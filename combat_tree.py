"""Strict skill-priority decision layer for Live Arena combat V15.

Perception and champion-specific conditions are computed in livearena_combat.py.
This module deliberately has no third-party dependency: it preserves the old
selector semantics in a few deterministic Python branches.

Rule: a lower-priority skill is considered only when every higher branch is
CONFIRMED unavailable or ineligible. Unknown/uncertain state waits; after the
caller-confirmed timeout only a fully verified action may be used as controlled fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from livearena_config import SKILL_PRIORITY_BY_FAMILY

DEFAULT_SKILL_PRIORITY = ("A3", "A2", "A1")


@dataclass
class SkillTreeResult:
    skill: Optional[dict]
    state: str          # selected | wait | none
    reason: str
    priority: Tuple[str, ...]
    unknown_reasons: Tuple[str, ...] = ()


class CombatDecisionTree:
    def __init__(self, champion_priorities: Optional[Mapping[str, Sequence[str]]] = None):
        self.priorities = {
            str(family).lower(): tuple(order)
            for family, order in SKILL_PRIORITY_BY_FAMILY.items()
        }
        if champion_priorities:
            for family, order in champion_priorities.items():
                self.priorities[str(family).lower()] = tuple(order)

    def priority_for(self, family: Optional[str]) -> Tuple[str, ...]:
        if not family:
            return DEFAULT_SKILL_PRIORITY
        return tuple(self.priorities.get(str(family).lower(), DEFAULT_SKILL_PRIORITY))

    @staticmethod
    def _ready(item: Optional[dict], min_score: float) -> bool:
        if item is None:
            return False
        if item.get("eligibility", "eligible") != "eligible":
            return False
        if item.get("availability", "unknown") != "available":
            return False
        return float(item.get("score", 0.0)) >= float(min_score)

    def decide(
        self,
        *,
        family: Optional[str],
        skills: Mapping[str, dict],
        declared_skill_ids: Iterable[str],
        dead_ally_available: bool,
        min_score: float,
        prefer_fallback: bool = False,
        priority_override: Optional[Sequence[str]] = None,
    ) -> SkillTreeResult:
        """Strict priority with diagnosable uncertainty and controlled fallback.

        Unknown on a higher-priority skill still blocks lower skills during normal
        operation.  We collect the uncertainty reasons instead of returning on
        the first one.  After the caller's timeout, ``prefer_fallback=True`` may
        select the best fully confirmed action in the supplied priority order.
        """
        priority = tuple(priority_override) if priority_override else self.priority_for(family)
        declared = set(declared_skill_ids)
        unknown_reasons = []

        for skill_id in priority:
            if skill_id not in declared:
                continue

            item = skills.get(skill_id)
            if item is None:
                unknown_reasons.append(f"{skill_id}-not-recognised")
                continue

            eligibility = item.get("eligibility", "eligible")
            if eligibility == "ineligible":
                continue
            if eligibility != "eligible":
                unknown_reasons.append(
                    item.get("eligibility_reason")
                    or f"{skill_id}-eligibility-unknown"
                )
                continue

            # Revive is not uncertain merely because there is no corpse: the branch
            # is simply ineligible for this frame and the next priority may run.
            if item.get("attack_type") == "ally_dead" and not dead_ally_available:
                continue

            availability = item.get("availability", "unknown")
            if availability == "unavailable":
                continue
            if availability != "available":
                unknown_reasons.append(f"{skill_id}-availability-unknown")
                continue

            if float(item.get("score", 0.0)) < float(min_score):
                unknown_reasons.append(f"{skill_id}-match-uncertain")
                continue

            # A ready lower skill cannot overtake unresolved higher-priority state.
            if unknown_reasons:
                continue

            return SkillTreeResult(
                item,
                "selected",
                item.get("eligibility_reason") or f"priority-{skill_id}-ready",
                priority,
                (),
            )

        if unknown_reasons:
            if prefer_fallback:
                # V16.1 autonomous fallback: after the caller-confirmed wait
                # timeout, select the best FULLY VERIFIED action from the current
                # (possibly utility-ranked) priority order.  This remains safe:
                # unknown/unavailable/ineligible skills are never guessed, and
                # revive still requires a confirmed corpse.
                for fallback_id in priority:
                    if fallback_id not in declared:
                        continue
                    candidate = skills.get(fallback_id)
                    if not self._ready(candidate, min_score):
                        continue
                    if (
                        candidate.get("attack_type") == "ally_dead"
                        and not dead_ally_available
                    ):
                        continue
                    fallback = dict(candidate)
                    fallback["fallback"] = True
                    return SkillTreeResult(
                        fallback,
                        "selected",
                        f"controlled-dynamic-fallback-{fallback_id}-after-{unknown_reasons[0]}",
                        priority,
                        tuple(unknown_reasons),
                    )

            return SkillTreeResult(
                None,
                "wait",
                unknown_reasons[0],
                priority,
                tuple(unknown_reasons),
            )

        return SkillTreeResult(
            None,
            "none",
            "all-priority-skills-unavailable-or-ineligible",
            priority,
            (),
        )
