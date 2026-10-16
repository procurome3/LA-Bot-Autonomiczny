"""Structured champion-kit database for autonomous Live Arena V16.2.

Facts only: rarity/affinity/faction, skill mechanics, cooldowns, effects and
turn durations.  External tier/rating/win-rate/pick-rate/ban-rate fields are
intentionally not part of the schema and are never used for decisions.

The runtime is deliberately tolerant of partial coverage.  The database can
index every Legendary/Mythical champion while detailed skill records are filled
incrementally by tools/update_champion_database.py.  Existing hand-authored
Live Arena knowledge remains a tactical override/fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple
import json
import re


DEFAULT_DATABASE_PATH = "./data/champion_database.json"


def canonical_key(value: object) -> str:
    text = str(value or "").strip().lower()
    for prefix in (
        "arena_live_enemy_", "arena_live_opponent_", "arena_live_ban_",
        "arena_live_lead_", "arena_live_", "skill_",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = re.sub(r"\.png$", "", text, flags=re.I)
    text = re.sub(r"_a\d+$", "", text)
    text = re.sub(r"_f[12]$", "", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    aliases = {
        "glicea": "gliseah",
        "gliseah_soulguide": "gliseah",
        "night_queen_krixia": "krixia",
        "lord_entertainer_fabian": "fabian",
        "siphie": "siphi",
        "siphi_the_lost_bride": "siphi",
        "yummeko": "yumeko",
        "cruetaxa": "cruetraxa",
        "embris": "embrys",
        "shuzhen": "shu_zhen",
        "shu_zhen_the_valorous": "shu_zhen",
        "telenna": "talenna",
        "telena": "talenna",
        "thelena": "talenna",
        "komidus_darksmile": "komidus",
        "nais_the_shadowthief": "nais",
        "marius_the_gallant": "marius",
        "tekteon_fissureflesh": "tekteon",
        "vestele_riverthorn": "vestele",
        "arbiter": "arbiter",
        "lady_mikage": "mikage",
        "starsage_galathir": "galathir",
        "joan_the_luminant": "joan",
        "embrys_the_anomaly": "embrys",
        "theodosia_the_disgraced": "theodosia",
        "ash_nar_dragonsoul": "ashnar_dragonsoul",
        "april_o_neil": "april_oneil",
        "kro_khad_the_throatripper": "krokhad_the_throatripper",
        "krok_mar_the_devourer": "krokmar_the_devourer",
        "losan_k_leth": "losan_kleth",
        "ma_shalled": "mashalled",
        "mavara_the_web_diviner": "mavara",
        "mithrala_lifebane": "mithrala",
        "nekhret_the_great": "nekhret",
        "packmaster_shy_ek": "packmaster_shyek",
        "pelops_the_victor": "pelops",
        "sanguine_maria": "maria",
        "ultimate_deathknight": "ultimate_death_knight",
        "wight_queen_ankora": "ankora",
        "khamir_the_scaled_eye": "khamir_scald_eye",
    }
    return aliases.get(text, text)


def family_form(value: object) -> Tuple[str, str]:
    """Return (root, form). Form is base/alternate/unknown.

    Combat families use _f1/_f2 for mythical forms.  The database uses
    forms.base/forms.alternate; ordinary champions use forms.base.
    """
    raw = str(value or "").strip().lower()
    form = "unknown"
    if re.search(r"_f1(?:_a\d+)?$", raw):
        form = "base"
    elif re.search(r"_f2(?:_a\d+)?$", raw):
        form = "alternate"
    return canonical_key(raw), form


@dataclass(frozen=True)
class EffectRecord:
    kind: str
    name: str = ""
    target: str = ""
    duration_turns: Optional[int] = None
    chance_percent: Optional[float] = None
    value_percent: Optional[float] = None
    amount: Optional[float] = None
    irresistible: bool = False
    chance_booked_percent: Optional[float] = None
    value_basis: str = ""
    conditions: Tuple[Mapping[str, object], ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "EffectRecord":
        def opt_num(key: str):
            value = raw.get(key)
            if value is None or value == "":
                return None
            try:
                return float(value)
            except Exception:
                return None

        duration = opt_num("duration_turns")
        return cls(
            kind=str(raw.get("kind") or "").strip().lower(),
            name=str(raw.get("name") or "").strip(),
            target=str(raw.get("target") or "").strip().lower(),
            duration_turns=int(duration) if duration is not None else None,
            chance_percent=opt_num("chance_percent"),
            value_percent=opt_num("value_percent"),
            amount=opt_num("amount"),
            irresistible=bool(raw.get("irresistible", False)),
            chance_booked_percent=opt_num("chance_booked_percent"),
            value_basis=str(raw.get("value_basis") or ""),
            conditions=tuple(x for x in raw.get("conditions", ()) if isinstance(x, Mapping)),
        )


@dataclass(frozen=True)
class SkillRecord:
    skill_id: str
    name: str = ""
    form: str = "base"
    cooldown_base: Optional[int] = None
    cooldown_booked: Optional[int] = None
    target_type: str = "unknown"
    attack_type: str = "unknown"
    hits: Optional[int] = None
    tags: frozenset[str] = frozenset()
    effects: Tuple[EffectRecord, ...] = ()
    parse_confidence: float = 0.0
    clickable: bool = True
    selection_target: str = "unknown"

    @classmethod
    def from_mapping(cls, sid: str, raw: Mapping[str, object], *, form: str = "base") -> "SkillRecord":
        def opt_int(key: str):
            value = raw.get(key)
            if value is None or value == "":
                return None
            try:
                return int(float(value))
            except Exception:
                return None

        effects = tuple(
            EffectRecord.from_mapping(x)
            for x in (raw.get("effects") or ())
            if isinstance(x, Mapping)
        )
        return cls(
            skill_id=str(sid).upper(),
            name=str(raw.get("name") or "").strip(),
            form=str(raw.get("form") or form or "base").strip().lower(),
            cooldown_base=opt_int("cooldown_base"),
            cooldown_booked=opt_int("cooldown_booked"),
            target_type=str(raw.get("target_type") or "unknown").strip().lower(),
            attack_type=str(raw.get("attack_type") or "unknown").strip().lower(),
            hits=opt_int("hits"),
            tags=frozenset(str(x).strip().lower() for x in (raw.get("tags") or ()) if str(x).strip()),
            effects=effects,
            parse_confidence=float(raw.get("parse_confidence") or 0.0),
            clickable=bool(raw.get("clickable", bool(re.fullmatch(r"A[1-4]", str(sid).upper())))),
            selection_target=str(raw.get("selection_target") or "unknown"),
        )


@dataclass
class ChampionRecord:
    key: str
    name: str
    rarity: str = ""
    affinity: str = ""
    affinity_group: str = ""
    faction: str = ""
    role: str = ""
    source_url: str = ""
    source_updated_at: str = ""
    status: str = "index_only"
    forms: Dict[str, Dict[str, SkillRecord]] = field(default_factory=dict)
    auras: Tuple[Mapping[str, object], ...] = ()

    def all_skills(self) -> Iterable[SkillRecord]:
        for skills in self.forms.values():
            yield from skills.values()

    def skill(self, skill_id: str, form: str = "unknown") -> Optional[SkillRecord]:
        sid = str(skill_id or "").upper()
        if form in self.forms and sid in self.forms[form]:
            return self.forms[form][sid]
        if form in {"base", "alternate"}:
            return None  # Missing F2 must never silently return an F1 skill.
        if "base" in self.forms and sid in self.forms["base"]:
            return self.forms["base"][sid]
        # If only one form has the skill, use it; otherwise ambiguity is safer
        # than silently choosing the wrong mythical form.
        hits = [skills[sid] for skills in self.forms.values() if sid in skills]
        if len(hits) == 1:
            return hits[0]
        return None


CONTROL_EFFECTS = {
    "stun", "freeze", "sleep", "provoke", "fear", "true fear",
    "sheep", "petrification", "block active skills", "block passive skills",
}
PROTECTION_EFFECTS = {
    "shield", "strengthen", "increase def", "block damage", "unkillable",
    "ally protection", "veil", "perfect veil", "stone skin", "stoneskin",
    "taunt", "poison cloud", "intercept",
}
CLEANSE_EFFECTS = {"cleanse", "remove debuffs", "block debuffs"}
STRIP_EFFECTS = {"remove buffs", "steal buffs", "decrease buff duration"}
LOCKOUT_EFFECTS = {"increase cooldown", "full cooldown", "block active skills", "block passive skills"}
TURN_METER_EFFECTS = {"turn meter fill", "turn meter decrease", "turn meter steal", "increase spd", "decrease spd"}
REVIVE_EFFECTS = {"revive", "revive on death"}
ANTI_REVIVE_EFFECTS = {"block revive", "destroy max hp"}


def _effect_names(skill: SkillRecord) -> Set[str]:
    return {str(e.name or e.kind).strip().lower() for e in skill.effects
            if (e.name or e.kind) and e.kind not in {"immunity", "ignore_status", "requirement", "reference"}}


def derived_tags(skill: SkillRecord, attack_type_fallback: str = "") -> Set[str]:
    tags = set(skill.tags)
    names = _effect_names(skill)
    attack = str(skill.attack_type or attack_type_fallback or "").lower()

    if attack in {"single", "aoe"}:
        tags.add("damage")
    if attack == "single":
        tags.add("single")
    if attack == "aoe":
        tags.add("aoe")
    if attack in {"self", "ally_living", "ally_dead"}:
        tags.add("support")
    if attack == "ally_dead" or names & REVIVE_EFFECTS:
        tags.update({"support", "revive"})
    if attack == "transform":
        tags.add("transform")

    if names & CONTROL_EFFECTS:
        tags.add("control")
    if names & PROTECTION_EFFECTS:
        tags.update({"support", "protection"})
    if names & CLEANSE_EFFECTS:
        tags.update({"support", "cleanse"})
    if names & STRIP_EFFECTS:
        tags.add("strip")
    if names & LOCKOUT_EFFECTS:
        tags.update({"control", "lockout"})
    if names & TURN_METER_EFFECTS:
        tags.add("turn_meter")
    if "increase spd" in names or any(e.kind == "speed" and (e.amount or 0) > 0 for e in skill.effects):
        tags.add("speed")
    if names & ANTI_REVIVE_EFFECTS:
        tags.add("anti_revive")
    if any(e.kind == "heal" for e in skill.effects):
        tags.update({"support", "heal"})
    if any(e.kind == "extra_turn" for e in skill.effects):
        tags.add("extra_turn")
    return tags


class ChampionDatabase:
    def __init__(self, path: str = DEFAULT_DATABASE_PATH):
        self.path = Path(path)
        self.champions: Dict[str, ChampionRecord] = {}
        self.meta: Dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, Mapping):
            return
        self.meta = dict(raw.get("meta") or {}) if isinstance(raw.get("meta"), Mapping) else {}
        rows = raw.get("champions") or {}
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            rows = {str(x.get("key")): x for x in rows if isinstance(x, Mapping) and x.get("key")}
        if not isinstance(rows, Mapping):
            return
        for raw_key, data in rows.items():
            if not isinstance(data, Mapping):
                continue
            key = canonical_key(data.get("key") or raw_key)
            forms: Dict[str, Dict[str, SkillRecord]] = {}
            raw_forms = data.get("forms") or {}
            if isinstance(raw_forms, Mapping):
                for form_name, form_data in raw_forms.items():
                    if not isinstance(form_data, Mapping):
                        continue
                    raw_skills = form_data.get("skills") if "skills" in form_data else form_data
                    if not isinstance(raw_skills, Mapping):
                        continue
                    skills: Dict[str, SkillRecord] = {}
                    for sid, skill_data in raw_skills.items():
                        if isinstance(skill_data, Mapping):
                            skills[str(sid).upper()] = SkillRecord.from_mapping(str(sid), skill_data, form=str(form_name))
                    forms[str(form_name).lower()] = skills
            previous = self.champions.get(key)
            if previous and sum(len(s) for s in previous.forms.values()) > sum(len(s) for s in forms.values()):
                continue  # Preserve the complete kit when a partial alias follows.
            self.champions[key] = ChampionRecord(
                key=key,
                name=str(data.get("name") or raw_key),
                rarity=str(data.get("rarity") or "").lower(),
                affinity=str(data.get("affinity") or "").lower(),
                affinity_group=str(data.get("affinity_group") or "").lower(),
                faction=str(data.get("faction") or ""),
                role=str(data.get("role") or "").lower(),
                source_url=str(data.get("source_url") or ""),
                source_updated_at=str(data.get("source_updated_at") or ""),
                status=str(data.get("status") or "index_only"),
                forms=forms,
                auras=tuple(x for x in data.get("auras", ()) if isinstance(x, Mapping)),
            )

    def get(self, name: object) -> Optional[ChampionRecord]:
        return self.champions.get(canonical_key(name))

    def skill(self, family: object, skill_id: str) -> Optional[SkillRecord]:
        root, form = family_form(family)
        champ = self.champions.get(root)
        if champ is None:
            return None
        return champ.skill(skill_id, form=form)

    def coverage(self) -> Dict[str, int]:
        indexed = len(self.champions)
        detailed = sum(1 for c in self.champions.values() if any(c.forms.values()))
        return {"indexed": indexed, "detailed": detailed, "pending": max(0, indexed - detailed)}

    def derive_skill_profile(self, family: object, skill_id: str, attack_type: str = "") -> Optional[dict]:
        skill = self.skill(family, skill_id)
        if skill is None or not skill.clickable:
            return None
        tags = derived_tags(skill, attack_type)
        sid = str(skill_id).upper()
        base = {"A4": 70.0, "A3": 63.0, "A2": 55.0, "A1": 34.0, "P": 18.0}.get(sid, 42.0)
        tag_bonus = {
            "revive": 28, "lockout": 18, "control": 11, "strip": 9,
            "turn_meter": 10, "speed": 7, "cleanse": 8, "protection": 8,
            "anti_revive": 10, "heal": 5, "transform": 10,
        }
        base += sum(tag_bonus.get(tag, 0.0) for tag in tags)
        booked = skill.cooldown_booked if skill.cooldown_booked is not None else skill.cooldown_base
        if booked is None:
            booked = 1 if sid == "A1" else 3
        cooldown_value = max(0.0, float(booked - 1) * 8.0)
        opener = 0.0
        if tags & {"speed", "turn_meter", "control", "lockout", "strip", "transform"}:
            opener += 10.0
        if "revive" in tags:
            opener -= 8.0
        finisher = 12.0 if tags & {"single", "anti_revive"} else 0.0
        preserve = max(0.0, cooldown_value * (0.65 if "aoe" in tags else 0.35))
        return {
            "tags": sorted(tags),
            "base_utility": min(100.0, base),
            "cooldown_value": cooldown_value,
            "opener_bonus": opener,
            "finisher_bonus": finisher,
            "preserve_if_one_enemy": preserve,
        }

    def derive_champion_profile(self, name: object) -> Optional[dict]:
        champ = self.get(name)
        if champ is None or not any(champ.forms.values()):
            return None
        skills = list(champ.all_skills())
        tags: Set[str] = set()
        for skill in skills:
            tags.update(derived_tags(skill))

        def count(tag: str) -> int:
            return sum(1 for s in skills if tag in derived_tags(s))

        damage = 22.0 * count("damage") + 10.0 * count("aoe") + 8.0 * count("single")
        control = 24.0 * count("control")
        support = 16.0 * count("support") + 12.0 * count("heal")
        revive = 45.0 * count("revive")
        strip = 32.0 * count("strip")
        lockout = 38.0 * count("lockout")
        anti_revive = 34.0 * count("anti_revive")
        turn_meter = 28.0 * count("turn_meter")
        cleanse = 28.0 * count("cleanse")
        protection = 28.0 * count("protection")
        speed_pressure = 18.0 * count("speed") + 0.65 * turn_meter
        durability = 0.45 * protection + 0.20 * support

        # These are derived kit metrics, NOT imported rankings/ratings.
        threat = 42.0 + 0.12 * damage + 0.18 * control + 0.16 * lockout + 0.10 * strip + 0.08 * turn_meter + 0.07 * revive
        base_pick = 42.0 + 0.09 * damage + 0.10 * control + 0.09 * support + 0.10 * turn_meter + 0.08 * strip + 0.08 * revive
        roles = set()
        for tag in ("damage", "control", "support", "revive", "strip", "lockout", "anti_revive", "turn_meter", "cleanse", "protection"):
            if tag in tags:
                roles.add(tag)
        speed_aura = 0.0
        for aura in champ.auras:
            if str(aura.get("type", "")).lower() != "speed":
                continue
            if str(aura.get("location", "")).lower() not in {"arena", "all battles"}:
                continue
            if str(aura.get("faction", "0")) not in {"", "0"} or aura.get("rules"):
                continue
            try:
                speed_aura = max(speed_aura, float(aura.get("strength") or 0))
            except (TypeError, ValueError):
                continue
        return {
            "roles": sorted(roles),
            "base_pick": min(100.0, base_pick),
            "threat": min(100.0, threat),
            "leader": min(100.0, speed_aura * 2.5),
            "speed_aura_percent": speed_aura,
            "speed_pressure": min(100.0, speed_pressure),
            "durability": min(100.0, durability),
            "damage": min(100.0, damage),
            "control": min(100.0, control),
            "support": min(100.0, support),
            "revive": min(100.0, revive),
            "strip": min(100.0, strip),
            "lockout": min(100.0, lockout),
            "anti_revive": min(100.0, anti_revive),
            "turn_meter": min(100.0, turn_meter),
            "cleanse": min(100.0, cleanse),
            "protection": min(100.0, protection),
        }
