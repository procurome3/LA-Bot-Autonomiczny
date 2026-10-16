"""Helpers for conservative combat perception gating.

These utilities keep the bot in a wait state whenever a match is visually weak
or the margin between the top and second choice is too small.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PerceptionState:
    accepted: bool
    confidence: float
    margin: float
    threshold: float
    reason: str = "ok"

    @property
    def unknown(self) -> bool:
        return not self.accepted


def select_with_confidence(score, second_score=None, threshold=0.55):
    """Return a conservative acceptance decision for a visual match.

    The score is treated as uncertain when it sits under the minimum threshold
    or when the top match is not meaningfully ahead of the runner-up.
    """
    score = max(0.0, min(1.0, float(score or 0.0)))
    second = 0.0
    if second_score is not None:
        second = max(0.0, min(1.0, float(second_score)))
    margin = score - second
    threshold = float(threshold)

    if score < threshold:
        return PerceptionState(False, score, margin, threshold, "score-below-threshold")
    if second_score is not None and margin < 0.05:
        return PerceptionState(False, score, margin, threshold, "weak-margin")
    return PerceptionState(True, score, margin, threshold, "ok")


def confidence_from_margin(score, second_score=None, threshold=0.55):
    state = select_with_confidence(score, second_score, threshold=threshold)
    return state.confidence, state.margin, state.accepted, state.reason
