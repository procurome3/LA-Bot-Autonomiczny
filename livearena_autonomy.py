"""Autonomous decision layer for Live Arena V16.

This module is deliberately pure-Python and does not click anything.  It sits
between perception and the existing guarded action layer:

    vision/perception -> structured state -> utility scoring -> ranked action

Hard legality remains in the existing combat engine (Veil, Stoneskin policy,
Unkillable, revive confirmation, cooldown detection, click guards).  Autonomy
may reorder *legal* candidates, but cannot turn an illegal/unknown action into a
blind click.

The engine is explainable: every ranking returns a numeric score and component
breakdown.  Decisions are optionally written to JSONL for replay/debugging.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
import json
import math
import os
import time

from champion_database import ChampionDatabase, DEFAULT_DATABASE_PATH


# ---------------------------------------------------------------------------
# Configuration defaults.  livearena_config may override these at runtime.
# ---------------------------------------------------------------------------
DEFAULT_AUTONOMY_ENABLED = True
DEFAULT_KNOWLEDGE_PATH = "./livearena_autonomy_knowledge.json"
DEFAULT_CHAMPION_DB_PATH = DEFAULT_DATABASE_PATH
DEFAULT_TELEMETRY_PATH = "./logs/livearena_autonomy.jsonl"
DEFAULT_LEARNING_PATH = "./state/livearena_autonomy_learning.json"


def _config_value(name: str, default):
    """Late config lookup to avoid import cycles during module initialization."""
    try:
        import livearena_config as cfg
        return getattr(cfg, name, default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Helpers / canonical names
# ---------------------------------------------------------------------------
def _norm(value: object) -> str:
    text = str(value or "").strip().lower()
    for prefix in (
        "arena_live_enemy_", "arena_live_opponent_", "arena_live_ban_",
        "arena_live_lead_", "arena_live_", "skill_",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.endswith(".png"):
        text = text[:-4]
    if text.endswith(".PNG"):
        text = text[:-4]
    # preserve mythical form for skill knowledge, strip for draft identity elsewhere
    return text.strip("_ ")


def champion_root(value: object) -> str:
    import re
    text = _norm(value)
    text = re.sub(r"_a\d+$", "", text)
    text = re.sub(r"_f[12]$", "", text)
    aliases = {
        "glicea": "gliseah", "galathier": "galathir", "yummeko": "yumeko",
        "siphie": "siphi", "cruetaxa": "cruetraxa", "embris": "embrys",
        "shuzhen": "shu_zhen", "telenna": "talenna", "telena": "talenna",
        "thelena": "talenna",
    }
    return aliases.get(text, text)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _unique(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for value in values:
        key = champion_root(value)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


# ---------------------------------------------------------------------------
# Explainable scoring records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScoreBreakdown:
    score: float
    components: Tuple[Tuple[str, float], ...] = ()
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "score": round(float(self.score), 3),
            "components": {k: round(float(v), 3) for k, v in self.components},
            "reason": self.reason,
        }


def _score(components: Mapping[str, float], reason: str = "") -> ScoreBreakdown:
    return ScoreBreakdown(
        score=float(sum(float(v) for v in components.values())),
        components=tuple((str(k), float(v)) for k, v in components.items()),
        reason=reason,
    )


@dataclass
class ChampionKnowledge:
    name: str
    roles: Set[str] = field(default_factory=set)
    base_pick: float = 50.0
    threat: float = 50.0
    leader: float = 0.0
    speed_pressure: float = 0.0
    durability: float = 0.0
    damage: float = 0.0
    control: float = 0.0
    support: float = 0.0
    revive: float = 0.0
    strip: float = 0.0
    lockout: float = 0.0
    anti_revive: float = 0.0
    turn_meter: float = 0.0
    cleanse: float = 0.0
    protection: float = 0.0
    counters: Dict[str, float] = field(default_factory=dict)
    vulnerable_to: Dict[str, float] = field(default_factory=dict)
    synergy: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, name: str, raw: Mapping[str, object]) -> "ChampionKnowledge":
        def num(key: str, default=0.0) -> float:
            try:
                return float(raw.get(key, default))
            except Exception:
                return float(default)

        def fmap(key: str) -> Dict[str, float]:
            value = raw.get(key, {})
            if not isinstance(value, Mapping):
                return {}
            out: Dict[str, float] = {}
            for k, v in value.items():
                try:
                    out[champion_root(k)] = float(v)
                except Exception:
                    continue
            return out

        roles = raw.get("roles", ())
        return cls(
            name=champion_root(name),
            roles={str(x).strip().lower() for x in (roles or ()) if str(x).strip()},
            base_pick=num("base_pick", 50.0),
            threat=num("threat", 50.0),
            leader=num("leader"),
            speed_pressure=num("speed_pressure"),
            durability=num("durability"),
            damage=num("damage"),
            control=num("control"),
            support=num("support"),
            revive=num("revive"),
            strip=num("strip"),
            lockout=num("lockout"),
            anti_revive=num("anti_revive"),
            turn_meter=num("turn_meter"),
            cleanse=num("cleanse"),
            protection=num("protection"),
            counters=fmap("counters"),
            vulnerable_to=fmap("vulnerable_to"),
            synergy=fmap("synergy"),
        )


@dataclass
class SkillKnowledge:
    family: str
    skill_id: str
    tags: Set[str] = field(default_factory=set)
    base_utility: float = 50.0
    cooldown_value: float = 0.0
    opener_bonus: float = 0.0
    finisher_bonus: float = 0.0
    preserve_if_one_enemy: float = 0.0

    @classmethod
    def from_mapping(cls, family: str, skill_id: str, raw: Mapping[str, object]) -> "SkillKnowledge":
        def num(key: str, default=0.0) -> float:
            try:
                return float(raw.get(key, default))
            except Exception:
                return float(default)
        return cls(
            family=str(family).lower(),
            skill_id=str(skill_id).upper(),
            tags={str(x).strip().lower() for x in (raw.get("tags", ()) or ()) if str(x).strip()},
            base_utility=num("base_utility", 50.0),
            cooldown_value=num("cooldown_value"),
            opener_bonus=num("opener_bonus"),
            finisher_bonus=num("finisher_bonus"),
            preserve_if_one_enemy=num("preserve_if_one_enemy"),
        )


# ---------------------------------------------------------------------------
# Persistent lightweight learning
# ---------------------------------------------------------------------------
class LearningStore:
    """Small Bayesian-style outcome store.

    It intentionally changes scores slowly.  A bad streak cannot rewrite the
    strategy overnight.  Data may be populated automatically from reliable
    outcome hints or externally/manual tooling later.
    """

    def __init__(self, path: str = DEFAULT_LEARNING_PATH):
        self.path = Path(path)
        self.data = {"champions": {}, "matchups": {}, "version": 1}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, Mapping):
                self.data.update(raw)
        except Exception:
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    @staticmethod
    def _entry(container: MutableMapping[str, object], key: str) -> MutableMapping[str, float]:
        entry = container.setdefault(key, {"wins": 0.0, "losses": 0.0})
        if not isinstance(entry, MutableMapping):
            entry = {"wins": 0.0, "losses": 0.0}
            container[key] = entry
        return entry  # type: ignore[return-value]

    def record_outcome(self, own: Iterable[str], enemy: Iterable[str], won: bool, weight: float = 1.0) -> None:
        own_roots = _unique(own)
        enemy_roots = _unique(enemy)
        field = "wins" if won else "losses"
        weight = _clamp(weight, 0.05, 2.0)

        champs = self.data.setdefault("champions", {})
        matchups = self.data.setdefault("matchups", {})
        if not isinstance(champs, MutableMapping) or not isinstance(matchups, MutableMapping):
            return

        for champ in own_roots:
            e = self._entry(champs, champ)
            e[field] = float(e.get(field, 0.0)) + weight
            for opp in enemy_roots:
                m = self._entry(matchups, f"{champ}|{opp}")
                m[field] = float(m.get(field, 0.0)) + weight
        self.save()

    @staticmethod
    def _posterior_bonus(entry: Mapping[str, object], scale: float) -> float:
        # Beta(3,3) prior keeps early samples from dominating.
        w = float(entry.get("wins", 0.0) or 0.0)
        l = float(entry.get("losses", 0.0) or 0.0)
        p = (w + 3.0) / (w + l + 6.0)
        n = w + l
        confidence = min(1.0, n / 20.0)
        return (p - 0.5) * 2.0 * scale * confidence

    def champion_bonus(self, champion: str) -> float:
        champs = self.data.get("champions", {})
        if not isinstance(champs, Mapping):
            return 0.0
        entry = champs.get(champion_root(champion), {})
        return self._posterior_bonus(entry, 10.0) if isinstance(entry, Mapping) else 0.0

    def matchup_bonus(self, champion: str, enemies: Iterable[str]) -> float:
        matchups = self.data.get("matchups", {})
        if not isinstance(matchups, Mapping):
            return 0.0
        total = 0.0
        count = 0
        for enemy in _unique(enemies):
            entry = matchups.get(f"{champion_root(champion)}|{enemy}", {})
            if isinstance(entry, Mapping):
                total += self._posterior_bonus(entry, 7.0)
                count += 1
        return total / max(1, count)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
class AutonomyTelemetry:
    def __init__(self, path: str = DEFAULT_TELEMETRY_PATH):
        self.path = Path(path)

    def emit(self, kind: str, payload: Mapping[str, object]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": time.time(),
                "kind": str(kind),
                **dict(payload),
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
class KnowledgeBase:
    def __init__(self, path: str = DEFAULT_KNOWLEDGE_PATH, champion_db_path: str = DEFAULT_CHAMPION_DB_PATH):
        self.path = Path(path)
        self.champion_db = ChampionDatabase(champion_db_path)
        self.champions: Dict[str, ChampionKnowledge] = {}
        self.skills: Dict[Tuple[str, str], SkillKnowledge] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

        champions = raw.get("champions", {}) if isinstance(raw, Mapping) else {}
        if isinstance(champions, Mapping):
            for name, data in champions.items():
                if isinstance(data, Mapping):
                    k = ChampionKnowledge.from_mapping(str(name), data)
                    self.champions[k.name] = k

        skills = raw.get("skills", {}) if isinstance(raw, Mapping) else {}
        if isinstance(skills, Mapping):
            for family, family_skills in skills.items():
                if not isinstance(family_skills, Mapping):
                    continue
                for sid, data in family_skills.items():
                    if isinstance(data, Mapping):
                        s = SkillKnowledge.from_mapping(str(family), str(sid), data)
                        self.skills[(str(family).lower(), s.skill_id)] = s

    def champion(self, name: str) -> ChampionKnowledge:
        root = champion_root(name)
        if root in self.champions:
            return self.champions[root]

        # V16.2: derive tactical metrics from factual kit mechanics when detailed
        # database coverage exists.  No HH tier/rating is imported or consulted.
        derived = self.champion_db.derive_champion_profile(root)
        if isinstance(derived, Mapping):
            return ChampionKnowledge.from_mapping(root, derived)

        # Unknown enemy identity must not be treated as harmless.  Use a neutral
        # but non-trivial prior while the factual record is still index-only.
        return ChampionKnowledge(name=root, base_pick=55.0, threat=62.0)

    def skill(self, family: str, skill_id: str, attack_type: str = "") -> SkillKnowledge:
        family_l = str(family or "").lower()
        sid = str(skill_id or "").upper()
        direct = self.skills.get((family_l, sid))
        if direct is not None:
            return direct
        root = champion_root(family_l)
        rooted = self.skills.get((root, sid))
        if rooted is not None:
            return rooted

        # Factual kit DB is the next source. Manual tactical records above remain
        # authoritative where they exist so known champion-specific behaviour is
        # not regressed by a parser update.
        derived = self.champion_db.derive_skill_profile(family_l, sid, attack_type)
        if isinstance(derived, Mapping):
            return SkillKnowledge.from_mapping(family_l, sid, derived)

        tags: Set[str] = set()
        attack = str(attack_type or "").lower()
        if attack == "ally_dead":
            tags.add("revive")
        elif attack in ("single", "aoe"):
            tags.add("damage")
            if attack == "aoe":
                tags.add("aoe")
        elif attack in ("self", "ally_living"):
            tags.add("support")
        elif attack == "transform":
            tags.add("transform")

        generic_base = {"A4": 72.0, "A3": 66.0, "A2": 58.0, "A1": 35.0}.get(sid, 45.0)
        return SkillKnowledge(family=family_l, skill_id=sid, tags=tags, base_utility=generic_base)

    def draft_scan_names(self, limit: int = 24) -> List[str]:
        ranked = sorted(
            self.champions.values(),
            key=lambda c: (c.threat, c.base_pick),
            reverse=True,
        )
        return [c.name for c in ranked[: max(0, int(limit))]]


# ---------------------------------------------------------------------------
# Opponent archetype modelling
# ---------------------------------------------------------------------------
@dataclass
class OpponentModel:
    speed: float = 0.0
    damage: float = 0.0
    control: float = 0.0
    sustain: float = 0.0
    revive: float = 0.0
    protection: float = 0.0
    lockout: float = 0.0
    strip: float = 0.0
    archetype: str = "balanced"

    def as_dict(self) -> dict:
        return {
            "speed": round(self.speed, 2), "damage": round(self.damage, 2),
            "control": round(self.control, 2), "sustain": round(self.sustain, 2),
            "revive": round(self.revive, 2), "protection": round(self.protection, 2),
            "lockout": round(self.lockout, 2), "strip": round(self.strip, 2),
            "archetype": self.archetype,
        }


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------
class AutonomyController:
    def __init__(
        self,
        *,
        enabled: bool = DEFAULT_AUTONOMY_ENABLED,
        knowledge_path: str = DEFAULT_KNOWLEDGE_PATH,
        champion_db_path: str = DEFAULT_CHAMPION_DB_PATH,
        telemetry_path: str = DEFAULT_TELEMETRY_PATH,
        learning_path: str = DEFAULT_LEARNING_PATH,
    ):
        self.enabled = bool(enabled)
        self.knowledge = KnowledgeBase(knowledge_path, champion_db_path)
        self.learning = LearningStore(learning_path)
        self.telemetry = AutonomyTelemetry(telemetry_path)
        self._last_console_rank: Dict[str, Tuple[object, ...]] = {}

    def _console_rank_once(self, kind: str, signature: Tuple[object, ...], scored) -> None:
        """Print explainable top choices only when the game state/ranking changes."""
        key = str(kind)
        compact = tuple((name, round(float(score.score), 1)) for name, score, *_ in scored[:5])
        full_sig = tuple(signature) + compact
        if self._last_console_rank.get(key) == full_sig:
            return
        self._last_console_rank[key] = full_sig
        if compact:
            print(
                f"AUTONOMY {key.upper()}: "
                + " > ".join(f"{name}={score:.1f}" for name, score in compact)
            )

    # ---------------- Draft -------------------------------------------------
    def opponent_model(self, enemies: Iterable[str]) -> OpponentModel:
        roots = _unique(enemies)
        if not roots:
            return OpponentModel()
        profiles = [self.knowledge.champion(x) for x in roots]
        n = float(len(profiles))
        model = OpponentModel(
            speed=sum(p.speed_pressure + 0.45 * p.turn_meter for p in profiles) / n,
            damage=sum(p.damage for p in profiles) / n,
            control=sum(p.control for p in profiles) / n,
            sustain=sum(p.support + 0.6 * p.cleanse for p in profiles) / n,
            revive=sum(p.revive for p in profiles) / n,
            protection=sum(p.protection + 0.35 * p.durability for p in profiles) / n,
            lockout=sum(p.lockout for p in profiles) / n,
            strip=sum(p.strip for p in profiles) / n,
        )
        axes = {
            "speed-control": model.speed + model.control + 0.7 * model.lockout,
            "burst": model.damage + 0.35 * model.speed,
            "sustain": model.sustain + model.revive + model.protection,
            "control": model.control + model.lockout + 0.3 * model.strip,
        }
        model.archetype = max(axes, key=axes.get) if max(axes.values(), default=0) > 25 else "balanced"
        return model

    @staticmethod
    def _role_counts(profiles: Sequence[ChampionKnowledge]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for profile in profiles:
            for role in profile.roles:
                counts[role] = counts.get(role, 0) + 1
        return counts

    def score_pick(self, candidate: str, enemies: Iterable[str], own: Iterable[str]) -> ScoreBreakdown:
        c = self.knowledge.champion(candidate)
        enemy_roots = _unique(enemies)
        own_roots = _unique(own)
        own_profiles = [self.knowledge.champion(x) for x in own_roots]
        model = self.opponent_model(enemy_roots)
        roles = self._role_counts(own_profiles)

        base_weight = float(_config_value("AUTONOMY_BASE_PICK_WEIGHT", 0.42))
        comp: Dict[str, float] = {
            # Static profile strength is a prior, not the decision.  V16 used the
            # full 70-90 base score and therefore almost reproduced pick_priority.
            "base_prior": base_weight * c.base_pick,
            "learned": self.learning.champion_bonus(c.name) + self.learning.matchup_bonus(c.name, enemy_roots),
        }

        # Direct known matchups receive enough weight to actually beat a static
        # base prior, but remain soft evidence rather than a hard rule.
        direct = 0.0
        vulnerability = 0.0
        for enemy in enemy_roots:
            direct += float(c.counters.get(enemy, 0.0))
            vulnerability += float(c.vulnerable_to.get(enemy, 0.0))
        comp["direct_counters"] = 1.55 * direct
        comp["known_risk"] = -1.35 * vulnerability

        # Team role completion.  Repeated copies of the same role are explicitly
        # penalised, so the fifth pick is no longer simply the next base-priority
        # champion with overlapping damage/control.
        role_bonus = 0.0
        redundancy = 0.0
        high_value_roles = {
            "speed": 10.0, "control": 8.0, "damage": 9.0, "revive": 10.0,
            "cleanse": 8.0, "strip": 7.0, "protection": 8.0, "lockout": 8.0,
            "anti_revive": 7.0, "turn_meter": 5.0,
        }
        for role in c.roles:
            weight = high_value_roles.get(role, 3.0)
            count = roles.get(role, 0)
            if count == 0:
                role_bonus += weight
            elif count == 1:
                redundancy -= 0.18 * weight
            else:
                redundancy -= (0.45 + 0.18 * (count - 2)) * weight
        comp["role_coverage"] = role_bonus
        comp["role_redundancy"] = redundancy

        # Broad early picks are valuable before the enemy composition is known.
        if len(own_roots) <= 1:
            comp["early_flexibility"] = 1.8 * len(set(c.roles))

        # Pairwise synergy.
        synergy = 0.0
        for ally in own_roots:
            synergy += float(c.synergy.get(ally, 0.0))
            synergy += 0.5 * float(self.knowledge.champion(ally).synergy.get(c.name, 0.0))
        comp["synergy"] = 1.15 * synergy

        # React to the observed enemy archetype.  These terms intentionally carry
        # more weight than in V16 because first-battle footage showed the draft
        # remaining nearly identical to the legacy profile even after enemies were
        # recognised.
        response = 0.0
        response += model.speed * (0.12 * c.speed_pressure + 0.10 * c.durability + 0.09 * c.protection) / 100.0
        response += model.damage * (0.12 * c.protection + 0.11 * c.revive + 0.08 * c.durability) / 100.0
        response += model.control * (0.13 * c.cleanse + 0.10 * c.support + 0.08 * c.durability) / 100.0
        response += model.sustain * (0.12 * c.strip + 0.10 * c.damage + 0.09 * c.anti_revive) / 100.0
        response += model.revive * (0.14 * c.anti_revive + 0.08 * c.control) / 100.0
        response += model.lockout * (0.08 * c.durability + 0.08 * c.protection + 0.08 * c.speed_pressure) / 100.0
        comp["archetype_response"] = response

        # High-threat enemy teams reward picks that can either race them, protect
        # through them, or deny sustain.
        if enemy_roots:
            threat_avg = sum(self.knowledge.champion(e).threat for e in enemy_roots) / len(enemy_roots)
            comp["threat_response"] = (threat_avg / 100.0) * (
                0.055 * c.speed_pressure
                + 0.060 * c.protection
                + 0.050 * c.durability
                + 0.045 * c.control
                + 0.045 * c.anti_revive
            )

        # Fourth/fifth picks close composition holes aggressively.
        if len(own_roots) >= 3:
            missing = 0.0
            if not any("damage" in p.roles for p in own_profiles) and "damage" in c.roles:
                missing += 14.0
            if not any("speed" in p.roles for p in own_profiles) and "speed" in c.roles:
                missing += 11.0
            if not any("cleanse" in p.roles for p in own_profiles) and "cleanse" in c.roles and model.control >= 35:
                missing += 11.0
            if not any("strip" in p.roles for p in own_profiles) and "strip" in c.roles and model.sustain >= 35:
                missing += 9.0
            if not any(("revive" in p.roles or "protection" in p.roles) for p in own_profiles) and (
                "revive" in c.roles or "protection" in c.roles
            ):
                missing += 10.0
            if not any("anti_revive" in p.roles for p in own_profiles) and "anti_revive" in c.roles and model.revive >= 25:
                missing += 9.0
            comp["late_pick_completion"] = missing

        return _score(comp, reason=f"pick-vs-{model.archetype}")

    def rank_pick_candidates(
        self, candidates: Iterable[str], enemies: Iterable[str], own: Iterable[str],
        manual_priority: Iterable[str] = (),
    ) -> List[str]:
        original = _unique(candidates)
        manual = _unique(manual_priority)
        manual_rank = {name: i for i, name in enumerate(manual)}
        scored = []
        for idx, name in enumerate(original):
            base = self.score_pick(name, enemies, own)
            components = dict(base.components)
            if name in manual_rank:
                # Manual counter rules are a prior, not a command.  V16's +20
                # bonus was strong enough to recreate the legacy draft almost
                # verbatim.
                prior = float(_config_value("AUTONOMY_MANUAL_COUNTER_BONUS", 4.0))
                components["manual_counter_rule"] = max(0.5, prior - 0.75 * manual_rank[name])
            score = _score(components, base.reason)
            scored.append((name, score, idx))
        scored.sort(key=lambda row: (-row[1].score, row[2]))
        result = [name for name, _, _ in scored]
        self._console_rank_once(
            "pick",
            (tuple(_unique(enemies)), tuple(_unique(own))),
            scored,
        )
        self.telemetry.emit("draft_pick_rank", {
            "enemies": _unique(enemies), "own": _unique(own),
            "manual_priority": manual,
            "ranking": [{"name": n, **sc.as_dict()} for n, sc, _ in scored],
        })
        return result

    def score_ban(self, enemy: str, enemy_team: Iterable[str], own: Iterable[str]) -> ScoreBreakdown:
        e = self.knowledge.champion(enemy)
        own_roots = _unique(own)
        team_roots = _unique(enemy_team)
        comp: Dict[str, float] = {
            "base_threat": e.threat,
            "burst": 0.18 * e.damage,
            "control": 0.17 * e.control,
            "lockout": 0.22 * e.lockout,
            "speed": 0.13 * e.speed_pressure + 0.08 * e.turn_meter,
            "revive": 0.15 * e.revive,
            "strip": 0.10 * e.strip,
        }
        if champion_root(enemy) not in self.knowledge.champions:
            # An unknown portrait is uncertainty, not safety.  This prevents a
            # newly added champion from being automatically ranked below every
            # familiar threat merely because its knowledge entry is incomplete.
            comp["unknown_threat_uncertainty"] = 10.0

        # Threat specifically against our current draft.
        matchup = 0.0
        for ally in own_roots:
            ally_k = self.knowledge.champion(ally)
            matchup += float(e.counters.get(ally, 0.0))
            matchup += 0.5 * float(ally_k.vulnerable_to.get(e.name, 0.0))
        comp["counter_to_own"] = matchup

        # Remove a synergy hub from the enemy composition.
        synergy = 0.0
        for mate in team_roots:
            if mate == e.name:
                continue
            synergy += float(e.synergy.get(mate, 0.0))
            synergy += 0.5 * float(self.knowledge.champion(mate).synergy.get(e.name, 0.0))
        comp["enemy_synergy_hub"] = synergy
        return _score(comp, reason="ban-threat")

    def rank_ban_candidates(
        self, candidates: Iterable[str], enemy_team: Iterable[str], own: Iterable[str],
        manual_priority: Iterable[str] = (),
    ) -> List[str]:
        enemy_set = set(_unique(enemy_team))
        original = [x for x in _unique(candidates) if not enemy_set or x in enemy_set]
        if not original:
            original = _unique(candidates)
        manual = _unique(manual_priority)
        manual_rank = {name: i for i, name in enumerate(manual)}
        scored = []
        for idx, name in enumerate(original):
            base = self.score_ban(name, enemy_team, own)
            components = dict(base.components)
            if name in manual_rank:
                prior = float(_config_value("AUTONOMY_MANUAL_BAN_BONUS", 5.0))
                components["manual_ban_rule"] = max(0.5, prior - 0.75 * manual_rank[name])
            scored.append((name, _score(components, base.reason), idx))
        scored.sort(key=lambda row: (-row[1].score, row[2]))
        self._console_rank_once(
            "ban",
            (tuple(_unique(enemy_team)), tuple(_unique(own))),
            scored,
        )
        self.telemetry.emit("draft_ban_rank", {
            "enemy_team": _unique(enemy_team), "own": _unique(own),
            "manual_priority": manual,
            "ranking": [{"name": n, **sc.as_dict()} for n, sc, _ in scored],
        })
        return [name for name, _, _ in scored]

    def rank_leaders(self, candidates: Iterable[str], own: Iterable[str]) -> List[str]:
        own_set = set(_unique(own))
        original = [x for x in _unique(candidates) if not own_set or x in own_set]
        scored = []
        for idx, name in enumerate(original):
            c = self.knowledge.champion(name)
            components = {
                "leader": c.leader,
                "speed_pressure": 0.30 * c.speed_pressure,
                "team_value": 0.08 * (c.support + c.control + c.damage),
                "original_tiebreak": max(0.0, 1.0 - idx * 0.05),
            }
            scored.append((name, _score(components, "leader-utility"), idx))
        scored.sort(key=lambda row: (-row[1].score, row[2]))
        self._console_rank_once("leader", (tuple(_unique(own)),), scored)
        self.telemetry.emit("draft_leader_rank", {
            "own": _unique(own),
            "ranking": [{"name": n, **s.as_dict()} for n, s, _ in scored],
        })
        return [name for name, _, _ in scored]

    # ---------------- Combat -----------------------------------------------
    @staticmethod
    def _enemy_summary(enemy_states: Sequence[Mapping[str, object]]) -> dict:
        alive = [s for s in enemy_states if s.get("alive")]
        hps = [float(s.get("hp", 1.0) or 0.0) for s in alive]
        return {
            "alive": len(alive),
            "low_hp": sum(1 for hp in hps if hp <= 0.35),
            "critical_hp": sum(1 for hp in hps if hp <= 0.18),
            "avg_hp": sum(hps) / len(hps) if hps else 0.0,
            "stoneskin": sum(1 for s in alive if s.get("stoneskin") is True),
            "immune": sum(1 for s in alive if s.get("damage_immune") is True),
            "counterattack": sum(1 for s in alive if s.get("counterattack") is True),
        }

    @staticmethod
    def _ally_summary(ally_tracker: Mapping[int, Mapping[str, object]], ally_ratios: Mapping[int, float]) -> dict:
        dead = sum(1 for s in ally_tracker.values() if s.get("seen_alive") and s.get("dead"))
        living_ratios = [float(v) for slot, v in ally_ratios.items() if not ally_tracker.get(slot, {}).get("dead")]
        return {
            "dead": dead,
            "living": max(0, len(ally_tracker) - dead),
            "low": sum(1 for v in living_ratios if v < 0.035),
            "avg_ratio": sum(living_ratios) / len(living_ratios) if living_ratios else 0.0,
        }

    def score_skill(
        self,
        family: str,
        skill: Mapping[str, object],
        *,
        enemy_states: Sequence[Mapping[str, object]] = (),
        ally_tracker: Mapping[int, Mapping[str, object]] = {},
        ally_ratios: Mapping[int, float] = {},
        combat_context: Mapping[str, object] = {},
        opponent_families: Iterable[str] = (),
    ) -> ScoreBreakdown:
        sid = str(skill.get("skill_id") or "").upper()
        attack = str(skill.get("attack_type") or "").lower()
        knowledge = self.knowledge.skill(str(family), sid, attack)
        tags = set(knowledge.tags)
        enemy = self._enemy_summary(enemy_states)
        ally = self._ally_summary(ally_tracker, ally_ratios)
        action_counts = combat_context.get("family_action_counts", {})
        root = champion_root(family)
        acted = int(action_counts.get(root, 0)) if isinstance(action_counts, Mapping) else 0
        opponent_model = self.opponent_model(opponent_families)
        failed_map = combat_context.get("turn_failed_skills", {})

        base_weight = float(_config_value("AUTONOMY_SKILL_BASE_WEIGHT", 0.55))
        comp: Dict[str, float] = {"base_prior": base_weight * knowledge.base_utility}

        failure_key = f"{root}:{sid}"
        recent_failures = int(failed_map.get(failure_key, 0)) if isinstance(failed_map, Mapping) else 0
        if recent_failures > 0:
            comp["recent_execution_failure"] = -32.0 * min(2, recent_failures)

        # Perception confidence is only one source of evidence.
        combined = float(skill.get("combined_score", skill.get("score", 0.0)) or 0.0)
        comp["confidence"] = (combined - 0.50) * 14.0

        if acted == 0:
            comp["opener"] = knowledge.opener_bonus
        if bool(combat_context.get("extra_turn")):
            comp["extra_turn"] = 6.0 if "damage" in tags else 2.0

        # Team utility is state-dependent.  Support/protection stops being an
        # automatic high-base choice once the team is healthy and the opener is
        # already spent.
        if "revive" in tags:
            comp["revive_need"] = 34.0 * ally["dead"]
            if ally["dead"] <= 0:
                comp["revive_no_target"] = -120.0
        if "heal" in tags or "protection" in tags or "support" in tags:
            comp["team_pressure"] = 11.0 * ally["low"] + 4.0 * ally["dead"]
            if ally["low"] == 0 and ally["dead"] == 0 and acted > 0:
                comp["healthy_team_preserve"] = -9.0

        if "speed" in tags or "turn_meter" in tags:
            comp["tempo"] = 9.0 + 0.10 * opponent_model.speed
            if acted > 0:
                comp["tempo_late"] = -7.0

        if "control" in tags or "lockout" in tags:
            comp["control_targets"] = 5.5 * enemy["alive"] + 0.08 * (opponent_model.damage + opponent_model.lockout)
            if enemy["alive"] <= 1:
                comp["control_last_target"] = -9.0

        if "strip" in tags:
            comp["strip_vs_sustain"] = 5.0 * enemy["stoneskin"] + 0.11 * opponent_model.protection

        if "damage" in tags:
            comp["damage_targets"] = 2.5 * enemy["alive"]
            comp["kill_pressure"] = 13.0 * enemy["critical_hp"] + 6.0 * enemy["low_hp"]
            comp["immunity_penalty"] = -12.0 * enemy["immune"]

        if "aoe" in tags:
            if enemy["alive"] >= 3:
                comp["aoe_scale"] = 5.0 * (enemy["alive"] - 1)
            elif enemy["alive"] == 2:
                comp["aoe_scale"] = 1.5
            elif enemy["alive"] == 1:
                comp["aoe_last_target"] = -max(14.0, knowledge.preserve_if_one_enemy)

        if "single" in tags:
            comp["single_finish"] = 9.0 * enemy["low_hp"] + 10.0 * enemy["critical_hp"]

        if "anti_revive" in tags:
            comp["anti_revive"] = 0.14 * opponent_model.revive + 7.0 * enemy["critical_hp"]

        if "transform" in tags:
            comp["transform_timing"] = 24.0 if acted == 0 else -16.0

        if "cleanse" in tags:
            comp["cleanse_vs_control"] = 0.13 * (opponent_model.control + opponent_model.lockout)

        # Cooldown opportunity cost.  This is the part that lets a lower-base A1
        # or single-target skill beat a premium AoE when only one weak target is
        # left, which V16 rarely did.
        if sid != "A1":
            if enemy["alive"] == 1:
                comp["preserve_cooldown"] = -0.55 * knowledge.cooldown_value
            elif enemy["alive"] == 2 and enemy["critical_hp"] > 0:
                comp["preserve_cooldown"] = -0.28 * knowledge.cooldown_value
            elif enemy["alive"] >= 3:
                comp["cooldown_value"] = 0.18 * knowledge.cooldown_value

        if enemy["critical_hp"] > 0:
            comp["finisher"] = knowledge.finisher_bonus

        return _score(comp, reason=f"combat-{root}-{sid}")

    def rank_skill_ids(
        self,
        family: str,
        skills: Mapping[str, Mapping[str, object]],
        static_priority: Iterable[str],
        *,
        enemy_states: Sequence[Mapping[str, object]] = (),
        ally_tracker: Mapping[int, Mapping[str, object]] = {},
        ally_ratios: Mapping[int, float] = {},
        combat_context: Mapping[str, object] = {},
        opponent_families: Iterable[str] = (),
        min_score: float = 0.34,
        reorder_margin: float = 2.0,
    ) -> Tuple[Tuple[str, ...], Dict[str, ScoreBreakdown]]:
        """Rank READY skills while preserving strict uncertainty barriers.

        A missing/unknown higher-priority skill may never be moved behind a lower
        skill.  Ready skills are reordered only inside contiguous regions that do
        not cross such a barrier. Confirmed unavailable/ineligible entries are
        harmless and may be crossed because the strict tree already skips them.
        """
        base = [str(x).upper() for x in static_priority]
        scored: Dict[str, ScoreBreakdown] = {}

        def state_of(sid: str) -> str:
            item = skills.get(sid)
            if item is None:
                return "unknown"
            eligibility = str(item.get("eligibility", "eligible"))
            availability = str(item.get("availability", "unknown"))
            if eligibility == "ineligible" or availability == "unavailable":
                return "blocked"
            if eligibility != "eligible" or availability != "available":
                return "unknown"
            if float(item.get("score", 0.0) or 0.0) < float(min_score):
                return "unknown"
            return "ready"

        # Pre-score every ready item.
        for sid in base:
            item = skills.get(sid)
            if item is None or state_of(sid) != "ready":
                continue
            scored[sid] = self.score_skill(
                family, item,
                enemy_states=enemy_states,
                ally_tracker=ally_tracker,
                ally_ratios=ally_ratios,
                combat_context=combat_context,
                opponent_families=opponent_families,
            )

        # Two-ply own-action look-ahead.  We cannot know exact future RNG/turn
        # order from pixels, but we can model cooldown opportunity cost: after
        # spending one ready skill, the next best remaining action is the likely
        # follow-up.  A small gamma keeps immediate tactical value dominant.
        plan_scores: Dict[str, float] = {}
        ready_ids = [sid for sid in base if sid in scored and state_of(sid) == "ready"]
        for sid in ready_ids:
            future = max(
                (scored[other].score for other in ready_ids if other != sid),
                default=0.0,
            )
            plan_scores[sid] = scored[sid].score + 0.22 * future

        result: List[str] = []
        segment: List[str] = []

        def flush_segment() -> None:
            if not segment:
                return
            ready = [sid for sid in segment if state_of(sid) == "ready"]
            blocked = [sid for sid in segment if state_of(sid) == "blocked"]
            if len(ready) >= 2:
                indexed = {sid: i for i, sid in enumerate(segment)}
                ranked = sorted(
                    ready,
                    key=lambda sid: (-plan_scores.get(sid, scored[sid].score), indexed[sid]),
                )
                # Avoid noisy micro-reorders.  If the winner is only marginally
                # better than the static first ready skill, keep user order.
                static_ready = [sid for sid in segment if sid in ready]
                if static_ready and ranked and ranked[0] != static_ready[0]:
                    gain = (
                        plan_scores.get(ranked[0], scored[ranked[0]].score)
                        - plan_scores.get(static_ready[0], scored[static_ready[0]].score)
                    )
                    if gain < float(reorder_margin):
                        ranked = static_ready
            else:
                ranked = ready

            # Blocked items are preserved for diagnostics; the tree skips them.
            # Put them before a ranked ready item only when they originally were
            # before it. This keeps printed priority understandable.
            for sid in segment:
                if sid in blocked:
                    result.append(sid)
                elif sid in ranked:
                    if sid == ranked[0]:
                        result.extend([x for x in ranked if x not in result])
                    # other ready items were emitted with the first ranked item
            segment.clear()

        for sid in base:
            if state_of(sid) == "unknown":
                flush_segment()
                result.append(sid)  # strict barrier remains exactly here
            else:
                segment.append(sid)
        flush_segment()

        # Deduplicate while retaining order (segments can emit ranked items early).
        dedup: List[str] = []
        seen: Set[str] = set()
        for sid in result:
            if sid not in seen:
                seen.add(sid)
                dedup.append(sid)
        for sid in base:
            if sid not in seen:
                dedup.append(sid)

        priority = tuple(dedup)

        compact = tuple(
            (
                sid,
                round(float(plan_scores.get(sid, scored[sid].score)), 1),
                state_of(sid),
            )
            for sid in base
            if sid in scored
        )
        skill_key = f"skill:{champion_root(family)}"
        skill_sig = (tuple(priority), tuple(_unique(opponent_families)), compact)
        if self._last_console_rank.get(skill_key) != skill_sig:
            self._last_console_rank[skill_key] = skill_sig
            if compact:
                print(
                    f"AUTONOMY SKILL {champion_root(family)}: "
                    + " > ".join(
                        f"{sid}={score:.1f}[{state}]"
                        for sid, score, state in sorted(compact, key=lambda x: -x[1])
                    )
                    + f" | priority={priority}"
                )

        self.telemetry.emit("combat_skill_rank", {
            "family": family,
            "static_priority": base,
            "dynamic_priority": list(priority),
            "opponents": _unique(opponent_families),
            "states": {sid: state_of(sid) for sid in base},
            "scores": {sid: sc.as_dict() for sid, sc in scored.items()},
            "plan_scores": {sid: round(v, 3) for sid, v in plan_scores.items()},
        })
        return priority, scored

    def score_target(
        self,
        state: Mapping[str, object],
        *,
        attack_type: str,
        lowest_hp: bool,
        affinity_aware: bool,
        policy: Mapping[str, object] = {},
    ) -> ScoreBreakdown:
        hp = float(state.get("hp", 1.0) or 0.0)
        affinity = str(state.get("affinity", "unknown"))
        comp: Dict[str, float] = {
            "finish": (1.0 - _clamp(hp, 0.0, 1.0)) * (30.0 if lowest_hp else 18.0),
            "stable_slot": -0.05 * float(state.get("slot", 0) or 0),
        }
        if affinity_aware:
            comp["affinity"] = {
                "positive": 9.0, "neutral": 3.0, "unknown": 0.0, "negative": -18.0,
            }.get(affinity, 0.0)
        if state.get("stoneskin") is True:
            comp["stoneskin"] = -25.0
        if state.get("damage_immune") is True:
            comp["immune"] = -100.0
        if state.get("counterattack") is True:
            comp["counterattack"] = -8.0

        buff_mode = policy.get("buff_count")
        if isinstance(state.get("buff_count"), int):
            buffs = float(state.get("buff_count", 0))
            if buff_mode == "max":
                comp["buff_policy"] = 2.5 * buffs
            elif buff_mode == "min":
                comp["buff_policy"] = -2.5 * buffs
        for effect in policy.get("prefer_effects", ()) or ():
            if state.get(effect) is True:
                comp[f"prefer_{effect}"] = 20.0
        return _score(comp, reason="target-utility")

    def choose_target(
        self,
        pool: Sequence[Mapping[str, object]],
        *,
        attack_type: str,
        lowest_hp: bool,
        affinity_aware: bool,
        policy: Mapping[str, object] = {},
    ) -> Tuple[Optional[Mapping[str, object]], str, List[dict]]:
        if not pool:
            return None, "autonomy-no-target", []
        rows = []
        for idx, state in enumerate(pool):
            sc = self.score_target(
                state,
                attack_type=attack_type,
                lowest_hp=lowest_hp,
                affinity_aware=affinity_aware,
                policy=policy,
            )
            rows.append((state, sc, idx))
        rows.sort(key=lambda r: (-r[1].score, int(r[0].get("slot", 99))))
        target, score, _ = rows[0]
        trace = [
            {"slot": int(s.get("slot", 0) or 0), **sc.as_dict()}
            for s, sc, _ in rows
        ]
        return target, f"autonomy-target={score.score:.1f}", trace


# ---------------------------------------------------------------------------
# Singleton factory with late config import (avoids circular imports).
# ---------------------------------------------------------------------------
_CONTROLLER: Optional[AutonomyController] = None


def get_autonomy_controller() -> AutonomyController:
    global _CONTROLLER
    if _CONTROLLER is not None:
        return _CONTROLLER

    enabled = DEFAULT_AUTONOMY_ENABLED
    knowledge = DEFAULT_KNOWLEDGE_PATH
    champion_db = DEFAULT_CHAMPION_DB_PATH
    telemetry = DEFAULT_TELEMETRY_PATH
    learning = DEFAULT_LEARNING_PATH
    try:
        import livearena_config as cfg
        enabled = bool(getattr(cfg, "AUTONOMY_ENABLED", enabled))
        knowledge = str(getattr(cfg, "AUTONOMY_KNOWLEDGE_PATH", knowledge))
        champion_db = str(getattr(cfg, "AUTONOMY_CHAMPION_DB_PATH", champion_db))
        telemetry = str(getattr(cfg, "AUTONOMY_TELEMETRY_PATH", telemetry))
        learning = str(getattr(cfg, "AUTONOMY_LEARNING_PATH", learning))
    except Exception:
        pass

    env = os.environ.get("LIVEARENA_AUTONOMY")
    if env is not None:
        enabled = str(env).strip().lower() not in {"0", "false", "off", "no"}

    _CONTROLLER = AutonomyController(
        enabled=enabled,
        knowledge_path=knowledge,
        champion_db_path=champion_db,
        telemetry_path=telemetry,
        learning_path=learning,
    )
    return _CONTROLLER


def autonomy_enabled() -> bool:
    return bool(get_autonomy_controller().enabled)
