"""Editable skill priority rules for Live Arena combat.

Only order belongs here. Perception and target logic stay elsewhere.
"""
from __future__ import annotations

DEFAULT_SKILL_PRIORITY = ("A3", "A2", "A1")

# Champion-specific overrides. Keys must match the family name recognised from
# skill templates, e.g. skill_predator_a1.PNG -> "predator".
CHAMPION_SKILL_PRIORITIES = {
    # Requested example: Predator prefers A2, then A3, then A1.
    "predator": ("A2", "A3", "A1"),
}


def priority_for(family):
    if not family:
        return DEFAULT_SKILL_PRIORITY
    return tuple(CHAMPION_SKILL_PRIORITIES.get(
        str(family).lower(),
        DEFAULT_SKILL_PRIORITY,
    ))
