"""Live Arena Combat V15.26: stable actor binding + evidence fusion + bounded fallback + verified targeting.

Drop-in module for the V11.6 configuration. Recognition thresholds are conservative
starting values, not calibrated accuracy claims. No cross-champion A1 fallback.
No hard DeadTime/deadline counter: freshness is validated from the current frame/turn.
 """

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import hashlib
import base64
import ctypes
from ctypes import wintypes
import math
import os
import random
import re
import sys
import time

import cv2
import numpy as np

from combat_tree import CombatDecisionTree
from livearena_perception import select_with_confidence


# Console colours (24-bit ANSI / TrueColor).
# These helpers affect log rendering only; no extra screenshot/template analysis is added.
COLOR_TURN_PLAYER = (0, 255, 255)     # #00FFFF
COLOR_TURN_OPPONENT = (160, 32, 58)   # #A0203A
COLOR_SKILL_CLICK = (50, 205, 50)      # #32CD32
_ANSI_RESET = "\x1b[0m"
_vt_console_initialized = False


PERCEPTION_THRESHOLD = 0.55
PERCEPTION_MARGIN_MIN = 0.05
PERCEPTION_WAIT_REASON = "perception-weak-unknown"


def _perception_gate(score, second_score=None, *, threshold=PERCEPTION_THRESHOLD, min_margin=PERCEPTION_MARGIN_MIN):
    state = select_with_confidence(score, second_score, threshold=threshold)
    if not state.accepted:
        return {
            "accepted": False,
            "confidence": float(state.confidence),
            "margin": float(state.margin),
            "reason": state.reason,
            "wait_reason": PERCEPTION_WAIT_REASON,
        }
    return {
        "accepted": True,
        "confidence": float(state.confidence),
        "margin": float(state.margin),
        "reason": state.reason,
        "wait_reason": None,
    }


# NOTE: the full file continues below; only the import + gate helpers were patched.
