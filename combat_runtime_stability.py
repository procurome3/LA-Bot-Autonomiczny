"""Targeted confirmation and fallback support for combat runtime.

This module is intentionally lightweight and can be used by the main combat loop
without requiring a heavy rewrite. It centralizes the runtime safety checks that
prevent deadlocks from unknown states and unconfirmed target mode.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from livearena_config import (
    DECISION_ALLOW_FALLBACK,
    DECISION_UNKNOWN_TIMEOUT,
    TARGET_CONFIRM_RETRY_COUNT,
    TARGET_CONFIRM_WAIT_SECONDS,
    REVIVE_CONFIRM_FRAMES,
)


@dataclass
class TargetConfirmationState:
    attempts: int = 0
    confirmed: bool = False
    last_checked_at: float = 0.0
    selected_frame: Optional[object] = None
    target_kind: Optional[str] = None


@dataclass
class DecisionSnapshot:
    timestamp: float
    family: Optional[str]
    skill_id: Optional[str]
    reason: str
    wait_reasons: List[str] = field(default_factory=list)
    fallback_used: bool = False
    target_confirmed: bool = False
    revive_confirmed: bool = False


class CombatRuntimeStability:
    def __init__(self, analyzer=None):
        self.analyzer = analyzer
        self._history: List[DecisionSnapshot] = []
        self._target_states: Dict[str, TargetConfirmationState] = {}
        self._wait_started_at: Optional[float] = None

    def record_decision(self, *, family, skill_id, reason, wait_reasons=None,
                       fallback_used=False, target_confirmed=False,
                       revive_confirmed=False):
        snapshot = DecisionSnapshot(
            timestamp=time.monotonic(),
            family=family,
            skill_id=skill_id,
            reason=reason,
            wait_reasons=list(wait_reasons or ()),
            fallback_used=fallback_used,
            target_confirmed=target_confirmed,
            revive_confirmed=revive_confirmed,
        )
        self._history.append(snapshot)
        if len(self._history) > 500:
            self._history = self._history[-500:]

    def start_wait_timer(self):
        if self._wait_started_at is None:
            self._wait_started_at = time.monotonic()

    def clear_wait_timer(self):
        self._wait_started_at = None

    def wait_expired(self) -> bool:
        if self._wait_started_at is None:
            return False
        return (time.monotonic() - self._wait_started_at) >= DECISION_UNKNOWN_TIMEOUT

    def should_force_fallback(self) -> bool:
        return DECISION_ALLOW_FALLBACK and self.wait_expired()

    def prepare_target_state(self, key: str, *, target_kind: Optional[str] = None):
        st = self._target_states.get(key)
        if st is None:
            st = TargetConfirmationState(target_kind=target_kind)
            self._target_states[key] = st
        st.target_kind = target_kind or st.target_kind
        return st

    def increment_target_attempt(self, key: str):
        st = self._target_states.setdefault(key, TargetConfirmationState())
        st.attempts += 1
        st.last_checked_at = time.monotonic()

    def target_retry_allowed(self, key: str) -> bool:
        st = self._target_states.get(key)
        if st is None:
            return True
        return st.attempts < TARGET_CONFIRM_RETRY_COUNT

    def target_confirmed(self, key: str, *, selected_frame=None) -> bool:
        st = self._target_states.get(key)
        if st is None:
            return False
        st.confirmed = True
        st.selected_frame = selected_frame
        st.last_checked_at = time.monotonic()
        return True

    def check_target_confirmation(self, frame, rect, skill, reason: str):
        if self.analyzer is None:
            return False
        key = f"{skill.get('skill_name', 'unknown')}::{reason}"
        st = self.prepare_target_state(key, target_kind=skill.get('attack_type'))
        if st.confirmed:
            return True
        if st.attempts >= TARGET_CONFIRM_RETRY_COUNT:
            return False
        if hasattr(self.analyzer, 'selected_skill') and self.analyzer.selected_skill(frame, rect, skill):
            st.confirmed = True
            st.selected_frame = frame
            return True
        time.sleep(TARGET_CONFIRM_WAIT_SECONDS)
        self.increment_target_attempt(key)
        return False

    def revive_confirmation_ok(self, *, dead_ally_available: bool, hp_sample=None):
        if not dead_ally_available:
            return False
        if hp_sample is not None and hp_sample <= 0.0:
            return True
        return False

    @property
    def history(self):
        return list(self._history)


__all__ = [
    "CombatRuntimeStability",
    "DecisionSnapshot",
    "TargetConfirmationState",
]
