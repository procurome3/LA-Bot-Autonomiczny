from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def confidence_from_margin(best_score: float, second_score: Optional[float] = None, *, min_gap: float = 0.05) -> float:
    """Map a score margin into a conservative confidence value.

    The logic intentionally stays conservative: a single good match is not enough
    evidence by itself, and a very small margin between the best and second result
    still yields low confidence.  This is a general utility for perception layers
    that should distinguish "strong evidence" from "uncertain but plausible".
    """
    best = clamp01(best_score)
    if second_score is None:
        return best

    second = clamp01(second_score)
    margin = max(0.0, best - second)
    # Normalise margin into 0..1 over a small but useful operating window.
    normalised = margin / max(min_gap, 0.20)
    return clamp01(0.55 * best + 0.45 * clamp01(normalised))


@dataclass
class Observation:
    value: Any
    score: float
    confidence: float
    source: str
    age_ms: float = 0.0
    unknown: bool = False


@dataclass
class PerceptionState:
    turn_owner: Optional[str] = None
    active_slot: Optional[int] = None
    enemy_states: List[Dict[str, Any]] = field(default_factory=list)
    ally_states: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    skill_states: Dict[str, Any] = field(default_factory=dict)
    selected_family: Optional[str] = None
    confidence: float = 0.0
    notes: List[str] = field(default_factory=list)

    @staticmethod
    def merge(previous: Optional["PerceptionState"], current: "PerceptionState") -> "PerceptionState":
        """Temporal merge for frame-to-frame perception.

        If a value is genuinely unstable or the current frame is weak, keep the prior
        value instead of flipping.  This is intentionally conservative: it reduces
        noisy toggles and helps the combat engine wait for a stable signal instead of
        acting on a single noisey frame.
        """
        if previous is None:
            return current

        merged = PerceptionState(
            turn_owner=current.turn_owner,
            active_slot=current.active_slot,
            enemy_states=current.enemy_states,
            ally_states=current.ally_states,
            skill_states=current.skill_states,
            selected_family=current.selected_family,
            confidence=current.confidence,
            notes=list(current.notes),
        )

        if current.turn_owner is None and previous.turn_owner is not None:
            merged.turn_owner = previous.turn_owner
            merged.confidence = min(merged.confidence, previous.confidence)

        if current.active_slot is None and previous.active_slot is not None:
            merged.active_slot = previous.active_slot
            merged.notes.append("active-slot-stable-fallback")

        # If the new frame is weak overall, prefer the previous stronger belief.
        if current.confidence < 0.45 and previous.confidence >= 0.45:
            merged.confidence = previous.confidence
            merged.selected_family = merged.selected_family or previous.selected_family
            if current.active_slot is None:
                merged.active_slot = previous.active_slot

        return merged


def make_observation(value: Any, score: float, *, source: str, confidence: Optional[float] = None, age_ms: float = 0.0) -> Observation:
    obs_confidence = clamp01(float(confidence if confidence is not None else score))
    return Observation(
        value=value,
        score=clamp01(float(score)),
        confidence=obs_confidence,
        source=source,
        age_ms=float(age_ms),
        unknown=obs_confidence < 0.45,
    )


def select_with_confidence(best_score: float, second_score: Optional[float], *, threshold: float = 0.55) -> Tuple[bool, float]:
    confidence = confidence_from_margin(best_score, second_score, min_gap=0.06)
    return confidence >= threshold, confidence
