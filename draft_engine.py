"""Profile-driven Live Arena draft strategy.

The screen/UI logic remains in arenalive.py.  This module only decides ordered
candidate names for PICK, BAN and LEADER based on a JSON profile and the
opponent champions already recognised on screen.

Profile goals:
- different users can keep different strategies without editing Python;
- a bad/missing profile falls back to the legacy config order;
- all decisions are deterministic and bounded-cost;
- rule evaluation never clicks anything itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import re
import difflib
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


_NAME_PREFIXES = (
    "arena_live_enemy_",
    "arena_live_opponent_",
    "arena_live_ban_",
    "arena_live_lead_",
    "arena_live_",
    "skill_",
)

# Canonical spelling aliases used in user-editable JSON profiles.
# This keeps common manual spellings/typos from creating a new fake champion key.
_CANONICAL_NAME_ALIASES = {
    "glicea": "gliseah",
    "galathier": "galathir",
    "embris": "embrys",
    "yummeko": "yumeko",
    "siphie": "siphi",
    "cruetaxa": "cruetraxa",
    "shuzhen": "shu_zhen",
    "telenna": "talenna",
    "talenna": "talenna",
    "thelena": "talenna",
}

# Known filename spelling differences already present in the user's bilder.
_BUILTIN_TEMPLATE_ALIASES = {
    "gliseah": ("gliseah", "glicea"),
    "galathir": ("galathir", "galathier"),
    "embrys": ("embrys", "embris"),
    "yumeko": ("yumeko", "yummeko"),
    "siphi": ("siphi", "siphie"),
    "cruetraxa": ("cruetraxa", "cruetaxa"),
    "shu_zhen": ("shu_zhen", "shuzhen", "shu-zhen"),
    "talenna": ("telena", "telenna", "talenna", "thelena"),
}

# ---- Unified alias -> canonical map ---------------------------------------
# Build a single mapping so all code paths produce the same canonical keys.
_ALIAS_TO_CANONICAL: Dict[str, str] = {}

# Populate from explicit canonical corrections (user typos -> canonical).
for alias, canonical in _CANONICAL_NAME_ALIASES.items():
    a = str(alias).strip().lower()
    c = str(canonical).strip().lower()
    _ALIAS_TO_CANONICAL[a] = c
    _ALIAS_TO_CANONICAL[c] = c

# Incorporate builtin template variants: map every variant to the canonical key.
for canonical, variants in _BUILTIN_TEMPLATE_ALIASES.items():
    c = str(canonical).strip().lower()
    _ALIAS_TO_CANONICAL[c] = c
    for v in variants:
        _ALIAS_TO_CANONICAL[str(v).strip().lower()] = c
# ---------------------------------------------------------------------------


def normalize_champion(value: object) -> str:
    """Return a stable lower-case canonical champion key without UI prefixes.

    This uses a unified alias map (_ALIAS_TO_CANONICAL) to ensure the same
    canonical name is produced for template variants and common typos.
    """
    text = str(value or "").strip().lower()
    text = Path(text).stem

    # strip known UI prefixes
    for prefix in _NAME_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break

    # remove form suffixes and non-alnum -> underscore
    text = re.sub(r"_f[12]$", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")

    if not text:
        return ""

    # map known aliases -> canonical
    return _ALIAS_TO_CANONICAL.get(text, text)


def pick_template_name(champion: object) -> str:
    return f"arena_live_{normalize_champion(champion)}"


def ban_template_name(champion: object) -> str:
    return f"arena_live_ban_{normalize_champion(champion)}"


def enemy_template_names(champion: object, explicit: Optional[str] = None) -> Tuple[str, ...]:
    """Ordered possible opponent template stems for one champion."""
    key = normalize_champion(champion)
    variants: List[str] = []
    if explicit:
        stem = Path(str(explicit)).stem
        variants.append(stem)
    aliases = _BUILTIN_TEMPLATE_ALIASES.get(key, (key,))
    for alias in aliases:
        variants.append(f"arena_live_enemy_{alias}")
        variants.append(f"arena_live_opponent_{alias}")
        variants.append(f"arena_live_ban_{alias}")
    return tuple(dict.fromkeys(x for x in variants if x))


def _unique(seq: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for item in seq:
        key = normalize_champion(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _normalise_rule(raw: Mapping[str, object]) -> dict:
    return {
        "if_enemy_any": _unique(raw.get("if_enemy_any", []) or []),
        "if_enemy_all": _unique(raw.get("if_enemy_all", []) or []),
        "priority": _unique(raw.get("priority", []) or []),
    }


def _rule_matches(rule: Mapping[str, object], enemy_set: Set[str]) -> bool:
    any_list = list(rule.get("if_enemy_any", []) or [])
    all_list = list(rule.get("if_enemy_all", []) or [])
    if any_list and not any(name in enemy_set for name in any_list):
        return False
    if all_list and not all(name in enemy_set for name in all_list):
        return False
    return bool(any_list or all_list)


def _autonomy_controller():
    try:
        from livearena_autonomy import get_autonomy_controller
        controller = get_autonomy_controller()
        if not getattr(controller, "enabled", False):
            return None
        try:
            import livearena_config as cfg
            if not bool(getattr(cfg, "AUTONOMY_DRAFT_ENABLED", True)):
                return None
        except Exception:
            pass
        return controller
    except Exception:
        return None


def _available_enemy_template_names() -> List[str]:
    """Return canonical champion names for opponent portraits that exist on disk.

    V16 originally asked the knowledge base for only its top-threat names.  That
    made the "AI" blind to perfectly valid enemy templates lower in that list.
    V16.1 discovers the actual asset bank first; knowledge ranking only decides
    scan order, never visibility.
    """
    root = Path("./bilder")
    if not root.is_dir():
        return []

    names: List[str] = []
    prefixes = ("arena_live_enemy_", "arena_live_opponent_")
    ignored = {"left", "picking"}
    for item in root.iterdir():
        if not item.is_file() or item.suffix.lower() != ".png":
            continue
        lower = item.stem.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                raw = lower[len(prefix):]
                key = normalize_champion(raw)
                if key and key not in ignored:
                    names.append(key)
                break
    return _unique(names)


def _autonomy_scan_names() -> List[str]:
    controller = _autonomy_controller()
    if controller is None:
        return []
    limit = 64
    try:
        import livearena_config as cfg
        limit = int(getattr(cfg, "AUTONOMY_OPPONENT_SCAN_TOP_K", limit))
    except Exception:
        pass

    available = _available_enemy_template_names()
    available_set = set(available)

    # Keep high-threat knowledge entries early for the rotating PICK scan, then
    # append every other portrait that actually exists. BAN/LEADER can force a
    # complete pass, so no enemy card is excluded merely because its threat prior
    # is missing from the knowledge JSON.
    ranked = [
        normalize_champion(x)
        for x in controller.knowledge.draft_scan_names(max(limit * 2, len(available) * 2))
        if normalize_champion(x) in available_set
    ]
    ordered = _unique(ranked + available)
    return ordered[:max(1, limit)]


@dataclass
class DraftProfile:
    name: str
    pick_priority: List[str]
    ban_priority: List[str]
    leader_priority: List[str]
    counter_pick: Dict[str, List[str]] = field(default_factory=dict)
    counter_pick_rules: List[dict] = field(default_factory=list)
    ban_rules: List[dict] = field(default_factory=list)
    opponent_templates: Dict[str, str] = field(default_factory=dict)
    pick_templates: Dict[str, str] = field(default_factory=dict)
    ban_templates: Dict[str, str] = field(default_factory=dict)
    source_path: Optional[str] = None
    _autonomy_last_own_picks: List[str] = field(default_factory=list, repr=False)

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        name: str,
        fallback_pick: Sequence[str] = (),
        fallback_ban: Sequence[str] = (),
        fallback_leader: Sequence[str] = (),
        source_path: Optional[str] = None,
    ) -> "DraftProfile":
        pick = _unique(data.get("pick_priority", fallback_pick) or fallback_pick)
        ban = _unique(data.get("ban_priority", fallback_ban) or fallback_ban)
        leader = _unique(data.get("leader_priority", fallback_leader) or fallback_leader)

        cp: Dict[str, List[str]] = {}
        for enemy, order in (data.get("counter_pick", {}) or {}).items():
            enemy_key = normalize_champion(enemy)
            if enemy_key:
                cp[enemy_key] = _unique(order or [])

        cp_rules = [
            _normalise_rule(rule)
            for rule in (data.get("counter_pick_rules", []) or [])
            if isinstance(rule, Mapping)
        ]
        ban_rules = [
            _normalise_rule(rule)
            for rule in (data.get("ban_rules", []) or [])
            if isinstance(rule, Mapping)
        ]

        def norm_map(value: object) -> Dict[str, str]:
            result: Dict[str, str] = {}
            if not isinstance(value, Mapping):
                return result
            for key, path in value.items():
                nk = normalize_champion(key)
                if nk and path:
                    result[nk] = str(path)
            return result

        return cls(
            name=name,
            pick_priority=pick,
            ban_priority=ban,
            leader_priority=leader,
            counter_pick=cp,
            counter_pick_rules=cp_rules,
            ban_rules=ban_rules,
            opponent_templates=norm_map(data.get("opponent_templates", {})),
            pick_templates=norm_map(data.get("pick_templates", {})),
            ban_templates=norm_map(data.get("ban_templates", {})),
            source_path=source_path,
        )

    def counter_order(self, enemy_champions: Iterable[str]) -> List[str]:
        """Return only counter-pick candidates activated by the current enemy team."""
        enemy_set = {normalize_champion(x) for x in enemy_champions if normalize_champion(x)}
        order: List[str] = []

        for enemy_name, priority in self.counter_pick.items():
            if enemy_name in enemy_set:
                order.extend(priority)

        for rule in self.counter_pick_rules:
            if _rule_matches(rule, enemy_set):
                order.extend(rule.get("priority", ()))

        return _unique(order)

    def pick_order(self, enemy_champions: Iterable[str], own_picks: Iterable[str]) -> List[str]:
        """Return pick candidates.  V16 can dynamically rank them by utility.

        Legacy hard-coded order remains available when autonomy is disabled.
        Hard template availability is still checked by arenalive.py after this
        method returns; this function only ranks names.
        """
        own_list = _unique(own_picks)
        own_set = set(own_list)
        self._autonomy_last_own_picks = list(own_list)

        counter = self.counter_order(enemy_champions)
        order: List[str] = []
        order.extend(counter)
        order.extend(self.pick_priority)
        order = [x for x in _unique(order) if x not in own_set]

        controller = _autonomy_controller()
        if controller is not None:
            ranked = controller.rank_pick_candidates(
                order, enemy_champions, own_list, manual_priority=counter
            )
            if ranked:
                return ranked

        # Legacy V15 rule preserved only for non-autonomous mode.
        tekteon_key = normalize_champion("tekteon")
        if len(own_list) == 4 and tekteon_key and tekteon_key not in own_set:
            order = [o for o in order if normalize_champion(o) != tekteon_key]
            order.insert(0, tekteon_key)

        return order

    def ban_order(self, enemy_champions: Iterable[str]) -> List[str]:
        enemy_set = {normalize_champion(x) for x in enemy_champions if normalize_champion(x)}
        rule_priority: List[str] = []
        for rule in self.ban_rules:
            if _rule_matches(rule, enemy_set):
                rule_priority.extend(rule.get("priority", ()))
        order: List[str] = list(rule_priority)
        order.extend(self.ban_priority)

        # In autonomy mode every recognised enemy is a legal ban candidate, not
        # just champions pre-listed in ban_priority.  Explicit ban rules still
        # contribute candidates and are reflected in knowledge/threat scoring.
        controller = _autonomy_controller()
        if controller is not None:
            order.extend(sorted(enemy_set))
            ranked = controller.rank_ban_candidates(
                _unique(order),
                enemy_set,
                self._autonomy_last_own_picks,
                manual_priority=rule_priority,
            )
            if ranked:
                return ranked
        return _unique(order)

    def leader_order(self, own_picks: Iterable[str]) -> List[str]:
        own_order = _unique(own_picks)
        own_set = set(own_order)
        configured = [x for x in self.leader_priority if not own_set or x in own_set]
        order = _unique(configured + own_order)
        controller = _autonomy_controller()
        if controller is not None:
            ranked = controller.rank_leaders(order, own_order)
            if ranked:
                return ranked
        return order

    def opponent_names_needed(self) -> List[str]:
        names: List[str] = list(self.counter_pick.keys())
        for rule in self.counter_pick_rules + self.ban_rules:
            names.extend(rule.get("if_enemy_any", ()))
            names.extend(rule.get("if_enemy_all", ()))
        names.extend(self.opponent_templates.keys())
        # V16 autonomy needs more than counter-rule names.  Add a bounded set of
        # high-value opponents from the knowledge base; missing templates are
        # already handled safely by arenalive.py and logged once.
        names.extend(_autonomy_scan_names())
        return _unique(names)

    def pick_template_stem(self, champion: object) -> str:
        key = normalize_champion(champion)
        explicit = self.pick_templates.get(key)
        return Path(explicit).stem if explicit else pick_template_name(key)

    def ban_template_stems(self, champion: object) -> Tuple[str, ...]:
        key = normalize_champion(champion)
        explicit = self.ban_templates.get(key)
        candidates = []
        if explicit:
            candidates.append(Path(explicit).stem)
        candidates.append(ban_template_name(key))
        candidates.extend(enemy_template_names(key, self.opponent_templates.get(key)))
        return tuple(dict.fromkeys(candidates))

    def enemy_template_stems(self, champion: object) -> Tuple[str, ...]:
        key = normalize_champion(champion)
        return enemy_template_names(key, self.opponent_templates.get(key))

    def preload_template_stems(self) -> List[str]:
        names: List[str] = []
        for champ in self.pick_priority:
            names.append(self.pick_template_stem(champ))
        for champ in self.ban_priority:
            names.extend(self.ban_template_stems(champ))
        for champ in self.opponent_names_needed():
            names.extend(self.enemy_template_stems(champ))
        return list(dict.fromkeys(names))


def _legacy_to_keys(values: Sequence[str]) -> List[str]:
    return _unique(values)


def _resolve_profile_path(profile_name: str, profiles_dir: str):
    """Resolve a profile robustly without silently changing draft strategy.

    Resolution order:
      1. exact filename stem,
      2. case-insensitive exact stem,
      3. one unique close match (common typo, e.g. symbiontS -> symbiont).

    Returns:
        (resolved_name, path, notice)
    """
    requested = str(profile_name or "default").strip()
    safe_requested = re.sub(r"[^A-Za-z0-9_.-]+", "_", requested)
    directory = Path(profiles_dir)

    exact = directory / f"{safe_requested}.json"
    if exact.exists():
        return exact.stem, exact, None

    available = [p for p in directory.glob("*.json") if p.is_file()]
    by_lower = {p.stem.lower(): p for p in available}

    lower = safe_requested.lower()
    if lower in by_lower:
        path = by_lower[lower]
        notice = None
        if path.stem != safe_requested:
            notice = (
                f"PROFILE NAME: '{safe_requested}' -> '{path.stem}' "
                f"(case-insensitive match)"
            )
        return path.stem, path, notice

    names = sorted(by_lower.keys())
    close = difflib.get_close_matches(
        lower,
        names,
        n=2,
        cutoff=0.80,
    )

    if close:
        best = close[0]
        second = close[1] if len(close) > 1 else None
        best_ratio = difflib.SequenceMatcher(None, lower, best).ratio()
        second_ratio = (
            difflib.SequenceMatcher(None, lower, second).ratio()
            if second is not None
            else 0.0
        )

        if best_ratio >= 0.80 and (second is None or best_ratio - second_ratio >= 0.08):
            path = by_lower[best]
            notice = (
                f"PROFILE AUTOCORRECT: '{safe_requested}' -> '{path.stem}' "
                f"(similarity={best_ratio:.2f})"
            )
            return path.stem, path, notice

    return safe_requested or "default", exact, None


def load_profile(
    profile_name: str,
    *,
    profiles_dir: str,
    fallback_pick: Sequence[str],
    fallback_ban: Sequence[str],
    fallback_leader: Sequence[str],
) -> DraftProfile:
    """Load one JSON profile with safe typo correction.

    If no profile can be resolved, the object still carries load_error so the
    caller can fail closed instead of silently drafting with the wrong strategy.
    """
    requested = (profile_name or "default").strip()
    safe_name, path, resolve_notice = _resolve_profile_path(
        requested,
        profiles_dir,
    )

    fallback_kwargs = dict(
        name=safe_name or "default",
        fallback_pick=_legacy_to_keys(fallback_pick),
        fallback_ban=_legacy_to_keys(fallback_ban),
        fallback_leader=_legacy_to_keys(fallback_leader),
    )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError("profile root must be an object")
        profile = DraftProfile.from_mapping(
            data,
            source_path=str(path),
            **fallback_kwargs,
        )
        if resolve_notice:
            profile.load_notice = resolve_notice
        profile.requested_name = requested
        profile.profile_valid = True
        return profile
    except Exception as exc:
        profile = DraftProfile.from_mapping({}, source_path=None, **fallback_kwargs)
        profile.name = safe_name or "default"
        profile.load_error = f"{type(exc).__name__}: {exc}"
        profile.requested_name = requested
        profile.profile_valid = False
        return profile


def profile_name_from_argv(
    argv: Sequence[str],
    *,
    default_name: str = "default",
    env_name: str = "LIVEARENA_DRAFT_PROFILE",
) -> str:
    """CLI --draft-profile wins over env, then config default."""
    args = list(argv or ())
    if "--draft-profile" in args:
        idx = args.index("--draft-profile")
        if idx + 1 < len(args) and not str(args[idx + 1]).startswith("--"):
            return str(args[idx + 1])
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    return default_name
