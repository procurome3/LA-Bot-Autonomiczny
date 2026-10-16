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


# Console colours (24-bit ANSI / TrueColor).
# These helpers affect log rendering only; no extra screenshot/template analysis is added.
COLOR_TURN_PLAYER = (0, 255, 255)     # #00FFFF
COLOR_TURN_OPPONENT = (160, 32, 58)   # #A0203A
COLOR_SKILL_CLICK = (50, 205, 50)      # #32CD32
_ANSI_RESET = "\x1b[0m"
_vt_console_initialized = False


def _init_virtual_terminal_once():
    """Enable ANSI escape sequences in the Windows console when available."""
    global _vt_console_initialized
    if _vt_console_initialized:
        return
    _vt_console_initialized = True

    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.windll.kernel32
        stdout_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                stdout_handle,
                mode.value | 0x0004,  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
    except Exception:
        # Modern Windows Terminal/PowerShell usually needs no manual setup.
        pass


def _console_rgb(text, rgb):
    """Return coloured text in a real terminal; keep files/pipes free of ANSI codes."""
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return text
    _init_virtual_terminal_once()
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m{text}{_ANSI_RESET}"


from livearena_config import (
    SKILL_PLAN,
    GLOBAL_SKILL_PLAN,
    ALLY_SLOT_POINTS,
    ALLY_HP_REGIONS,
    ALLY_ACTIVE_RING_REGIONS,
    REFERENCE_SIZE,
    ROI_SKILL_BAR,
    STATE_COMBAT,
    PERF_LOG_INTERVAL_SECONDS,
    COMBAT_ACTION_LOCK_SECONDS,
    COMBAT_NO_SKILL_LOG_SECONDS,
    COMBAT_NO_PROGRESS_DIAG_SECONDS,
    ENEMY_HP_ALIVE_THRESHOLD,
    ALLY_HP_ALIVE_THRESHOLD,
    ALLY_HP_DEAD_THRESHOLD,
    ALLY_ALIVE_CONFIRM_FRAMES,
    ALLY_DEAD_CONFIRM_FRAMES,
    SKILL_SLOT_SCORE_MIN,
    SKILL_SLOT_SCORE_STRONG,
    SKILL_FAMILY_BIND_SCORE,
    SKILL_FAMILY_MEMORY_MIN,
    COMBAT_A1_EXACT_SCAN_LIMIT,
    COMBAT_A1_PREFILTER_TOP_K,
    COMBAT_A1_PREFILTER_MAX_EXACT,
    COMBAT_A1_PREFILTER_DOWNSCALE,
    COMBAT_A1_PREFILTER_RESCUE_SCORE,
    COMBAT_A1_PREFILTER_RESCUE_MARGIN,
    SKILL_RULES_BY_FAMILY,
    TARGET_POLICY_BY_FAMILY_SKILL,
    SPECIAL_TARGET_EFFECT_TEMPLATES,
    SPECIAL_TARGET_EFFECT_SCORE_MIN,
    SPECIAL_TARGET_EFFECT_SCALES,
    SKILL_SAFE_A1_FALLBACK_SECONDS,
    DECISION_UNKNOWN_TIMEOUT,
    DECISION_ALLOW_FALLBACK,
    SKILL_EVIDENCE_TEMPLATE_WEIGHT,
    SKILL_EVIDENCE_APPEARANCE_WEIGHT,
    SKILL_EVIDENCE_GEOMETRY_WEIGHT,
    SKILL_EVIDENCE_RESCUE_RAW_MIN,
    TARGET_RETRY_BACKOFF_FACTOR,
    TARGET_RETRY_BACKOFF_MAX,
    ACTIVE_RING_GREEN_RATIO_MIN,
    ACTIVE_RING_DOMINANCE,
    SKILL_PRIORITY_BY_FAMILY,
    GLOBAL_A4_BEFORE_A1,
    SKILL_AVAILABLE_VALUE_RATIO_MIN,
    SKILL_AVAILABLE_SAT_RATIO_MIN,
    TARGETING_DELAY_MIN,
    TARGETING_DELAY_MAX,
    TARGET_RETRY_DELAY,
    COMBAT_REQUIRE_YOUR_TURN,
    COMBAT_PLAYER_PORTRAIT_REGION,
    COMBAT_OPPONENT_PORTRAIT_REGION,
    COMBAT_PORTRAIT_GREEN_RATIO_MIN,
    COMBAT_PORTRAIT_GREEN_DOMINANCE,
    AUTONOMY_ENABLED,
    AUTONOMY_COMBAT_ENABLED,
    AUTONOMY_TARGET_ENABLED,
    AUTONOMY_LEARNING_ENABLED,
    AUTONOMY_SKILL_REORDER_MARGIN,
    ACTIVE_COMBAT_TEMPLATE_FILTER,
)

from livearena_autonomy import get_autonomy_controller


# Local combat settings: no draft/config changes required.
TURN_BUDGET_SECONDS = None
CLICK_RESERVE_SECONDS = 0.0
PRIORITY_WAIT_SECONDS = 0.0
A1_IDENTITY_MIN = 0.34
A1_IDENTITY_MARGIN = 0.025
SKILL_MATCH_MIN = 0.34
CONFIRM_FRAMES = 2

# V13.8 FAST CONFIRM:
# Keep the safety property of two independent observations, but make the second
# observation cheap. The first frame still runs the full decision tree. On the
# next frame we verify only:
#   - player still owns the turn,
#   - the expected actor's A1 is still a strong match,
#   - the already chosen skill is still available at its anchored button.
# Any ambiguity falls back to the old full analysis; no blind click is allowed.
FAST_CONFIRM_ENABLED = True
FAST_CONFIRM_A1_SCORE_MIN = 0.72
FAST_CONFIRM_MAX_A1_SCORE_DROP = 0.16
FAST_CONFIRM_A1_CENTER_TOLERANCE_REF = 18

# PAUSE SAFETY: any real pause invalidates a pre-pause click/decision frame.
# The game itself keeps running while the bot is paused, so on resume we always
# require fresh pixels before sending input.
PAUSE_STALE_AFTER_SECONDS = 0.02

# V15.20 turn detector:
# - an explicit OPPONENT portrait border is authoritative; the Your Turn label
#   may linger for a frame during transitions and must not override it,
# - a short player-edge settling window prevents decisions from being built on
#   the same animation frame that flips ownership.
YOUR_TURN_SCORE_MIN = 0.68
YOUR_TURN_ROI_REF = (280, 0, 740, 105)
PLAYER_TURN_SETTLE_SECONDS = 0.075
RETURN_CHECK_INTERVAL = 0.35
ACTOR_PROBE_INTERVAL = 0.12
ACTOR_A1_SCORE_MIN = 0.60
ACTOR_A1_MARGIN_MIN = 0.10
# Slot memory is an optimisation, never identity proof.  A remembered champion
# must still have a meaningful visual match before the decision tree may use it.
SLOT_MEMORY_VISUAL_SCORE_MIN = 0.42
SLOT_INFERENCE_VISUAL_SCORE_MIN = 0.46

# V15.11 — fixed-slot A1 rescue.
# Some Champion Skills source crops (Vestele/Tekteon in the 2026-10-01 replay)
# correlate too weakly in a full ROI search even though the actual A1 icon is
# clearly visible.  The rescue is used ONLY after the normal all-A1 matcher
# fails.  It compares the tiny expected A1 button crop against active-team A1
# templates, so it is cheap and does not add screenshots.
A1_FIXED_FALLBACK_SCORE_MIN = 0.55
A1_FIXED_FALLBACK_MARGIN_MIN = 0.08
# V15.13: a very strong fixed-button match can short-circuit the more expensive
# full skill-bar search. The old fallback thresholds remain unchanged for rescue.
A1_FIXED_FAST_SCORE_MIN = 0.60
A1_FIXED_FAST_MARGIN_MIN = 0.10

# V15.15 — mythical root rescue.
# Mythical form1/form2 A1 templates belong to the SAME champion root.  Treating
# the sibling form as a competing champion artificially shrinks the margin.
# The supplied full Komidus turn is stable around:
#   komidus_f1 ~= 0.53
#   komidus_f2 ~= 0.46
#   best DIFFERENT root ~= 0.45
# so the old 0.55 / 0.08 fallback never fired although Komidus was clearly the
# best root on every sampled frame.
A1_FIXED_MYTHICAL_ROOT_SCORE_MIN = 0.52
A1_FIXED_MYTHICAL_ROOT_MARGIN_MIN = 0.06

# V15.16 — physical multi-skill fingerprint rescue.
# Used only after the cheap A1 passes are ambiguous.  The supplied 20:39 replay
# gives Komidus f1 ~0.61 aggregate vs ~0.47 next form/competitor on the same
# five-button skill row, while the old single-A1 score sat just below 0.52.
MULTI_SKILL_FINGERPRINT_SCORE_MIN = 0.55
MULTI_SKILL_FINGERPRINT_ROOT_MARGIN_MIN = 0.08
MULTI_SKILL_FINGERPRINT_FORM_MARGIN_MIN = 0.05
MULTI_SKILL_FINGERPRINT_MIN_SKILLS = 2

# V15.23 — fixed-geometry multi-skill rescue.
# Tekteon can have an A1 correlation below the single-icon fallback threshold,
# especially while the skill bar is settling.  When the normal A1 path and the
# Hough-circle fingerprint both fail, compare the expected fixed A1/A2/A3
# button positions for the ACTIVE roster only.  Requiring coherent evidence
# from multiple skills keeps this safer than globally lowering A1 thresholds.
FIXED_MULTI_SKILL_SCORE_MIN = 0.50
FIXED_MULTI_SKILL_ROOT_MARGIN_MIN = 0.055
FIXED_MULTI_SKILL_A1_MIN = 0.46
FIXED_MULTI_SKILL_SECONDARY_MIN = 0.50
FIXED_MULTI_SKILL_MIN_SKILLS = 2

A1_PASSIVE_CENTER_X_REF = 956
A1_SKILL_ROW_Y_REF = 727
A1_FIXED_HALF_REF = 48

SUBMITTED_RETRY_SECONDS = 0.90
MAX_SUBMIT_ATTEMPTS_PER_ACTOR = 1

# V13.4: once A1 identifies the active champion, A2/A3 are NOT searched
# across the whole skill bar. Their physical centers are inferred from A1.
SKILL_BUTTON_GAP_REF = 120
SKILL_BUTTON_HALF_REF = 43
ANCHORED_SKILL_SCORE_MIN = 0.44

# V15.14:
# - Transform A4 is a physically anchored mythical button.  Its battle artwork
#   can correlate worse than ordinary A2/A3 source crops, so use both the
#   champion-specific and generic metamorph templates and a conservative lower
#   local threshold.
# - A continued/extra turn is re-armed only after the previous non-A1 skill is
#   visibly on cooldown AND the same champion root's A1 is visible again.
TRANSFORM_ANCHORED_SCORE_MIN = 0.30
CONTINUED_TURN_REARM_DELAY = 0.40

# Cooldown requires both a dark overlay and reduced brightness, or a very
# strong dark overlay. This avoids treating a bright ready Fabian A3 as cooldown.
COOLDOWN_OVERLAY_STRONG = 0.38
COOLDOWN_OVERLAY_WEAK = 0.18
COOLDOWN_VALUE_RATIO_MAX = 0.90

# V13.5 input timing.
# The supplied replay shows that clicking the target ~0.1-0.18 s after the
# skill button is sometimes too early. We now wait until RAID shows the cyan
# selected-skill rim before submitting a target.
SKILL_SELECT_CONFIRM_TIMEOUT = 0.80
TARGET_ACCEPT_TIMEOUT = 0.90
TARGET_ONLY_RETRY_DELAY = 0.10
TARGET_ONLY_MAX_ATTEMPTS = 2

# V14.0 — Sheep fallback.
# When a champion is Polymorphed, its normal A1 template disappears, so the
# standard family recognizer correctly returns family=None.  After 2 seconds of
# a confirmed PLAYER turn we use the Sheep debuff marker + exactly one physical
# skill button as an independent proof that the CURRENT actor is a Sheep.
# This path is champion-agnostic: Harima, Ankora, Mikage, etc. behave identically.
SHEEP_TEMPLATE = "./bilder/sheep.png"
TOTAL_GUARD_TEMPLATE = "./bilder/total_guard.png"
SHEEP_FALLBACK_DELAY_SECONDS = 2.0
SHEEP_MARKER_SCORE_MIN = 0.78
TOTAL_GUARD_SCORE_MIN = 0.78
SHEEP_MARKER_FIELD_REF = (0, 300, 1020, 650)
SHEEP_MARKER_SCALES = (0.90, 1.00, 1.10)
TOTAL_GUARD_SCALES = (0.85, 0.92, 1.00, 1.08, 1.15)
SHEEP_SKILL_CENTER_TOLERANCE_REF = 24

# V14.0 — generic revive targeting.
# A dead champion's clickable corpse can move below its standing-position point
# or overlap a living neighbour.  Retry nearby corpse-safe points without
# re-clicking the revive skill.  This applies to every attack_type="ally_dead".
REVIVE_TARGET_MAX_ATTEMPTS = 6
REVIVE_TARGET_RETRY_DELAY = 0.08
REVIVE_CORPSE_OFFSETS_REF = (
    (0, 0),
    (0, 72),
    (34, 58),
    (-34, 58),
)

# V13.6: every support/buff skill declared attack_type == "self" targets
# the CURRENT ACTOR. We never search another ally for these skills.
SELF_TARGET_ATTACK_TYPE = "self"

# V13.7: lightweight damage-immunity scan. These templates are native battle
# icon crops from bilder(7), so only a tiny +/-10% local scale search is needed.
# Matching runs ONLY inside each living enemy's existing buff ROI and reuses the
# same combat frame; it does not capture another screenshot.
# V14.2 target-safety templates.  Counterattack uses the same tiny local
# buff-ROI matcher as Block Damage / Unkillable, so there is no extra capture.
TARGET_AVOID_TEMPLATES = {
    "block_damage": "./bilder/block_damage.png",
    "unkillable": "./bilder/unkillable.png",
    "counterattack": "./bilder/counterattack.png",
}
TARGET_AVOID_SCORE_MIN = 0.80
TARGET_AVOID_SCALE_FACTORS = (0.90, 1.00, 1.10)

# A very short cache masks single animation frames where every HP bar is hidden.
# It is used only for target discovery; every click still gets a fresh re-check.
TARGET_STATE_CACHE_SECONDS = 0.45

# Tight UI regions around the enemy HP bars (1024x769 reference client).
# The old broad regions included champion bodies/floor/effects and generated
# false alive targets from red armour, arena art and debuff text.
ENEMY_HP_BAR_REGIONS_REF = {
    1: (285, 145, 410, 220),
    2: (445, 170, 595, 250),
    3: (610, 180, 770, 250),
    4: (780, 195, 930, 275),
}
ENEMY_HP_BAR_SCORE_MIN = 24.0

# Large green floor-ring detector for the currently acting ally.
ACTIVE_ACTOR_FIELD_REF = (20, 420, 980, 700)
ACTIVE_ACTOR_BODY_OFFSET_Y_REF = 38
ACTIVE_ACTOR_MOVE_CONFIRM_REF = 70

# Multi-skill identity: one very strong skill or two coherent skills of one family.
FAMILY_STRONG_SCORE = 0.58
FAMILY_EVIDENCE_SCORE = 0.34
FAMILY_MARGIN_MIN = 0.025
VEIL_SCORE_MIN = 0.82
# Source icons are 44 x 40; battle buff icons are typically much smaller.
VEIL_SCALES = (0.25, 0.275, 0.30, 0.325, 0.35, 0.375, 0.40, 0.425,
               0.45, 0.475, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75,
               0.80, 0.85, 0.90, 0.95, 1.00, 1.06, 1.12, 1.20)

# Original user-supplied PNG bytes, decoded once. No new bilder files needed.
_VEIL_ICON_PNG = {
    'veil': 'iVBORw0KGgoAAAANSUhEUgAAACwAAAAoCAYAAACFFRgXAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAk1SURBVFhHzZhpbFzVFcd/977Zx+PMeJnxPl5jO04cx8YL2YjTLARIoQ1EaWkJoQsFqZSlXyqRllIVqQjaKq1oS9sPRUItpLRAaFChlUpSQ7YGSBycPc5ivCZ2vIzHnnnv9cOMZ8uMM0n4wH/0l+aee969f7137z3nXOGs/oJuqlqHtHoAyecb00jpKEBanYk9n1sIV/MW3VzajpQisS8ldF2g61F/kwTCTSkE5QUOqvLnMO4P0Hl+mP7LU9GHNUCPNqXUoo2rQNdBuJq/oZtLVyKlhhAxI80CTZNxgi0KCAFtNXk8vmkhcywG7GYjqqZxqn+MnQcv8N7HvZwbHAc1XrCiqNHGVaBp8rMRvKTWzZObm8jJtJLrtGCO8Z1SNUb8QT45N8y2NzrZc7j/hgQr1sLGpwzOMoTQEWmuipDYkPOtzSU8/UAzZQWZ2C0GBGCI8RVSYDQpFGTbua25BJ9/imMXRgiqIdVSpveSCM+b1rGg6wJVVSKcebutVbls3bSQ8jw7ZgVMChgV0GIownarUeCyG/jx/S2sqM/HagCrIbL000ZaghOhSMHiGg/PPNBMeb4jsfuqeOGxW7i5Lg+Z7ieNwTULFgJaqnLZem8D87zXfxw+ck891V4n4hpFpyVYAFKE6Jlj4r7VFTRUZoc6rm0+hAixoSKHH21ppjA7Awgdk7EbORXSEiwFmBVwWg3ctbSUtgV5aJIIrwWKAKMM8abKHDavrkXXFDRNoqUx2NU9YrCgPIs7by7D47Qmdl03ttxWTUttbqI5JdIW7HFZWb/ES0NVdmLXDWPr5iZKcjMSzUmRUrCuiSgR1JVnsaaxKBJaRQw1HdQwg5rO5TF/hL7JQGSpC+KfEzooEuq9Lr60tASLMWHeJGs6ZaRTVSXyvzDHxhN3z+cryysjtlhMAUd7Rug8cYkj54bx+aK5g8moUOK2s6A8i/nlWWTbLHGRbibKHD0/zF0/fJvLE9EuIfS4XGPW0Dwj2KhI1jYV8uw3W3BlxAbdEI73XmZP1xBv7TvL6Z4xei7GzBjeZC67kWK3nbZaD/eurKIiPzPqEBY8HVDZ+qd9vPTOmUhXMsEpQ7Ouh1ZLlsPEPUu9LJ6XF+0MY8eec2zbcYSde8/TdXaEUd90ogtSgKZpDF32c7JnlA9PDqEYBCXuDEwGJbIopZTkZdl5bfdZAmpIZOgIjL7EtEKzJ8vG7UvKQCHCqWCQ13adYdvrR+g43E/f8DgIFSm1K4jUCOghDk9Osef4IM/85RCvdpxmcNyHrocECQH5Lhs1hbNHzlkFW00GWqvduDItMbsGTvSNsv39M3SFk5jQ10lO0ON+mg6fXvTx3KudfHrRFzef02Hi0Q21cbZEzCo4w2ZkeWNBnK1v2Mfvdx6j48gAqpZ+ppWI4bEpfrG9k/HJYMSmSIHXk0FTeVacbyxmF2wxsHx+fpxtf1c/+7sGCIbX2Y3gnQ8/paOrl/CqAMCZYWLxQnesWxxSCp5jkdzaWBi3EU/1jfLG/gucHRpDUdQIrwVSapHnpFTZ8vx/8U+qEARUQWamg8V1BVgNobQ0ESkFm4wK7S1Fkbaq6XR1j9DVPRLn91ng9X3dcW2DIsmwGuNsM0gp2GiQNM+Nfppzg+O8deA8p/vH4vw+C/x919m4dllBJhvaK+JsM0gpWFV1untHI22fX2V8IoAMp4fXC12PVt0z5+rQhD/GAQLTGqMTAZLt6ZSCfVMBfv7Kx1wc86PpUFHo5J5byvHm2lBuSHAojZyhCfjZluZwJ0z6grx/qJ8POgcIJtnXKQUHVZ29R/v4267TEVtztZvl9fHH3I2itdZNY3kOAEFN48NTQ/z6jU7OpFh6Mi4RScCYL8Cf3z3O23tDayzLYaG11kOxO71U8Gpw2BQe21CPFAJN1zncfYkX3+7izEByscz2hlVdQ9U1ei6O89s3Ozl4fBCDhGXz81h3kxeHxZx2lRAHEZ5VwpqWIqpLXKgCfAGNZ7cfYvfhnkhYT3ZPknI2FT3CU32j/GbHEQ4eHyTHYWbjikrml+WkXYfFISy2qjCT+1bNxWQ2EAReevcE7x3qSxLar3z8qpicVuno6ueV3afpueSjNN/BxpUVlHiuf2k8eHst9aVZKELwhx1d/O6trkSXpEhLMGHRO/ef54//PEbvsI/2hgLWLCpKecDPhi8vK6W9IR+LSeF/Jwd5cWcXA5cnE92SIqVgVZURZtmtrK7Lp8Bh4a//PknHRxfIMGo8tL4Sr9uOioIqJKqQaCJ+yNCtUXQsi2JkTUMxToeVKRV++vIBxvx+Vjfks6zOjVHICJUkdwiKtaDxKYMreQJvMxu5d8VcfvXdJdy51EtrnZueoQle/tdpvG47C8pc5Lgs7Dk6iG9KjeSf8UePCBcDob6728v54uJSMm0mvvXcLj46PchPNjfz6F0LWN1YiM1qZP/RQQQCBGgxY+m6SC3YqBjYuKyCJ7/ehMNmxG5V8DhtzC12cqJnlA86B5hf5qKlOptXdnUzMhGtNq4UHBq4tsjJt2+rpcbr4sHnd3PwxBD/+dkdtFV7sJoNZFiNtFS7WbWoiKNnh+kd8aUn2GxUeOF7y9mytgYpBUKAEr4Dzp1j4c6bi9l7bJAdHedZVJnNutZi/rHvAv7pUOaWTLAiBQ+tr2NdazFPvPABB09cZPtTq/DmZsTdsUkh8LisVJe4OHp+hL4RX2S0OMGhI0qSabew7ZGlrG0qRDGAYgCphArdGUpFUuN10js8wUcnL7FyUSHTkzoHjg2BFn+FqgiBWRGsbyti4wovb+45xYhvkl8+3EZlfia6AF1eSU+2jYqCTM4OjHNp3I8QAi2xpsuwGHn2O2201xfGmpOiPC+Tp+9vJttpYdcnffzgawspdtsT3SCclDdV5eAPqEwHdR6+YwGlnpjKOQWaa9w8vqGeecXRCiTyhufYTGxcXsFXV1ViUCRKyvMjXM2G/y+uyyOg6nicVhZWZvPugR6mAoGIr8Nm4oFb57JlbRW+KZWmuR68nmiheWVoiEIAxe4MNF2ns3uYUV8wKrixPJvvb6rHbFQIBDWmAxpTqTit4Y9htsOMquq451g5eGyI7oFoWjrP62RTewWZGSZsFgMGxcBUQI8+nzh2LIMagaBGdZGTkz2jHOke4f+o/tO6ELMQTgAAAABJRU5ErkJggg==',
    'perfect_veil': 'iVBORw0KGgoAAAANSUhEUgAAACwAAAAoCAYAAACFFRgXAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAA0+SURBVFhHzZhpcFvXeYafc+/FQoAEQBDcSXDfJIoiRe0SKcuyaHqVLTu261Eij5xmnIyTJl1Tp9OwiTPuZDrTOGnqto7r+kdq1+l4rNhxLC+1Lcm7Fps7JUriAm7iAoArtntvfwDEQska186Pvph3BvjOd855D872fUfYK1t1Y/XNyFYXYAIk/r9C1zUkkV6AbC0AjEgSSJIWZwoEICdRpBZfE59R16gIxFXaSdaQTFkGCSEltQRC6HFeAQE2iwG71XhNwZurXGyrzmFbdQ41hfaoUSQxBlkSZNsNSGvaStZwBR1N9+vmylsgNrJkoaoaHQSAxaxQXWwjrGkMeOaJhDVYMwnfOljHdQ15OKxGMoxGAKb8AV7+cIS3PhnnwtRC1FEFdJAEZNkMVBXZeb9nhtWeZVlNNLoGsjl/Q4firIb4yBKFuh5dz7IsUVtiZ2NZJv2jfnxLIdCjnQK01ufwD9/ayvVN+RRlW3FkmMhzWHBkmMh3Wthc7aK5JpvL/gCXJhfi9XQgGNapK7WzpyGXs4NeACTpKrMbwzUFm2QJRYKK/HTubC3lna5JLngW0TUwCDDKsLXKxY8f3EJDuYsMsxGTomCUowtVB4QQmA0yBU4L60ocLAWDjEwvEdZ0kEAXMDKxjCvdwt37yjnZOYmuS3GCSJn1ax4JAsh3Wvj6rbX8z4fjdA560fRE5aZyF48+uIVatwNJCJI/ayFJgnXFmfzTN1to31ycUhaOaLx6xoPTZuL7hxpTytbimoKdNhM/PNLMxOwypwan43ZJCDZVuvjbw83UlWam1Pk8+OmRLezfVIC0Zrf96OkztK7P48bGIhT5ykGzVrAQiY0sS4J7WyvItJj55Qs9iXIB5YXpfPvu9TRWZSVX/9wQQvDQrXU0VThTTohAKMK/Hu3jz7+ygX0NhfH+kpEiWEHCIGQMQmZTeTb33lDJj545S0AFVQOzDDk2I9+4qYbrNxai6cR5Legk/DQdzIrCzspcfnyomRKXOb6AIqrOa2c8/Ofbg3zjQB1FTjOGNWvgqkuissjOU3/ZypOvDnD6wkzcbjbItG8tZl9zYYr/F0VTmYuv76/DbEocn4GQyvu9kwTDKl9rr8VqNqTUuargv/ijBsZnl/nVywMp9ppiBwd3l1HgtKbYvwyOtNexe31uyjYdnlrgiRe72Vydw+76/KSSVcFSjAIO7HKzqdzJk6/0J+wSOB0mbtnpZmtdTryy0BPUVFBTqMapa1qKL0SPs1X+4P4GyvIz4n1FNLg0tUC/x8fBPeWU5tvQEegIpGRRAN++Yx2Xfcu8dHI4RXBVsZ1bd7hTxWoJqiqokVXqqJFwnFpETfFFgC4lWON2crC1FGLnclgDz8wKr3/soTQ3nesai9CEhCYkZHPBhg4lK3px/HF7FS31uTz2bCcXxheIxMRl2czcf30l121Imp6kmw5gYNzPO59M8N8nLnK8a4L3eyY52T3Fye4pui55WQmppFuMWE3KFTGFEJCfZeGpY+eihli7y8EIRdlW6ssy6R3xMTsfTBXccaiRpUCEf/xNNxFVjwuuLLDx/XsbyTArMUtC8OjsEs+9c5H/eP08v/9olHe6Jvjkwiw9Q3N8ejHKriEv3SNeRmcW0XVw2EyYjYm2hIDMdBOT/hW6Ls7FBS8FIphNMjdvK2ZidpmuIS9yQW5lR6ndwK76LPZuquSl98Z4f2CGsKqjS5BmlNnXUMiBbSXR9RejqsOxU2P8/MVujn4wwrkxL/MrwaRIT0eLMaiqTPtXGBz3c3pwBkmRKc21YTTIaDrIsTYr8jJ47vglwuFEVKUIiY2lWZgkmc6Lc0hmXcWh+ritpY5Mm5VjZ8YJRTTU2ChzHWl857Z10SWeJPiN02P84mgPb306wYw/AEQjvVWuitXQ0fQoF1bCDI77eeJoLy+8e4n55TCaDnqszXyHhc3lrrhYgIuTC/QOeTmww82WquyojvXNtbhLi+gc9TM9H4g2ABgViV21eRS6Uo+x452T/PK3vXQNzRFW18SYnwOXvSv87DfdDK2GmzGYjTJ/9ZWGFFswrNI35mM5pLK1OiZ42/ZmsnOyOHF2kuVAIhY1GWTatlx5SXQPe+kZ8RL5AmJX4VsM8vjzXcz4AnGbJARFLgtbq1Pjk4FhP+c9fjbXupCEvITVILBIEid6p1gJR+K72GSUaWkoJACEBKDAm5+O8/zxiwTCIWRZjfOL4M1PxzjeNZEy8PQ0A+1b3aQpkKaAQYJ+j4++8XnWV7iQqtdXUeDOR1VVND1RUQhBe1NxSvAxMr3Iix8MMzDmTxi/BHQdnn5lgMWVcNwmBChy6gWsA32jXsZml5AMioIiK7x94gQ+X0KIJEH7jkTcqmo650fn6Tw/F7f9IdA9PMdrZzzx32lGhV11eWRYUmOIUERD1TSk0pIysrNzOPXeWRb8CynhZUtdXvyym5pb5qWPRjg34b9mAvpF8MTRHlRdR4v9m4UuK4dvrEnx6R6cY3h8AUmNSIRUUMMKki7iAg3ojIz7MQJGIByMMDcfuCJV/0NgIRwmBFEKCKgqozOLKT6XphYYm11ASrlfkxCM6Dz67Bmm56O7uDQvg7tbSyl0Wda6fmkc2lcTj9RDYZXjn05w9MTQWjf8S+HVkAdyC3MwmqKpObEN8dH5y/z6rdj9DjSUOdm/6cpj7stgW10uh9pqEICm6/QMe/m3l3rXuuGwGgEduWrDzo6GrZux57nQhIGhqQU0TUeSIBTWGfD4cdrSqCvJxGpW0DQY8PjwzgdjF0x01a9NZa4FXY/WKXZZ+eHhZipyM1CEoM/j4xcvdnNqYCaRyQjIspk4sLOUu1rLkQ3pZR3LQSitrWJPfRG6ptLv8YLQCYZgKaAy4PFT63ZQUWAjJzONcEilb9jPUkBD1wW6Lq75lrAWq4IP7CrhrpZS0g0KEvBnv/qQN86Oo2mJdMppM3Hn7lIO31jL3EII2Wov71j2B5iZnKWwKI89DW7qijN58xMPkVi4thJUGZ9ZoshlobLQToHTwjnPPIPj83ER/1fB5bk2vnl7HRUFNmQEz7xxnidfi2U4sabcOek80F7DXa0VdA3N8i8vdSNn5dV1OBxOZi/PcnoKghGZ+66roq44k5HJJaZ8K6iazrR/hbCmUl+WSXF2OopB0DPsw7sQhC8g+Ht3baB9SxFmo8zTr57j5y/3shiIXiAWo8KNmwr5zh3rWF+WyfHucZ56pY8Bjw8JPYImwmgizPlRH10XZtE0nX1NRbTvKIgfY0FV5a0zYzz5u348s0vsrs/npi3FOGzG1XfEz4SOiGcMmpC4abubPU0FKAaFU4OzPH2snznvMibAJCDHbuTOliJ2rnfhnV/htydHOO9ZIBgCOSu3usOeGQ027rq1lQdvbSTLnsZPnz3Lc+9eYikQwWY1sKMqG0VIfNQ3RV6mheaaHGqKM/lg4HL0yvyM4zEKgS6k+AY90l7Lttpcuobm+PEzH3NxfJ6W9fkUZ1nxzCwRCqv4FkPUlNipKnIgkOkf8TO/HEbOyq3psGc6qW9t5IHbWnDnOHjs16d5/vggC8EI9+ws4YmHt3PbjhJ2byxgej7As29ewGVPo6kqm9GpRfpGfYTDq/nJ1SDQY8fIgZ0l3LOngsx0Mz948gPOnp/hr7/axJ/es5G2rcXYbEZOdk4yPrvMmYFZnBlmbtlVRppRpn/EFxW887a9tN13CzUuJ3c88jIneydQNY3bt7t59IEmMtIMpJkU8pzp1BTb8cwscqJriqoiB7fvLOXY6VGmvctrVSYhKrgq38ZDN9fRWOHi4cePc7Jzghd+chNtmwqxmBQsZoVNlS7amvPpG/LRM+Klf2SeHIeFg61lKJKE3Lq/reO7f3KEiqwsvvZ3x7g4Po8iS/zsuy08fKAeg8GArCjIsowQ4Mwws7s+l3NjXn733jAb3ZnsXJ/L259MsbCsxl8dUzahLhC6xOG2Gu5sqeBv/v193u0e478e2U9DiROk6EunHosSc21WGspddA/76Rn10jfkI89u4eDuMuRbDt7XsfeGPTz+k3/m9KUAlvR0HntoO/s3FZMc5YlY6AdgNirsbyymd8TLKx+NcFOzGwnB2QuzqLF3q2TBsiSxf3MxX22r5s1THmbnVvj7I9upczuBaKqfDKGDy25mb2M+wYjKO12T9A37cOemI2/esbdD16Hz4y78wsUjD+6irdmNJMRnCobo37F3QwHBsMr0YoBDbVX8/mNPLL9LFVyRb+fB9jocNhPnRv3cvr2Ede5EVnE1wQDpZgPpZiPDk4v0jnoJaRqyxVXRMTIeZGp6mRv2buXeG9aRZopOf/LL4tUEA9SXOdHQcdnNbKh08vrHY6yE1JivwGo2cMeuMg631xAIqawrdVBZYIuWJzOG+M/Yl7wsC0XZVgbH/BzvnEBeslZ3zFib8Sk5fO/+ZjLTDawEw6wEwywFUrmYzGCCFrPCSkjFbjEyOLLAuXF//MquyrfzwA1VWNJkDHJ01paS6i5erZ+ksuVQGKfdyNDEPP3Dc/wv0VmlyXFw44IAAAAASUVORK5CYII=',
}

_ALLY_CONFIRM_MARKER_PNG = "iVBORw0KGgoAAAANSUhEUgAAABUAAAAVCAAAAACMfPpKAAAAUUlEQVQYGW3BwREDQQzDMLL/opVoPb6XAbnIRS5ykQpLSv7CR0qeMOSRimFISYUlJX/hIyVPDCWPVChjpGSEkiEjlAxZQZasIEsucpGLXOTyA08vEBZ866skAAAAAElFTkSuQmCC"

class CombatDeadline(Exception):
    """Cancel stale work before submitting another input."""


def _check_deadline(deadline, reserve=0.0):
    # V13.1: hard DeadTime/deadline counter intentionally disabled.
    return



STONE_SKIN_TEMPLATE = "./bilder/arena_live_stoneskin.PNG"
VEIL_TEMPLATES = (
    "./bilder/arena_live_veil.PNG",
    "./bilder/arena_live_perfect_veil.PNG",
)
YOUR_TURN_TEMPLATE = "./bilder/arena_live_your_turn.PNG"
RETURN_TEMPLATE = "./bilder/arena_live_return.PNG"


def _rel_point(rect, x, y):
    left, top, width, height = rect
    ref_w, ref_h = REFERENCE_SIZE
    return (
        left + round(x * width / ref_w),
        top + round(y * height / ref_h),
    )


def _rel_region(rect, x1, y1, x2, y2):
    left, top, width, height = rect
    ref_w, ref_h = REFERENCE_SIZE
    sx1 = left + round(x1 * width / ref_w)
    sy1 = top + round(y1 * height / ref_h)
    sx2 = left + round(x2 * width / ref_w)
    sy2 = top + round(y2 * height / ref_h)
    return (sx1, sy1, max(1, sx2 - sx1), max(1, sy2 - sy1))


def _crop_abs(frame_bgr, rect, region):
    if frame_bgr is None or rect is None or region is None:
        return None

    left, top, _, _ = rect
    x, y, w, h = region

    x1 = max(0, int(x - left))
    y1 = max(0, int(y - top))
    x2 = min(frame_bgr.shape[1], x1 + int(w))
    y2 = min(frame_bgr.shape[0], y1 + int(h))

    if x2 <= x1 or y2 <= y1:
        return None

    return frame_bgr[y1:y2, x1:x2]


def _skill_family(skill_name):
    if skill_name == "skill_mythical_transform_a4":
        return "__global__"

    match = re.match(r"^skill_(.+)_a\d+$", skill_name.lower())
    if not match:
        return skill_name.lower()
    return match.group(1)


def _runtime_skill_plan():
    non_a1 = [entry for entry in SKILL_PLAN if entry[1] != "A1"]
    a1 = [entry for entry in SKILL_PLAN if entry[1] == "A1"]
    return non_a1 + list(GLOBAL_SKILL_PLAN) + a1


def _normalize_family_hint(value):
    value = str(value or "").strip().lower()
    if value.startswith("arena_live_lead_"):
        value = value[len("arena_live_lead_"):]
    elif value.startswith("arena_live_"):
        value = value[len("arena_live_"):]
    elif value.startswith("skill_"):
        value = value[len("skill_"):]
    value = re.sub(r"_a\d+$", "", value)
    aliases = {
        "glicea": "gliseah",
        "galathier": "galathir",
        "yummeko": "yumeko",
    }
    return aliases.get(value, value)


def _family_matches_hint(family, hint):
    family = _normalize_family_hint(family)
    hint = _normalize_family_hint(hint)
    if not family or not hint:
        return False
    return (
        family == hint
        or family.startswith(hint + "_f")
        or hint.startswith(family + "_f")
    )


def _family_root(value):
    """Base champion key shared by mythical forms, e.g. komidus_f2 -> komidus."""
    value = _normalize_family_hint(value)
    return re.sub(r"_f[12]$", "", value or "")


def _count_positive_buff_icons(crop):
    """Count blue positive-buff tiles without matching dozens of templates.

    RAID renders positive buffs as small blue UI tiles immediately above HP bars.
    This lightweight detector works on a tiny existing ROI and is only called for
    Maria / Harvest Jack / Cruetraxa rules, so ordinary turns pay zero cost.
    """
    if crop is None or crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([85, 20, 45], dtype=np.uint8),
        np.array([125, 255, 235], dtype=np.uint8),
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    h, w = mask.shape[:2]
    row_counts = np.count_nonzero(mask, axis=1)
    row_active = row_counts >= max(5, int(round(w * 0.06)))

    bands = []
    y = 0
    while y < h:
        if not row_active[y]:
            y += 1
            continue
        y2 = y + 1
        while y2 < h and row_active[y2]:
            y2 += 1
        # True icon rows are ~14-18 px at reference size.  Shorter bands are
        # floor/particle noise; very tall bands are scenery.
        if 8 <= (y2 - y) <= 26:
            bands.append((y, y2))
        y = y2

    total = 0
    for y1, y2 in bands:
        sub = mask[y1:y2]
        col_counts = np.count_nonzero(sub, axis=0)
        col_active = col_counts >= max(2, int(round((y2 - y1) * 0.18)))
        x = 0
        while x < w:
            if not col_active[x]:
                x += 1
                continue
            x2 = x + 1
            while x2 < w and col_active[x2]:
                x2 += 1
            width = x2 - x
            if 8 <= width <= 26:
                total += 1
            elif 26 < width <= 90:
                # Adjacent icons can touch after thresholding. Split by the
                # observed ~17 px tile pitch instead of treating them as one.
                total += max(1, int(round(width / 17.0)))
            x = x2
    return int(total)


def _largest_colour_component(mask):
    try:
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    except Exception:
        return 0

    best = 0
    for i in range(1, count):
        _, _, w, h, area = stats[i]
        if 4 <= w <= 26 and 4 <= h <= 26 and 8 <= area <= 240:
            best = max(best, int(area))
    return best


def _hp_red_ratio(crop):
    if crop is None or crop.size == 0:
        return 0.0

    b = crop[:, :, 0].astype(np.float32)
    g = crop[:, :, 1].astype(np.float32)
    r = crop[:, :, 2].astype(np.float32)

    mask = (r >= 105) & (r >= g * 1.35) & (r >= b * 1.35)
    return float(mask.mean())


def _green_hp_ratio(crop):
    if crop is None or crop.size == 0:
        return 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([35, 80, 65], dtype=np.uint8),
        np.array([95, 255, 255], dtype=np.uint8),
    )
    return float(np.count_nonzero(mask)) / float(mask.size)


def _affinity_relation(crop):
    if crop is None or crop.size == 0:
        return "unknown"

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    green = cv2.inRange(
        hsv,
        np.array([35, 125, 115], dtype=np.uint8),
        np.array([90, 255, 255], dtype=np.uint8),
    )
    neutral = cv2.inRange(
        hsv,
        np.array([10, 115, 125], dtype=np.uint8),
        np.array([40, 255, 255], dtype=np.uint8),
    )
    red1 = cv2.inRange(
        hsv,
        np.array([0, 135, 110], dtype=np.uint8),
        np.array([10, 255, 255], dtype=np.uint8),
    )
    red2 = cv2.inRange(
        hsv,
        np.array([170, 135, 110], dtype=np.uint8),
        np.array([179, 255, 255], dtype=np.uint8),
    )
    red = cv2.bitwise_or(red1, red2)

    scores = {
        "positive": _largest_colour_component(green),
        "neutral": _largest_colour_component(neutral),
        "negative": _largest_colour_component(red),
    }

    relation = max(scores, key=scores.get)
    return relation if scores[relation] >= 10 else "unknown"


def _masked_corr(a, b, mask):
    av = a[mask].astype(np.float32)
    bv = b[mask].astype(np.float32)

    if av.size < 20:
        return 0.0

    av -= av.mean()
    bv -= bv.mean()

    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom <= 1e-6:
        return 0.0

    corr = float(np.dot(av, bv) / denom)
    return max(0.0, min(1.0, (corr + 1.0) * 0.5))


def _cosine_binary(a, b, mask):
    av = (a[mask] > 0).astype(np.float32)
    bv = (b[mask] > 0).astype(np.float32)

    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom <= 1e-6:
        return 0.0

    return max(0.0, min(1.0, float(np.dot(av, bv) / denom)))


def _hist_similarity(a_bgr, b_bgr, mask_u8):
    try:
        ah = cv2.cvtColor(a_bgr, cv2.COLOR_BGR2HSV)
        bh = cv2.cvtColor(b_bgr, cv2.COLOR_BGR2HSV)

        hist_a = cv2.calcHist([ah], [0, 1], mask_u8, [24, 24], [0, 180, 0, 256])
        hist_b = cv2.calcHist([bh], [0, 1], mask_u8, [24, 24], [0, 180, 0, 256])

        cv2.normalize(hist_a, hist_a)
        cv2.normalize(hist_b, hist_b)

        corr = float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))
        return max(0.0, min(1.0, (corr + 1.0) * 0.5))
    except Exception:
        return 0.0


def _central_hsv_stats(image_bgr):
    if image_bgr is None or image_bgr.size == 0:
        return 0.0, 0.0

    size = 96
    image = cv2.resize(image_bgr, (size, size), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    yy, xx = np.ogrid[:size, :size]
    center = (size - 1) / 2.0
    radius = size * 0.33
    mask = ((xx - center) ** 2 + (yy - center) ** 2) <= radius ** 2

    sat = hsv[:, :, 1][mask].astype(np.float32)
    val = hsv[:, :, 2][mask].astype(np.float32)

    if sat.size == 0:
        return 0.0, 0.0

    return float(sat.mean()), float(val.mean())


def _availability_against_template(icon_crop, template):
    """
    Template'y użytkownika są aktywnymi ikonami.
    Cooldown/disabled w RAID jest wyraźnie ciemniejszy / mniej nasycony.
    """
    cur_sat, cur_val = _central_hsv_stats(icon_crop)
    ref_sat, ref_val = _central_hsv_stats(template)

    value_ratio = cur_val / max(1.0, ref_val)
    sat_ratio = cur_sat / max(1.0, ref_sat)

    available = (
        value_ratio >= SKILL_AVAILABLE_VALUE_RATIO_MIN
        and sat_ratio >= SKILL_AVAILABLE_SAT_RATIO_MIN
    )

    return available, value_ratio, sat_ratio


def _cooldown_overlay_fraction(icon_crop, template):
    """Dark cooldown sectors survive mean-brightness tests due to white digits.

    Compare local value ratios against the clean art, excluding borders. Tested
    against real ready/selected icons and countdowns 2/3 from the supplied replay.
    """
    if icon_crop is None or template is None or not icon_crop.size:
        return 0.0
    current = cv2.resize(icon_crop, (96, 96))
    reference = cv2.resize(template, (96, 96))
    cv = cv2.cvtColor(current, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    rv = cv2.cvtColor(reference, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    cv = cv2.GaussianBlur(cv, (5, 5), 0)
    rv = cv2.GaussianBlur(rv, (5, 5), 0)
    yy, xx = np.ogrid[:96, :96]
    valid = ((xx - 47.5) ** 2 + (yy - 47.5) ** 2 < 30.72 ** 2) & (rv > 70)
    if np.count_nonzero(valid) < 100:
        return 0.0
    return float(np.mean((cv / np.maximum(rv, 1))[valid] < .60))


def _expected_physical_index(skill_id):
    """A1=0, A2=1, A3=2, A4=3. Pasywka P nie ma skill_id i jest ignorowana."""
    mapping = {
        "A1": 0,
        "A2": 1,
        "A3": 2,
        "A4": 3,
    }
    return mapping.get(skill_id)


def _frame_rel_region(frame_bgr, ref_region):
    """ROI zapisane w referencji 1020x793 -> region lokalny bieżącej klatki."""
    if frame_bgr is None or frame_bgr.size == 0:
        return None

    h, w = frame_bgr.shape[:2]
    ref_w, ref_h = REFERENCE_SIZE
    x1, y1, x2, y2 = ref_region

    sx1 = max(0, round(x1 * w / ref_w))
    sy1 = max(0, round(y1 * h / ref_h))
    sx2 = min(w, round(x2 * w / ref_w))
    sy2 = min(h, round(y2 * h / ref_h))

    if sx2 <= sx1 or sy2 <= sy1:
        return None

    return frame_bgr[sy1:sy2, sx1:sx2]


def _bright_green_ratio(crop):
    if crop is None or crop.size == 0:
        return 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(
        hsv,
        np.array([40, 140, 100], dtype=np.uint8),
        np.array([95, 255, 255], dtype=np.uint8),
    )

    # Małe kolorowe buffy/ikony są mniej istotne niż gruba zielona ramka.
    kernel = np.ones((3, 3), np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, kernel)

    return float(np.count_nonzero(green)) / float(green.size)


def detect_combat_turn_owner(frame_bgr):
    """
    Zwraca:
      "player"   - zielona ramka naszego portretu,
      "opponent" - zielona ramka portretu przeciwnika,
      None       - loading/draft/niepewna klatka.

    Ten detector jest niezależny od napisu Your Turn, który w przesłanych
    nagraniach bywał niewykrywany mimo widocznego tekstu.
    """
    own_crop = _frame_rel_region(
        frame_bgr,
        COMBAT_PLAYER_PORTRAIT_REGION,
    )
    opp_crop = _frame_rel_region(
        frame_bgr,
        COMBAT_OPPONENT_PORTRAIT_REGION,
    )

    own = _bright_green_ratio(own_crop)
    opp = _bright_green_ratio(opp_crop)

    if (
        own >= COMBAT_PORTRAIT_GREEN_RATIO_MIN
        and own >= max(
            COMBAT_PORTRAIT_GREEN_RATIO_MIN,
            opp * COMBAT_PORTRAIT_GREEN_DOMINANCE,
        )
    ):
        return "player"

    if (
        opp >= COMBAT_PORTRAIT_GREEN_RATIO_MIN
        and opp >= max(
            COMBAT_PORTRAIT_GREEN_RATIO_MIN,
            own * COMBAT_PORTRAIT_GREEN_DOMINANCE,
        )
    ):
        return "opponent"

    return None


def combat_turn_debug(frame_bgr):
    own = _bright_green_ratio(
        _frame_rel_region(frame_bgr, COMBAT_PLAYER_PORTRAIT_REGION)
    )
    opp = _bright_green_ratio(
        _frame_rel_region(frame_bgr, COMBAT_OPPONENT_PORTRAIT_REGION)
    )
    return {
        "owner": detect_combat_turn_owner(frame_bgr),
        "player_green": own,
        "opponent_green": opp,
    }


class CombatAnalyzer:
    def __init__(
        self,
        vision,
        active_families=None,
        opponent_families=None,
        combat_condition_families=None,
    ):
        self.vision = vision
        self.autonomy = get_autonomy_controller()
        self.autonomy_combat_enabled = bool(
            AUTONOMY_ENABLED and AUTONOMY_COMBAT_ENABLED and self.autonomy.enabled
        )
        self.autonomy_target_enabled = bool(
            AUTONOMY_ENABLED and AUTONOMY_TARGET_ENABLED and self.autonomy.enabled
        )
        self.active_family_hints = {
            _normalize_family_hint(x)
            for x in (active_families or ())
            if _normalize_family_hint(x)
        }
        self.opponent_family_hints = {
            _family_root(x)
            for x in (opponent_families or ())
            if _family_root(x)
        }
        # Full opponent_family_hints power the autonomous opponent model.
        # combat_condition_families is a separate conservative post-ban set used
        # only by special opener exceptions (e.g. Fabian vs enemy Gliseah).
        condition_source = (
            combat_condition_families
            if combat_condition_families is not None
            else opponent_families
        )
        self.final_opponent_family_hints = {
            _family_root(x)
            for x in (condition_source or ())
            if _family_root(x)
        }
        self._opening_rule_logged = set()

        # V16.2: keep family-specific A4 semantics, but do not waste combat CPU
        # matching skill templates for champions that are not in the drafted team.
        # Mythical roots keep both forms because form changes happen during battle.
        # If draft hints are missing/mismatched, fail open to the full plan.
        full_skill_plan = list(SKILL_PLAN)
        self.skill_plan = full_skill_plan
        if ACTIVE_COMBAT_TEMPLATE_FILTER and self.active_family_hints:
            active_roots = {_family_root(x) for x in self.active_family_hints if _family_root(x)}
            filtered = [
                entry for entry in full_skill_plan
                if _family_root(_skill_family(entry[0])) in active_roots
            ]
            if filtered:
                self.skill_plan = filtered
                print(
                    "COMBAT ACTIVE TEMPLATE SET: "
                    f"{len(active_roots)} champs -> {len(filtered)} skill templates "
                    f"(filtered from {len(full_skill_plan)})"
                )
            else:
                print(
                    "COMBAT ACTIVE TEMPLATE SET: no safe family match -> "
                    f"fallback full {len(full_skill_plan)} templates"
                )

        # A4 remains family-specific: Arbiter A4 is revive, while explicitly
        # configured mythical A4 entries may be transform. Generic mythical A4
        # is only a visual helper inside attack_type=transform handling.

        # Cache tylko obrazów template. Nie przechowujemy "slot -> champion"
        # pomiędzy turami, bo wcześniejszy błędny bind potrafił powodować
        # np. Harima w logu podczas realnej tury Fenaxa.
        self._template_cache = {}
        self._deadline = None
        self._resolved_skill_paths = {}
        self._veil_assets = None
        self._veil_sources = {}
        self._veil_variant_cache = {}
        # V14.2: tiny grayscale variants for Block Damage / Unkillable /
        # Counterattack are built once per window scale and reused.
        self._target_avoid_assets = None
        self._target_avoid_sources = {}
        self._target_avoid_variant_cache = {}
        self._enemy_state_cache = None
        self._enemy_state_cache_at = 0.0

        # V15 scalable A1 identity. Large databases never run an unbounded number
        # of expensive exact ROI matches on every turn.
        self._a1_prefilter_template_cache = {}
        self._seen_actor_families = set()
        self._missing_special_effect_logged = set()
        self._fixed_a1_fallback_logged = set()
        self._slot_identity_logged = set()

        # Count active buttons per family.  RAID right-aligns the skill row before
        # the passive, so this lets the fallback derive A1's physical center for
        # 2-skill, 3-skill and mythical 4-skill champions without hard-coding one
        # layout for the entire roster.
        self._active_skill_count_by_family = {}
        for entry in self.skill_plan:
            family = _skill_family(entry[0])
            skill_id = str(entry[1]).upper()
            if skill_id.startswith("A") and skill_id[1:].isdigit():
                self._active_skill_count_by_family.setdefault(family, set()).add(skill_id)
        self._active_skill_count_by_family = {
            family: len(skill_ids)
            for family, skill_ids in self._active_skill_count_by_family.items()
        }

        # V13.8: static lookup tables for the cheap second-frame verification.
        # They only reference SKILL_PLAN; no cross-turn actor identity is cached.
        self._a1_entry_by_family = {
            _skill_family(entry[0]): (priority, entry)
            for priority, entry in enumerate(self.skill_plan)
            if entry[1] == "A1"
        }
        self._skill_entry_by_name = {
            entry[0]: (priority, entry)
            for priority, entry in enumerate(self.skill_plan)
        }
        self.decision_tree = CombatDecisionTree()

    # --------------------------------------------------------
    # Geometry
    # --------------------------------------------------------
    def geometry(self, rect):
        enemy_hp = {
            1: _rel_region(rect, 300, 215, 395, 255),
            2: _rel_region(rect, 465, 208, 570, 252),
            3: _rel_region(rect, 625, 220, 745, 270),
            4: _rel_region(rect, 790, 235, 895, 282),
        }
        enemy_points = {
            1: _rel_point(rect, 345, 315),
            2: _rel_point(rect, 520, 315),
            3: _rel_point(rect, 685, 315),
            4: _rel_point(rect, 840, 330),
        }
        enemy_hp_bar = {
            slot: _rel_region(rect, *region)
            for slot, region in ENEMY_HP_BAR_REGIONS_REF.items()
        }
        veil_regions = {
            1: _rel_region(rect, 270, 175, 410, 385),
            2: _rel_region(rect, 445, 170, 590, 390),
            3: _rel_region(rect, 610, 180, 760, 405),
            4: _rel_region(rect, 775, 190, 920, 415),
        }
        # V15.22 target-status ROI: anchor to the calibrated enemy HP bar and
        # extend UPWARD, where RAID actually renders Stoneskin/Veil/Unkillable.
        # The old fixed ROIs started too low. In the supplied 2026-10-05 frame,
        # Stoneskin on slot 2 scored ~0.83 in the real icon area but only ~0.57
        # inside the old ROI, producing the false reason `no-stoneskin`.
        sx = rect[2] / float(REFERENCE_SIZE[0])
        sy = rect[3] / float(REFERENCE_SIZE[1])
        buff_regions = {}
        for slot, (hx, hy, hw, hh) in enemy_hp_bar.items():
            pad_x = max(2, round(12 * sx))
            up = max(8, round(58 * sy))
            below_top = max(4, round(18 * sy))
            buff_regions[slot] = (
                hx - pad_x,
                hy - up,
                hw + 2 * pad_x,
                up + below_top,
            )
        affinity_regions = {
            1: _rel_region(rect, 360, 145, 410, 185),
            2: _rel_region(rect, 530, 145, 585, 185),
            3: _rel_region(rect, 685, 180, 740, 220),
            4: _rel_region(rect, 845, 195, 905, 240),
        }
        ally_points = {
            slot: _rel_point(rect, x, y)
            for slot, (x, y) in ALLY_SLOT_POINTS.items()
        }
        ally_hp = {
            slot: _rel_region(rect, x1, y1, x2, y2)
            for slot, (x1, y1, x2, y2) in ALLY_HP_REGIONS.items()
        }
        # Positive buff icons sit immediately above the HP bar.  Expand the
        # already calibrated HP ROI rather than introducing another screen scan.
        ref_scale = ((rect[2] / 1020.0) + (rect[3] / 793.0)) * 0.5
        ally_buff_regions = {}
        for slot, (x, y, w, h) in ally_hp.items():
            up = round(45 * ref_scale)
            right = round(20 * ref_scale)
            down = round(5 * ref_scale)
            ally_buff_regions[slot] = (x, y - up, w + right, h + up + down)
        active_ring_regions = {
            slot: _rel_region(rect, x1, y1, x2, y2)
            for slot, (x1, y1, x2, y2) in ALLY_ACTIVE_RING_REGIONS.items()
        }
        skill_bar = _rel_region(rect, *ROI_SKILL_BAR)

        return {
            "enemy_hp": enemy_hp,
            "enemy_hp_bar": enemy_hp_bar,
            "enemy_points": enemy_points,
            "veil_regions": veil_regions,
            "buff_regions": buff_regions,
            "affinity_regions": affinity_regions,
            "ally_points": ally_points,
            "ally_hp": ally_hp,
            "ally_buff_regions": ally_buff_regions,
            "active_ring_regions": active_ring_regions,
            "skill_bar": skill_bar,
        }

    # --------------------------------------------------------
    # Active ally ring
    # --------------------------------------------------------
    def detect_active_ally_slot(self, frame, rect, geometry):
        ratios = {}

        for slot, region in geometry["active_ring_regions"].items():
            crop = _crop_abs(frame, rect, region)
            if crop is None or crop.size == 0:
                ratios[slot] = 0.0
                continue

            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(
                hsv,
                np.array([45, 150, 120], dtype=np.uint8),
                np.array([95, 255, 255], dtype=np.uint8),
            )

            # Ring jest gruby i jasny; morfologia usuwa pojedyncze zielone buffy.
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            ratios[slot] = float(np.count_nonzero(mask)) / float(mask.size)

        ordered = sorted(ratios.items(), key=lambda pair: pair[1], reverse=True)
        if not ordered:
            return None, ratios

        best_slot, best = ordered[0]
        second = ordered[1][1] if len(ordered) > 1 else 0.0

        if best < ACTIVE_RING_GREEN_RATIO_MIN:
            return None, ratios

        if second > 0 and best < second * ACTIVE_RING_DOMINANCE:
            return None, ratios

        return best_slot, ratios

    def detect_active_actor_floor_point(self, frame, rect):
        """Locate the CURRENT actor from the large bright-green floor ellipse.

        This is intentionally independent from the small configured ally-slot
        ring regions. In Trim 7 those small regions were ambiguous exactly on
        Ankora A2, which made V13.5 search another ally.
        """
        field = _rel_region(rect, *ACTIVE_ACTOR_FIELD_REF)
        crop = _crop_abs(frame, rect, field)
        if crop is None or crop.size == 0:
            return None, {"reason": "empty-field"}

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(
            hsv,
            np.array([40, 140, 100], dtype=np.uint8),
            np.array([95, 255, 255], dtype=np.uint8),
        )
        green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((11, 5), np.uint8))

        count, _, stats, centers = cv2.connectedComponentsWithStats(green, connectivity=8)
        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
        candidates = []
        for idx in range(1, count):
            x, y, w, h, area = stats[idx]
            aspect = w / float(max(1, h))
            if area < 80 * scale * scale:
                continue
            if w < 25 * scale or w > 190 * scale:
                continue
            if h < 5 * scale or h > 100 * scale:
                continue
            if aspect < 1.05:
                continue
            cx, cy = centers[idx]
            candidates.append({
                "score": float(area + 4.0 * w + 40.0 * aspect),
                "center": (float(cx), float(cy)),
                "area": int(area), "width": int(w), "height": int(h),
            })

        if not candidates:
            return None, {"reason": "no-floor-ring"}

        best = max(candidates, key=lambda item: item["score"])
        fx, fy, _, _ = field
        cx, cy = best["center"]
        point = (
            int(round(fx + cx)),
            int(round(fy + cy - ACTIVE_ACTOR_BODY_OFFSET_Y_REF * scale)),
        )
        left, top, width, height = rect
        point = (
            min(left + width - 4, max(left + 4, point[0])),
            min(top + height - 4, max(top + 4, point[1])),
        )
        best["reason"] = "active-floor-ring"
        best["point"] = point
        return point, best

    # --------------------------------------------------------
    # Physical skill slots
    # --------------------------------------------------------
    def detect_skill_slots(self, frame, rect, geometry):
        """
        Wykrywa REALNY klaster okrągłych przycisków umiejętności.

        Ważne:
        - liczba przycisków zależy od championa,
        - pasywka P może być ostatnim kółkiem,
        - przy większej liczbie ikon cały pasek przesuwa się w lewo.

        Dlatego ROI jest szerokie, ale nie bierzemy wszystkich kół znalezionych
        przez Hough. Budujemy regularny klaster od PRAWEGO skrajnego przycisku
        w lewo: podobne Y + odstęp około 80-150 px.

        To usuwa false-positive z podłogi/okręgów postaci i jednocześnie
        nie ucina A1/A2 Ankory lub mitycznych mających więcej ikon.
        """
        region = geometry["skill_bar"]
        crop = _crop_abs(frame, rect, region)
        if crop is None or crop.size == 0:
            return []

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (9, 9), 2)

        _, _, rw, rh = rect
        scale = max(
            0.55,
            min(
                1.80,
                ((rw / 1024.0) + (rh / 769.0)) * 0.5,
            ),
        )

        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.15,
            minDist=max(55, int(72 * scale)),
            param1=120,
            param2=31,
            minRadius=max(24, int(32 * scale)),
            maxRadius=max(46, int(61 * scale)),
        )

        if circles is None:
            circles = cv2.HoughCircles(
                gray,
                cv2.HOUGH_GRADIENT,
                dp=1.2,
                minDist=max(52, int(68 * scale)),
                param1=105,
                param2=27,
                minRadius=max(22, int(30 * scale)),
                maxRadius=max(48, int(63 * scale)),
            )

        if circles is None:
            return []

        rx, ry, rw_region, rh_region = region
        candidates = []

        for cx, cy, radius in np.round(circles[0]).astype(int):
            x_screen = rx + int(cx)
            y_screen = ry + int(cy)

            # Przyciski skillów siedzą bardzo nisko w oknie.
            # Odrzuca część kół z pola walki.
            ref_y = (
                (y_screen - rect[1])
                * REFERENCE_SIZE[1]
                / max(1, rect[3])
            )
            if ref_y < 645:
                continue

            candidates.append({
                "center": (x_screen, y_screen),
                "radius": int(radius),
            })

        if not candidates:
            return []

        # Deduplicate.
        candidates.sort(key=lambda item: item["center"][0])
        dedup = []
        for item in candidates:
            x, y = item["center"]
            replaced = False

            for idx, existing in enumerate(dedup):
                ex, ey = existing["center"]
                if math.hypot(x - ex, y - ey) < max(
                    30,
                    min(item["radius"], existing["radius"]) * 0.85,
                ):
                    if item["radius"] > existing["radius"]:
                        dedup[idx] = item
                    replaced = True
                    break

            if not replaced:
                dedup.append(item)

        if not dedup:
            return []

        # PRAWE skrajne kółko jest zawsze częścią paska:
        # aktywny skill albo pasywka P.
        anchor = max(dedup, key=lambda item: item["center"][0])
        cluster = [anchor]

        current = anchor
        remaining = sorted(
            [
                item
                for item in dedup
                if item is not anchor
                and item["center"][0] < anchor["center"][0]
            ],
            key=lambda item: item["center"][0],
            reverse=True,
        )

        y_tolerance = max(11, int(15 * scale))
        min_gap = max(70, int(78 * scale))
        max_gap = max(130, int(150 * scale))

        for item in remaining:
            cx, cy = current["center"]
            x, y = item["center"]

            gap = cx - x
            y_diff = abs(cy - y)

            if gap < min_gap:
                continue

            if gap > max_gap:
                # Jeżeli następne kółko jest już zbyt daleko, klaster skillów
                # się skończył.
                break

            if y_diff > y_tolerance:
                continue

            cluster.append(item)
            current = item

            # RAID nie ma potrzeby obsługiwać >5 okrągłych ikon tutaj.
            if len(cluster) >= 5:
                break

        cluster.sort(key=lambda item: item["center"][0])

        for idx, item in enumerate(cluster):
            item["physical_index"] = idx

        return cluster


    def _slot_crop(self, frame, rect, slot):
        center_x, center_y = slot["center"]
        radius = max(24, slot["radius"])
        half = int(radius * 0.92)

        region = (
            center_x - half,
            center_y - half,
            half * 2,
            half * 2,
        )
        return _crop_abs(frame, rect, region)

    # --------------------------------------------------------
    # Robust icon-to-template similarity
    # --------------------------------------------------------
    def _icon_similarity(self, icon_crop, template):
        if icon_crop is None or template is None:
            return 0.0
        if icon_crop.size == 0 or template.size == 0:
            return 0.0

        size = 96

        icon = cv2.resize(icon_crop, (size, size), interpolation=cv2.INTER_AREA)
        tmpl = cv2.resize(template, (size, size), interpolation=cv2.INTER_AREA)

        # Centralna część ikony; ignorujemy glow/border/cooldown frame.
        yy, xx = np.ogrid[:size, :size]
        cx = cy = (size - 1) / 2.0
        radius = size * 0.34
        mask = ((xx - cx) ** 2 + (yy - cy) ** 2) <= radius ** 2
        mask_u8 = (mask.astype(np.uint8) * 255)

        icon_gray = cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY)
        tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)

        # CLAHE zwiększa odporność na przyciemnienie/cooldown.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(6, 6))
        icon_eq = clahe.apply(icon_gray)
        tmpl_eq = clahe.apply(tmpl_gray)

        gray_score = _masked_corr(icon_eq, tmpl_eq, mask)

        edge_a = cv2.Canny(icon_eq, 55, 135)
        edge_b = cv2.Canny(tmpl_eq, 55, 135)
        edge_score = _cosine_binary(edge_a, edge_b, mask)

        hist_score = _hist_similarity(icon, tmpl, mask_u8)

        # Central art ma największe znaczenie.
        score = (
            0.62 * gray_score
            + 0.24 * edge_score
            + 0.14 * hist_score
        )
        return max(0.0, min(1.0, float(score)))

    def _skill_template(self, path):
        cached = self._template_cache.get(path)
        if cached is not None:
            return cached
        image = self.vision.get_image(path)
        if image is not None:
            self._template_cache[path] = image
        return image

    def _skill_path(self, name):
        if name in self._resolved_skill_paths:
            return self._resolved_skill_paths[name]
        root = Path("./bilder")
        paths = {p.name.lower(): str(p) for p in root.iterdir() if p.is_file()} if root.is_dir() else {}
        path = paths.get((name + ".png").lower(), f"./bilder/{name}.PNG")
        # Compatibility with the exact swapped PNG pair supplied by the user.
        # Correctly named replacements are left untouched. No user files rewritten.
        swapped = {
            "skill_mikage_a2": ("21d0c0109926b4b475577e378336e9444f86e3094f2579a65300c3ec7a7b9f1d", "skill_mikage_a3"),
            "skill_mikage_a3": ("185441ffa50f214481eee66b9878d7452b700318dbccbbee75a501da35325407", "skill_mikage_a2"),
        }
        if name in swapped and Path(path).is_file():
            bad_hash, other = swapped[name]
            other_path = paths.get(other + ".png")
            if (hashlib.sha256(Path(path).read_bytes()).hexdigest() == bad_hash
                    and other_path and hashlib.sha256(Path(other_path).read_bytes()).hexdigest() == swapped[other][0]):
                path = other_path
                print(f"COMBAT TEMPLATE MAP: {name} -> {Path(path).name} (corrected swapped A2/A3)")
        self._resolved_skill_paths[name] = path
        return path

    def _direct_skill_match(self, frame, rect, skill_name):
        """
        Szuka konkretnego skilla bez HoughCircles.

        Poprzednie wersje najpierw próbowały znaleźć okrągłe przyciski.
        Na realnych nagraniach potrafiły wykryć tylko 1 kółko mimo 4 ikon,
        więc A1/A2/A3 były przypisywane do złych pozycji.

        Tutaj template jest szukany bezpośrednio w ROI paska umiejętności.
        """
        path = self._skill_path(skill_name)
        if self._skill_template(path) is None:
            return None

        # V13.2: the user's RAID client is normally 1024x768.
        # At reference size one scale is enough and removes most recognition lag.
        rw, rh = rect[2], rect[3]
        ref_w, ref_h = REFERENCE_SIZE
        sx = rw / max(1.0, float(ref_w))
        sy = rh / max(1.0, float(ref_h))
        near_reference = abs(sx - 1.0) <= 0.025 and abs(sy - 1.0) <= 0.025
        scales = (1.0,) if near_reference else (0.95, 1.00, 1.05)

        match = {"score": -1.0}
        for scale in scales:
            candidate = self.vision.match(
                frame, path, confidence=0.0, grayscale=False,
                scales=(scale,), roi=ROI_SKILL_BAR, auto_roi=False,
            )
            if candidate.get("score", 0.0) > match.get("score", -1.0):
                match = candidate

        box = match.get("box")
        center = match.get("center")
        score = float(match.get("score", 0.0))

        if box is None or center is None:
            return None

        # VISION zwraca współrzędne lokalne względem client frame.
        screen_center = (
            rect[0] + int(center[0]),
            rect[1] + int(center[1]),
        )

        x, y, w, h = box
        crop = frame[
            max(0, y):min(frame.shape[0], y + h),
            max(0, x):min(frame.shape[1], x + w),
        ]

        template = self._skill_template(path)
        available, value_ratio, sat_ratio = _availability_against_template(
            crop,
            template,
        )

        cooldown_fraction = _cooldown_overlay_fraction(crop, template)
        blocked_visual = cooldown_fraction >= .30
        return {
            "cooldown_fraction": cooldown_fraction,
            "blocked_visual": blocked_visual,
            "score": score,
            "center": screen_center,
            "box": box,
            "available": available and not blocked_visual,
            "value_ratio": value_ratio,
            "sat_ratio": sat_ratio,
        }

    @staticmethod
    def _family_from_skill_name(skill_name):
        return _skill_family(skill_name)

    def _all_a1_entries(self):
        return [
            (priority, entry)
            for priority, entry in enumerate(self.skill_plan)
            if entry[1] == "A1"
        ]

    def _candidate_a1_entries(self):
        entries = self._all_a1_entries()
        if not self.active_family_hints:
            return entries, "database"
        filtered = [
            (priority, entry)
            for priority, entry in entries
            if any(
                _family_matches_hint(_skill_family(entry[0]), hint)
                for hint in self.active_family_hints
            )
        ]
        # Never brick combat because draft tracking missed every family.
        return (filtered, "active-team") if filtered else (entries, "database-hint-miss")

    def _a1_prefilter_variant(self, path, frame):
        base_scale = float(self.vision.template_base_scale(frame))
        key = (path, round(base_scale, 4), round(float(COMBAT_A1_PREFILTER_DOWNSCALE), 4))
        cached = self._a1_prefilter_template_cache.get(key)
        if cached is not None:
            return cached
        template = self._skill_template(path)
        if template is None or template.size == 0:
            return None
        gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        factor = max(0.10, base_scale * float(COMBAT_A1_PREFILTER_DOWNSCALE))
        h, w = gray.shape[:2]
        variant = cv2.resize(
            gray,
            (max(8, int(round(w * factor))), max(8, int(round(h * factor)))),
            interpolation=cv2.INTER_AREA if factor < 1.0 else cv2.INTER_CUBIC,
        )
        variant = cv2.GaussianBlur(variant, (3, 3), 0)
        if len(self._a1_prefilter_template_cache) >= 160:
            self._a1_prefilter_template_cache.clear()
        self._a1_prefilter_template_cache[key] = variant
        return variant

    def _prefilter_a1_entries(self, frame, entries):
        roi = _frame_rel_region(frame, ROI_SKILL_BAR)
        if roi is None or roi.size == 0:
            return entries[:COMBAT_A1_PREFILTER_MAX_EXACT]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        ds = float(COMBAT_A1_PREFILTER_DOWNSCALE)
        small = cv2.resize(
            gray,
            (max(32, int(round(gray.shape[1] * ds))), max(24, int(round(gray.shape[0] * ds)))),
            interpolation=cv2.INTER_AREA,
        )
        small = cv2.GaussianBlur(small, (3, 3), 0)
        scored = []
        for priority, entry in entries:
            path = self._skill_path(entry[0])
            needle = self._a1_prefilter_variant(path, frame)
            score = -1.0
            if needle is not None and needle.shape[0] <= small.shape[0] and needle.shape[1] <= small.shape[1]:
                result = cv2.matchTemplate(small, needle, cv2.TM_CCOEFF_NORMED)
                if result.size:
                    score = float(cv2.minMaxLoc(result)[1])
                    if not np.isfinite(score):
                        score = -1.0
            scored.append((score, priority, entry))
        scored.sort(key=lambda row: row[0], reverse=True)

        selected = []
        used = set()
        # Proven actors are nearly free insurance against an animation-weakened
        # low-res frame.
        for score, priority, entry in scored:
            family = _skill_family(entry[0])
            if family in self._seen_actor_families and family not in used:
                selected.append((priority, entry))
                used.add(family)
                if len(selected) >= COMBAT_A1_PREFILTER_MAX_EXACT:
                    return selected
        for score, priority, entry in scored:
            family = _skill_family(entry[0])
            if family in used:
                continue
            selected.append((priority, entry))
            used.add(family)
            if len(selected) >= COMBAT_A1_PREFILTER_MAX_EXACT:
                break
        return selected

    def _exact_a1_rank(self, frame, rect, entries):
        ranked = []
        for priority, entry in entries:
            name, skill_id, target_mode, attack_type = entry
            direct = self._direct_skill_match(frame, rect, name)
            if direct is None:
                continue
            ranked.append({
                **direct,
                "priority": priority,
                "skill_name": name,
                "skill_id": "A1",
                "target_mode": target_mode,
                "attack_type": attack_type,
                "family": _skill_family(name),
                "path": self._skill_path(name),
                "physical_index": 0,
            })
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    def _fixed_a1_rank(self, frame, rect, entries):
        """Cheap geometry-based A1 identity rescue.

        The passive button stays on the far right of RAID's skill row.  A1 is
        therefore ``active_skill_count * SKILL_BUTTON_GAP_REF`` to its left.
        This handles ordinary 3-skill champions, 2-skill champions such as
        Cruetraxa and 4-skill mythicals with the same code path.
        """
        ranked = []

        for priority, entry in entries:
            name, skill_id, target_mode, attack_type = entry
            family = _skill_family(name)
            count = max(1, int(self._active_skill_count_by_family.get(family, 3)))

            cx_ref = A1_PASSIVE_CENTER_X_REF - (count * SKILL_BUTTON_GAP_REF)
            cy_ref = A1_SKILL_ROW_Y_REF
            half = A1_FIXED_HALF_REF

            region = _rel_region(
                rect,
                cx_ref - half,
                cy_ref - half,
                cx_ref + half,
                cy_ref + half,
            )
            crop = _crop_abs(frame, rect, region)
            template = self._skill_template(self._skill_path(name))

            if crop is None or crop.size == 0 or template is None or template.size == 0:
                continue

            score = float(self._icon_similarity(crop, template))
            center = _rel_point(rect, cx_ref, cy_ref)
            left, top, _, _ = rect
            rx, ry, rw, rh = region

            ranked.append({
                "cooldown_fraction": 0.0,
                "blocked_visual": False,
                "score": score,
                "center": center,
                "box": (
                    int(rx - left),
                    int(ry - top),
                    int(rw),
                    int(rh),
                ),
                "available": True,
                "value_ratio": 1.0,
                "sat_ratio": 1.0,
                "priority": priority,
                "skill_name": name,
                "skill_id": skill_id,
                "target_mode": target_mode,
                "attack_type": attack_type,
                "family": family,
                "path": self._skill_path(name),
                "physical_index": 0,
                "identity_mode": "fixed-a1-fallback",
            })

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    @staticmethod
    def _best_fixed_by_root(ranked):
        """Collapse f1/f2 siblings into one champion-root score.

        Returns:
            best_item,
            best_root,
            root_margin,
            forms_in_best_root,
            root_scores
        """
        if not ranked:
            return None, None, 0.0, 0, []

        by_root = {}
        counts = {}
        for item in ranked:
            root = _family_root(item.get("family"))
            if not root:
                continue
            counts[root] = counts.get(root, 0) + 1
            score = float(item.get("score", 0.0))
            current = by_root.get(root)
            if current is None or score > float(current.get("score", 0.0)):
                by_root[root] = item

        ordered = sorted(
            by_root.items(),
            key=lambda pair: float(pair[1].get("score", 0.0)),
            reverse=True,
        )
        if not ordered:
            return None, None, 0.0, 0, []

        best_root, best_item = ordered[0]
        second_root_score = (
            float(ordered[1][1].get("score", 0.0))
            if len(ordered) > 1
            else 0.0
        )
        root_margin = float(best_item.get("score", 0.0)) - second_root_score
        root_scores = [
            (root, float(item.get("score", 0.0)))
            for root, item in ordered
        ]
        return (
            best_item,
            best_root,
            root_margin,
            int(counts.get(best_root, 0)),
            root_scores,
        )

    def _multi_skill_fingerprint_identity(self, frame, rect, entries):
        """Resolve an ambiguous actor from the real physical skill-button cluster.

        This path is intentionally a RESCUE, not the common path:
          - detect the 3/4/5-button cluster once,
          - discard families whose active-skill count cannot fit that cluster,
          - compare A1/A2/A3/A4 at their physical slots,
          - rank champion ROOTS first, then mythical forms.

        It is much cheaper than repeatedly running full-ROI exact A1 searches and
        is safer than globally lowering the A1 threshold.
        """
        geometry = self.geometry(rect)
        physical_slots = self.detect_skill_slots(frame, rect, geometry)
        slot_count = len(physical_slots)
        if slot_count < MULTI_SKILL_FINGERPRINT_MIN_SKILLS:
            return None

        candidate_families = []
        for _, entry in entries:
            family = _skill_family(entry[0])
            if family not in candidate_families:
                candidate_families.append(family)

        family_rows = []
        for family in candidate_families:
            family_entries = [
                (priority, entry)
                for priority, entry in enumerate(self.skill_plan)
                if _skill_family(entry[0]) == family
                and _expected_physical_index(entry[1]) is not None
            ]
            family_entries.sort(
                key=lambda row: _expected_physical_index(row[1][1])
            )

            active_count = len({
                entry[1]
                for _, entry in family_entries
            })
            if active_count < MULTI_SKILL_FINGERPRINT_MIN_SKILLS:
                continue

            # Normal champions commonly expose A1..A3 + passive (4 circles);
            # mythicals expose A1..A4 + passive (5).  Champions without a
            # passive may expose exactly active_count circles.
            if not (active_count <= slot_count <= active_count + 1):
                continue

            skill_scores = {}
            weighted = []
            a1_entry = None
            a1_crop_slot = None

            for priority, entry in family_entries:
                name, skill_id, _, attack_type = entry
                index = _expected_physical_index(skill_id)
                if index is None or index >= slot_count:
                    continue

                slot = physical_slots[index]
                crop = self._slot_crop(frame, rect, slot)
                if crop is None or crop.size == 0:
                    continue

                template_candidates = []
                path = self._skill_path(name)
                template = self._skill_template(path)
                if template is not None:
                    template_candidates.append(template)

                if attack_type == "transform":
                    generic = self._skill_template(
                        self._skill_path("skill_mythical_transform_a4")
                    )
                    if generic is not None:
                        template_candidates.append(generic)

                if not template_candidates:
                    continue

                score = max(
                    float(self._icon_similarity(crop, tmpl))
                    for tmpl in template_candidates
                )
                skill_scores[skill_id] = score
                weighted.append(score)

                if skill_id == "A1":
                    a1_entry = (priority, entry)
                    a1_crop_slot = slot

            if (
                a1_entry is None
                or a1_crop_slot is None
                or len(weighted) < MULTI_SKILL_FINGERPRINT_MIN_SKILLS
            ):
                continue

            aggregate = float(sum(weighted) / len(weighted))
            family_rows.append({
                "family": family,
                "root": _family_root(family),
                "score": aggregate,
                "skill_scores": skill_scores,
                "a1_entry": a1_entry,
                "a1_slot": a1_crop_slot,
                "slot_count": slot_count,
                "active_count": active_count,
            })

        if not family_rows:
            return None

        family_rows.sort(key=lambda row: row["score"], reverse=True)
        best = family_rows[0]

        # Rank roots independently so f1/f2 do not penalise the champion root.
        root_best = {}
        for row in family_rows:
            current = root_best.get(row["root"])
            if current is None or row["score"] > current["score"]:
                root_best[row["root"]] = row

        roots = sorted(
            root_best.values(),
            key=lambda row: row["score"],
            reverse=True,
        )
        if not roots:
            return None

        best_root_row = roots[0]
        second_root_score = roots[1]["score"] if len(roots) > 1 else 0.0
        root_margin = float(best_root_row["score"] - second_root_score)

        if best_root_row["score"] < MULTI_SKILL_FINGERPRINT_SCORE_MIN:
            return None
        if root_margin < MULTI_SKILL_FINGERPRINT_ROOT_MARGIN_MIN:
            return None

        same_root = sorted(
            [
                row for row in family_rows
                if row["root"] == best_root_row["root"]
            ],
            key=lambda row: row["score"],
            reverse=True,
        )
        chosen = same_root[0]
        form_margin = (
            chosen["score"] - same_root[1]["score"]
            if len(same_root) > 1
            else 1.0
        )
        if (
            len(same_root) > 1
            and form_margin < MULTI_SKILL_FINGERPRINT_FORM_MARGIN_MIN
        ):
            return None

        priority, a1_entry = chosen["a1_entry"]
        name, skill_id, target_mode, attack_type = a1_entry
        slot = chosen["a1_slot"]
        center = slot["center"]
        radius = max(24, int(slot["radius"]))
        half = int(radius * 0.92)
        left, top, _, _ = rect

        a1_score = float(chosen["skill_scores"].get("A1", chosen["score"]))
        a1_item = {
            "cooldown_fraction": 0.0,
            "blocked_visual": False,
            "score": a1_score,
            "identity_score": float(chosen["score"]),
            "center": center,
            "box": (
                int(center[0] - left - half),
                int(center[1] - top - half),
                int(half * 2),
                int(half * 2),
            ),
            "available": True,
            "value_ratio": 1.0,
            "sat_ratio": 1.0,
            "priority": priority,
            "skill_name": name,
            "skill_id": skill_id,
            "target_mode": target_mode,
            "attack_type": attack_type,
            "family": chosen["family"],
            "path": self._skill_path(name),
            "physical_index": 0,
            "identity_mode": "multi-skill-fingerprint",
            "fingerprint_scores": dict(chosen["skill_scores"]),
            "fingerprint_root_margin": root_margin,
            "fingerprint_form_margin": float(form_margin),
            "fingerprint_slot_count": slot_count,
        }

        ranked = []
        for row in family_rows:
            item = dict(a1_item if row is chosen else {})
            item.update({
                "family": row["family"],
                "score": float(row["score"]),
                "identity_score": float(row["score"]),
                "skill_scores": dict(row["skill_scores"]),
                "identity_mode": "multi-skill-fingerprint-rank",
            })
            ranked.append(item)

        log_key = ("fingerprint", chosen["family"])
        if log_key not in self._fixed_a1_fallback_logged:
            self._fixed_a1_fallback_logged.add(log_key)
            print(
                "SKILL FINGERPRINT -> "
                f"family={chosen['family']} "
                f"score={chosen['score']:.3f} "
                f"root_margin={root_margin:.3f} "
                f"form_margin={form_margin:.3f} "
                f"slots={slot_count} "
                f"skills={chosen['skill_scores']}"
            )

        return (
            chosen["family"],
            float(chosen["score"]),
            root_margin,
            a1_item,
            ranked,
            physical_slots,
        )

    def _fixed_multi_skill_identity(self, frame, rect, entries):
        """Fallback actor identity from fixed physical skill-button geometry.

        Unlike ``_multi_skill_fingerprint_identity`` this rescue does not depend
        on Hough-circle detection.  It is used only after the normal A1 and
        physical-cluster paths are ambiguous, and only against families present
        in the active-team candidate set.

        Safety gates:
          * A1 itself must still have a meaningful match,
          * at least one additional active skill must match strongly,
          * the multi-skill aggregate must beat the next champion root.
        """
        candidate_families = []
        for _, entry in entries:
            family = _skill_family(entry[0])
            if family and family not in candidate_families:
                candidate_families.append(family)

        rows = []
        left, top, _, _ = rect

        for family in candidate_families:
            active_count = max(
                1,
                int(self._active_skill_count_by_family.get(family, 3)),
            )
            a1_x_ref = A1_PASSIVE_CENTER_X_REF - (
                active_count * SKILL_BUTTON_GAP_REF
            )

            scores = {}
            a1_entry = None
            a1_center = None
            a1_box = None

            family_entries = [
                (priority, entry)
                for priority, entry in enumerate(self.skill_plan)
                if _skill_family(entry[0]) == family
                and _expected_physical_index(entry[1]) is not None
            ]

            for priority, entry in family_entries:
                name, skill_id, target_mode, attack_type = entry
                index = _expected_physical_index(skill_id)
                if index is None:
                    continue

                cx_ref = a1_x_ref + index * SKILL_BUTTON_GAP_REF
                cy_ref = A1_SKILL_ROW_Y_REF
                center = _rel_point(rect, cx_ref, cy_ref)
                crop, box = self._crop_skill_at_screen_center(
                    frame,
                    rect,
                    center,
                )
                if crop is None or crop.size == 0:
                    continue

                template_candidates = []
                path = self._skill_path(name)
                template = self._skill_template(path)
                if template is not None:
                    template_candidates.append(template)

                if attack_type == "transform":
                    generic = self._skill_template(
                        self._skill_path("skill_mythical_transform_a4")
                    )
                    if generic is not None:
                        template_candidates.append(generic)

                if not template_candidates:
                    continue

                score = max(
                    float(self._icon_similarity(crop, tmpl))
                    for tmpl in template_candidates
                )
                scores[skill_id] = score

                if skill_id == "A1":
                    a1_entry = (priority, entry)
                    a1_center = center
                    a1_box = box

            if (
                a1_entry is None
                or a1_center is None
                or len(scores) < FIXED_MULTI_SKILL_MIN_SKILLS
            ):
                continue

            a1_score = float(scores.get("A1", 0.0))
            secondary_scores = [
                float(v) for k, v in scores.items() if k != "A1"
            ]
            best_secondary = max(secondary_scores) if secondary_scores else 0.0

            if (
                a1_score < FIXED_MULTI_SKILL_A1_MIN
                or best_secondary < FIXED_MULTI_SKILL_SECONDARY_MIN
            ):
                continue

            # Give A1 slightly more weight because it remains the identity anchor.
            # The rest of the buttons provide independent coherence evidence.
            aggregate = (
                1.35 * a1_score
                + sum(float(v) for k, v in scores.items() if k != "A1")
            ) / (1.35 + max(0, len(scores) - 1))

            rows.append({
                "family": family,
                "root": _family_root(family),
                "score": float(aggregate),
                "a1_score": a1_score,
                "best_secondary": best_secondary,
                "skill_scores": dict(scores),
                "a1_entry": a1_entry,
                "a1_center": a1_center,
                "a1_box": a1_box,
            })

        if not rows:
            return None

        # Compete by champion root so f1/f2 siblings do not destroy the margin.
        root_best = {}
        for row in rows:
            current = root_best.get(row["root"])
            if current is None or row["score"] > current["score"]:
                root_best[row["root"]] = row

        root_rows = sorted(
            root_best.values(),
            key=lambda row: row["score"],
            reverse=True,
        )
        best_root_row = root_rows[0]
        second_root_score = (
            float(root_rows[1]["score"]) if len(root_rows) > 1 else 0.0
        )
        root_margin = float(best_root_row["score"]) - second_root_score

        if (
            float(best_root_row["score"]) < FIXED_MULTI_SKILL_SCORE_MIN
            or root_margin < FIXED_MULTI_SKILL_ROOT_MARGIN_MIN
        ):
            return None

        # If this is a mythical root, choose the better visible form within it.
        same_root = sorted(
            [r for r in rows if r["root"] == best_root_row["root"]],
            key=lambda row: row["score"],
            reverse=True,
        )
        chosen = same_root[0]
        if len(same_root) > 1:
            form_margin = float(same_root[0]["score"]) - float(same_root[1]["score"])
            if form_margin < MULTI_SKILL_FINGERPRINT_FORM_MARGIN_MIN:
                return None
        else:
            form_margin = 1.0

        priority, a1_entry = chosen["a1_entry"]
        name, skill_id, target_mode, attack_type = a1_entry
        a1_item = {
            "cooldown_fraction": 0.0,
            "blocked_visual": False,
            "score": float(chosen["a1_score"]),
            "identity_score": float(chosen["score"]),
            "center": chosen["a1_center"],
            "box": chosen["a1_box"],
            "available": True,
            "value_ratio": 1.0,
            "sat_ratio": 1.0,
            "priority": priority,
            "skill_name": name,
            "skill_id": skill_id,
            "target_mode": target_mode,
            "attack_type": attack_type,
            "family": chosen["family"],
            "path": self._skill_path(name),
            "physical_index": 0,
            "identity_mode": "fixed-multi-skill-fingerprint",
            "fingerprint_scores": dict(chosen["skill_scores"]),
            "fingerprint_root_margin": float(root_margin),
            "fingerprint_form_margin": float(form_margin),
        }

        ranked = []
        for row in sorted(rows, key=lambda r: r["score"], reverse=True):
            ranked.append({
                "family": row["family"],
                "score": float(row["score"]),
                "identity_score": float(row["score"]),
                "skill_scores": dict(row["skill_scores"]),
                "identity_mode": "fixed-multi-skill-fingerprint-rank",
            })

        log_key = ("fixed-fingerprint", chosen["family"])
        if log_key not in self._fixed_a1_fallback_logged:
            self._fixed_a1_fallback_logged.add(log_key)
            print(
                "FIXED SKILL FINGERPRINT -> "
                f"family={chosen['family']} "
                f"score={chosen['score']:.3f} "
                f"root_margin={root_margin:.3f} "
                f"form_margin={form_margin:.3f} "
                f"skills={chosen['skill_scores']}"
            )

        return (
            chosen["family"],
            float(chosen["score"]),
            float(root_margin),
            a1_item,
            ranked,
        )

    def _identify_actor_a1(self, frame, rect):
        """Identify actor from A1 with bounded cost for a large champion DB.

        V15.13 first checks the tiny physical A1 button crop.  A strong fixed-slot
        result is both cheaper and, on the supplied replays, more stable than a
        full-ROI search during animation.  Only ambiguous fixed results fall back
        to the exact/prefilter path.
        """
        entries, scope = self._candidate_a1_entries()
        if not entries:
            return None, 0.0, 0.0, None, []

        # Cheap first pass: one tiny crop per active-team family.
        fixed_ranked = self._fixed_a1_rank(frame, rect, entries)
        if fixed_ranked:
            fixed_best = fixed_ranked[0]
            fixed_second = (
                float(fixed_ranked[1]["score"])
                if len(fixed_ranked) > 1
                else 0.0
            )
            fixed_margin = float(fixed_best["score"]) - fixed_second

            if (
                float(fixed_best["score"]) >= A1_FIXED_FAST_SCORE_MIN
                and fixed_margin >= A1_FIXED_FAST_MARGIN_MIN
            ):
                family = fixed_best["family"]
                fixed_best = dict(fixed_best)
                fixed_best["identity_mode"] = "fixed-a1-fast"
                fixed_ranked[0] = fixed_best
                self._seen_actor_families.add(family)
                for item in fixed_ranked:
                    item["identity_scope"] = scope
                return (
                    family,
                    float(fixed_best["score"]),
                    fixed_margin,
                    fixed_best,
                    fixed_ranked,
                )

            # V15.15: for mythical champions, f1/f2 are sibling forms of one
            # champion, not two independent opponents in the identity margin.
            (
                root_best,
                root_name,
                root_margin,
                root_form_count,
                root_scores,
            ) = self._best_fixed_by_root(fixed_ranked)

            if (
                root_best is not None
                and root_form_count >= 2
                and float(root_best["score"]) >= A1_FIXED_MYTHICAL_ROOT_SCORE_MIN
                and root_margin >= A1_FIXED_MYTHICAL_ROOT_MARGIN_MIN
            ):
                family = root_best["family"]  # keep the visible form, e.g. komidus_f1
                root_best = dict(root_best)
                root_best["identity_mode"] = "fixed-a1-mythical-root"
                root_best["root_margin"] = float(root_margin)
                root_best["root_scores"] = tuple(root_scores)

                # Replace matching list item so downstream diagnostics preserve
                # the new identity mode without changing the rest of the rank.
                for i, item in enumerate(fixed_ranked):
                    if (
                        item.get("family") == family
                        and abs(float(item.get("score", 0.0)) - float(root_best["score"])) < 1e-9
                    ):
                        fixed_ranked[i] = root_best
                        break

                self._seen_actor_families.add(family)
                log_key = ("mythical-root", family)
                if log_key not in self._fixed_a1_fallback_logged:
                    self._fixed_a1_fallback_logged.add(log_key)
                    print(
                        "A1 MYTHICAL ROOT -> "
                        f"family={family} root={root_name} "
                        f"score={float(root_best['score']):.3f} "
                        f"root_margin={root_margin:.3f}"
                    )

                for item in fixed_ranked:
                    item["identity_scope"] = scope

                return (
                    family,
                    float(root_best["score"]),
                    float(root_margin),
                    root_best,
                    fixed_ranked,
                )

        # V15.16: before paying for full-ROI exact searches, use all visible
        # physical skill buttons as a fingerprint.  This is the path that fixes
        # the Komidus turn from the supplied 20:39 replay.
        fingerprint = self._multi_skill_fingerprint_identity(
            frame,
            rect,
            entries,
        )
        if fingerprint is not None:
            (
                family,
                fingerprint_score,
                fingerprint_margin,
                fingerprint_a1,
                fingerprint_ranked,
                _physical_slots,
            ) = fingerprint
            self._seen_actor_families.add(family)
            for item in fingerprint_ranked:
                item["identity_scope"] = scope
            return (
                family,
                fingerprint_score,
                fingerprint_margin,
                fingerprint_a1,
                fingerprint_ranked,
            )

        # V15.23: Tekteon and a few Champion-Skills source crops can be too weak
        # for a single-A1 decision while the skill row itself is visually coherent.
        # Use fixed geometry as a second multi-skill rescue before the expensive
        # exact full-ROI path.
        # V15.24: keep the fixed-geometry rescue strictly local to Tekteon.
        # The previous global call could alter actor identification for champions
        # that were already stable (for example Fabian).  Only Tekteon needs this
        # extra rescue path; every other family keeps the established A1 / Hough
        # fingerprint behaviour unchanged.
        tekteon_entries = [
            row for row in entries
            if _family_root(_skill_family(row[1][0])) == "tekteon"
        ]
        fixed_fingerprint = (
            self._fixed_multi_skill_identity(frame, rect, tekteon_entries)
            if tekteon_entries
            else None
        )
        if fixed_fingerprint is not None:
            (
                family,
                fingerprint_score,
                fingerprint_margin,
                fingerprint_a1,
                fingerprint_ranked,
            ) = fixed_fingerprint
            self._seen_actor_families.add(family)
            for item in fingerprint_ranked:
                item["identity_scope"] = scope
            return (
                family,
                fingerprint_score,
                fingerprint_margin,
                fingerprint_a1,
                fingerprint_ranked,
            )

        # Ambiguous fixed crop -> bounded exact path.
        if len(entries) <= COMBAT_A1_EXACT_SCAN_LIMIT:
            ranked = self._exact_a1_rank(frame, rect, entries)
        else:
            shortlist = self._prefilter_a1_entries(frame, entries)
            initial = shortlist[:max(1, COMBAT_A1_PREFILTER_TOP_K)]
            ranked = self._exact_a1_rank(frame, rect, initial)
            best_score = float(ranked[0]["score"]) if ranked else 0.0
            second = float(ranked[1]["score"]) if len(ranked) > 1 else 0.0
            if (
                len(shortlist) > len(initial)
                and (
                    best_score < COMBAT_A1_PREFILTER_RESCUE_SCORE
                    or best_score - second < COMBAT_A1_PREFILTER_RESCUE_MARGIN
                )
            ):
                ranked.extend(self._exact_a1_rank(
                    frame,
                    rect,
                    shortlist[len(initial):COMBAT_A1_PREFILTER_MAX_EXACT],
                ))
                ranked.sort(key=lambda item: item["score"], reverse=True)

        if ranked:
            best = ranked[0]
            second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
            margin = float(best["score"]) - float(second_score)
            if (
                float(best["score"]) >= ACTOR_A1_SCORE_MIN
                and margin >= ACTOR_A1_MARGIN_MIN
            ):
                family = best["family"]
                self._seen_actor_families.add(family)
                for item in ranked:
                    item["identity_scope"] = scope
                return family, float(best["score"]), margin, best, ranked
        else:
            best = None
            margin = 0.0

        # Reuse the already computed fixed rank as the softer rescue.
        if fixed_ranked:
            fixed_best = fixed_ranked[0]
            fixed_second = (
                float(fixed_ranked[1]["score"])
                if len(fixed_ranked) > 1
                else 0.0
            )
            fixed_margin = float(fixed_best["score"]) - fixed_second
            if (
                float(fixed_best["score"]) >= A1_FIXED_FALLBACK_SCORE_MIN
                and fixed_margin >= A1_FIXED_FALLBACK_MARGIN_MIN
            ):
                family = fixed_best["family"]
                fixed_best = dict(fixed_best)
                fixed_best["identity_mode"] = "fixed-a1-fallback"
                fixed_ranked[0] = fixed_best
                self._seen_actor_families.add(family)
                if family not in self._fixed_a1_fallback_logged:
                    self._fixed_a1_fallback_logged.add(family)
                    print(
                        "A1 FIXED FALLBACK -> "
                        f"family={family} "
                        f"score={float(fixed_best['score']):.3f} "
                        f"margin={fixed_margin:.3f}"
                    )
                for item in fixed_ranked:
                    item["identity_scope"] = scope
                return (
                    family,
                    float(fixed_best["score"]),
                    fixed_margin,
                    fixed_best,
                    fixed_ranked,
                )

        final_ranked = ranked or fixed_ranked or []
        if final_ranked:
            best = final_ranked[0]
            second = (
                float(final_ranked[1]["score"])
                if len(final_ranked) > 1
                else 0.0
            )
            margin = float(best["score"]) - second
            score = float(best["score"])
        else:
            best = None
            margin = 0.0
            score = 0.0

        for item in final_ranked:
            item["identity_scope"] = scope
        return None, score, margin, best, final_ranked

    def _crop_skill_at_screen_center(self, frame, rect, center):
        left, top, width, height = rect
        scale = ((width / 1024.0) + (height / 769.0)) * 0.5
        half = max(30, round(SKILL_BUTTON_HALF_REF * scale))

        cx = int(center[0] - left)
        cy = int(center[1] - top)

        x1 = max(0, cx - half)
        y1 = max(0, cy - half)
        x2 = min(frame.shape[1], cx + half)
        y2 = min(frame.shape[0], cy + half)

        if x2 <= x1 or y2 <= y1:
            return None, (x1, y1, max(1, x2 - x1), max(1, y2 - y1))

        return frame[y1:y2, x1:x2], (x1, y1, x2 - x1, y2 - y1)

    def _anchored_skill_item(
        self,
        frame,
        rect,
        entry,
        priority,
        a1_center,
    ):
        name, skill_id, target_mode, attack_type = entry
        index = _expected_physical_index(skill_id)

        if index is None:
            return None

        scale = rect[2] / 1024.0
        gap = round(SKILL_BUTTON_GAP_REF * scale)

        center = (
            int(a1_center[0] + index * gap),
            int(a1_center[1]),
        )

        crop, box = self._crop_skill_at_screen_center(
            frame,
            rect,
            center,
        )
        if crop is None or crop.size == 0:
            return None

        path = self._skill_path(name)
        template = self._skill_template(path)

        # V15.14 mythical transform:
        # Champion Skills source art and the real combat metamorph button are not
        # always pixel-identical.  Compare the expected family A4 AND the generic
        # metamorph reference, then use whichever actually matches this button.
        template_candidates = []
        if template is not None:
            template_candidates.append((path, template))

        if attack_type == "transform":
            generic_path = self._skill_path("skill_mythical_transform_a4")
            generic_template = self._skill_template(generic_path)
            if generic_template is not None and generic_path != path:
                template_candidates.append((generic_path, generic_template))

        if not template_candidates:
            return None

        scored_templates = [
            (float(self._icon_similarity(crop, candidate)), candidate_path, candidate)
            for candidate_path, candidate in template_candidates
        ]
        score, matched_template_path, matched_template = max(
            scored_templates,
            key=lambda item: item[0],
        )

        available_raw, value_ratio, sat_ratio = _availability_against_template(
            crop,
            matched_template,
        )
        cooldown_fraction = _cooldown_overlay_fraction(
            crop,
            matched_template,
        )

        blocked_visual = (
            cooldown_fraction >= COOLDOWN_OVERLAY_STRONG
            or (
                cooldown_fraction >= COOLDOWN_OVERLAY_WEAK
                and value_ratio <= COOLDOWN_VALUE_RATIO_MAX
            )
        )

        local_min_score = (
            TRANSFORM_ANCHORED_SCORE_MIN
            if attack_type == "transform"
            else ANCHORED_SKILL_SCORE_MIN
        )

        # V15.25 evidence aggregation.  At this point the actor has already been
        # identified by A1 and the physical button slot is deterministic.  A weak
        # source-art correlation therefore should not be the only reason to call a
        # READY skill unknown.  The rescue is conservative: it requires a minimum
        # raw template correlation, normal brightness/saturation and NO confirmed
        # cooldown overlay.
        def _clip01(value):
            return max(0.0, min(1.0, float(value)))

        appearance_score = 0.5 * (
            _clip01(value_ratio) + _clip01(sat_ratio)
        )
        geometry_score = 1.0  # crop exists at the family-anchored physical slot
        combined_score = (
            SKILL_EVIDENCE_TEMPLATE_WEIGHT * _clip01(score)
            + SKILL_EVIDENCE_APPEARANCE_WEIGHT * appearance_score
            + SKILL_EVIDENCE_GEOMETRY_WEIGHT * geometry_score
        )
        evidence_rescue = (
            not blocked_visual
            and available_raw
            and float(score) >= float(SKILL_EVIDENCE_RESCUE_RAW_MIN)
            and combined_score >= float(local_min_score)
        )

        # Fabian A3 local guard.  Fabian is already positively identified from
        # A1 and A3 has a deterministic physical slot.  In real battle frames
        # the A3 artwork can differ enough from the source crop that the generic
        # cooldown/template test falsely marks a READY A3 as unavailable.
        #
        # Keep this correction strictly local to Fabian A3.  We only call A3
        # cooldown-confirmed when the dark overlay is strong AND the normal
        # availability test also disagrees with the clean art, or when the dark
        # overlay is extremely strong by itself.  This prevents weak artwork
        # mismatch from making Fabian fall through to A2/A1.
        family = _skill_family(name)
        is_fabian_a3 = (family == "fabian" and skill_id == "A3")
        if is_fabian_a3:
            fabian_a3_cooldown_confirmed = (
                cooldown_fraction >= 0.55
                or (
                    cooldown_fraction >= COOLDOWN_OVERLAY_STRONG
                    and not available_raw
                    and value_ratio <= COOLDOWN_VALUE_RATIO_MAX
                )
            )
            blocked_visual = bool(fabian_a3_cooldown_confirmed)

        anchored_ready_override = (
            is_fabian_a3
            and not blocked_visual
        )

        # The physical button position is already anchored from A1.  Transform
        # gets its own local threshold; form2 priorities still omit A4 where the
        # user explicitly said never to return to form1.
        if blocked_visual:
            availability = "unavailable"
        elif anchored_ready_override:
            availability = "available"
        elif (score >= local_min_score or evidence_rescue) and available_raw:
            availability = "available"
        elif score >= local_min_score and not available_raw:
            availability = "unavailable"
        else:
            availability = "unknown"

        # CombatDecisionTree also has a generic min_score gate.  For Fabian A3
        # that gate must not undo the local anchored-ready decision: actor identity
        # and physical slot are already known, so template score is not identity
        # evidence here.  Preserve raw_score for diagnostics and floor only the
        # score seen by the tree.
        raw_score = float(score)
        if anchored_ready_override:
            decision_score = max(raw_score, float(SKILL_MATCH_MIN))
        elif evidence_rescue:
            decision_score = max(raw_score, float(combined_score))
        else:
            decision_score = raw_score

        return {
            "priority": priority,
            "skill_name": name,
            "skill_id": skill_id,
            "target_mode": target_mode,
            "attack_type": attack_type,
            "family": _skill_family(name),
            "path": path,
            "matched_template_path": matched_template_path,
            "score": float(decision_score),
            "raw_score": float(raw_score),
            "combined_score": float(combined_score),
            "appearance_score": float(appearance_score),
            "evidence_rescue": bool(evidence_rescue),
            "center": center,
            "box": box,
            "available": availability == "available",
            "availability": availability,
            "value_ratio": float(value_ratio),
            "sat_ratio": float(sat_ratio),
            "cooldown_fraction": float(cooldown_fraction),
            "blocked_visual": bool(blocked_visual),
            "physical_index": index,
        }

    def _entries_for_root(self, root):
        root = _family_root(root)
        entries, _ = self._candidate_a1_entries()
        return [
            (priority, entry)
            for priority, entry in entries
            if _family_root(_skill_family(entry[0])) == root
        ]

    def _root_limited_identity(self, frame, rect, root, *, allow_inferred=False):
        """Identify one known champion root, allowing mythical form changes.

        When the ally slot was already bound to this champion root we do not need
        an all-team margin test again.  For a mythical root we still compare both
        forms and choose the visible form.
        """
        entries = self._entries_for_root(root)
        if not entries:
            return None, 0.0, 0.0, None, []

        exact = self._exact_a1_rank(frame, rect, entries)
        fixed = self._fixed_a1_rank(frame, rect, entries)

        ranked = exact if exact else fixed
        if fixed and (not ranked or fixed[0]["score"] > ranked[0]["score"]):
            ranked = fixed

        if not ranked:
            return None, 0.0, 0.0, None, []

        best = ranked[0]
        second_score = float(ranked[1]["score"]) if len(ranked) > 1 else 0.0
        margin = float(best["score"]) - second_score

        # V15.20: slot memory is only a candidate limiter, never proof of identity.
        # The old 0.22/0.30 thresholds were low enough for stale Fabian memory to
        # survive on another champion's turn.  Require a real visual match; on
        # failure scan_skill_slots() falls back to the normal all-team identity path.
        min_score = (
            SLOT_INFERENCE_VISUAL_SCORE_MIN
            if allow_inferred
            else max(SLOT_MEMORY_VISUAL_SCORE_MIN, SKILL_FAMILY_MEMORY_MIN)
        )
        min_margin = 0.035 if len(ranked) > 1 else 0.0

        if float(best["score"]) < min_score or margin < min_margin:
            return None, float(best["score"]), margin, best, ranked

        best = dict(best)
        best["identity_mode"] = (
            "slot-roster-inference" if allow_inferred else "slot-family-memory"
        )
        return best["family"], float(best["score"]), margin, best, ranked

    def _unseen_active_roots(self, slot_family_memory):
        """Return active-team champion roots that are not bound to a physical ally slot yet.

        V15.16 KOMIDUS FIX:
        ``_seen_actor_families`` is a visual-recognition cache, not a slot-binding
        cache.  A champion can be recognised during the post-action transition
        before ``detect_active_ally_slot()`` has stabilised.  Treating that visual
        sighting as an already-bound actor removes the real champion from the
        unseen set and can make the last *other* champion look like the only
        possible slot inference.

        This is exactly what happened in the supplied Komidus replay:
          fingerprint -> komidus_f1 (~0.600)
          visual cache marks Komidus as seen
          unique-roster inference -> Vestele (~0.409)
          decision tree then waits on Vestele A2 and never presses Komidus A4.

        Only confirmed physical slot bindings are safe evidence for this
        elimination step.  ``_seen_actor_families`` remains useful for the A1
        prefilter, but it must not participate here.
        """
        hints = {
            _family_root(x)
            for x in self.active_family_hints
            if _family_root(x)
        }
        bound = {
            _family_root(x)
            for x in (slot_family_memory or {}).values()
            if _family_root(x)
        }
        return sorted(hints - bound)

    def scan_skill_slots(
        self,
        frame,
        rect,
        geometry,
        active_slot=None,
        slot_family_memory=None,
        identity_only=False,
    ):
        """V13.4: A1 identifies actor; A2/A3 come from physical button order.

        This removes the failure mode visible in the supplied recording where
        low ~0.36-0.39 correlations from unrelated skills beat the real actor,
        producing family=None or even the wrong family.
        """
        slot_family_memory = slot_family_memory if slot_family_memory is not None else {}

        # V15.13 MEMORY-FIRST:
        # The previous V15.12 code always paid for a full all-team A1 scan first
        # and consulted slot memory only after that scan failed.  That defeated
        # the purpose of slot memory and made every repeated turn unnecessarily
        # expensive.  Known slots now compare only their champion root first.
        family = None
        confidence = 0.0
        margin = 0.0
        a1_best = None
        ranked = []

        if active_slot is not None:
            remembered = slot_family_memory.get(active_slot)
            if remembered:
                (
                    family,
                    confidence,
                    margin,
                    a1_best,
                    ranked,
                ) = self._root_limited_identity(
                    frame,
                    rect,
                    _family_root(remembered),
                    allow_inferred=False,
                )
            else:
                unseen = self._unseen_active_roots(slot_family_memory)
                if len(unseen) == 1:
                    (
                        family,
                        confidence,
                        margin,
                        a1_best,
                        ranked,
                    ) = self._root_limited_identity(
                        frame,
                        rect,
                        unseen[0],
                        allow_inferred=True,
                    )

        # First appearance of an unknown slot (or a failed local check) still gets
        # the normal bounded active-team identity path.
        if family is None:
            (
                family,
                confidence,
                margin,
                a1_best,
                ranked,
            ) = self._identify_actor_a1(frame, rect)

        if family is not None and active_slot is not None:
            old_family = slot_family_memory.get(active_slot)
            # Same champion can legitimately change mythical form in this slot.
            if (
                old_family is None
                or _family_root(old_family) == _family_root(family)
            ):
                slot_family_memory[active_slot] = family
                self._seen_actor_families.add(family)
                log_key = (active_slot, family)
                if log_key not in self._slot_identity_logged:
                    self._slot_identity_logged.add(log_key)
                    print(
                        "ACTOR SLOT BIND -> "
                        f"slot={active_slot} family={family} "
                        f"mode={a1_best.get('identity_mode', 'a1') if a1_best else 'a1'} "
                        f"score={float(confidence):.3f}"
                    )

        family_results = [
            {
                "family": item["family"],
                "a1": round(float(item["score"]), 4),
            }
            for item in ranked
        ]

        if family is None or a1_best is None:
            return {
                "physical_slots": [],
                "matches": [],
                "selected_family": None,
                "family_confidence": confidence,
                "family_margin": margin,
                "family_results": family_results,
                "recognition_mode": "a1-anchor",
            }

        # The recognised A1 itself is always available for the chosen actor.
        a1_item = dict(a1_best)
        a1_item["availability"] = "available"
        a1_item["available"] = True
        a1_item["cooldown_fraction"] = 0.0
        a1_item["blocked_visual"] = False

        matches = [a1_item]

        if not identity_only:
            for priority, entry in enumerate(self.skill_plan):
                name, skill_id, _, _ = entry

                if skill_id == "A1":
                    continue
                if _skill_family(name) != family:
                    continue

                item = self._anchored_skill_item(
                    frame,
                    rect,
                    entry,
                    priority,
                    a1_item["center"],
                )
                if item is not None:
                    matches.append(item)

        return {
            "physical_slots": [],
            "matches": matches,
            "selected_family": family,
            "family_confidence": confidence,
            "family_margin": margin,
            "family_results": family_results,
            "recognition_mode": (
                a1_best.get("identity_mode", "a1-anchor-physical-skills")
                if a1_best is not None
                else "a1-anchor-physical-skills"
            ),
        }

    def fast_actor_family(self, frame, rect):
        family, best, margin, _, _ = self._identify_actor_a1(
            frame,
            rect,
        )
        return family, best, margin

    def fast_actor_family_for_root(self, frame, rect, family):
        """Cheap form-aware probe limited to one already known champion root."""
        root = _family_root(family)
        identified, score, margin, _, _ = self._root_limited_identity(
            frame,
            rect,
            root,
            allow_inferred=False,
        )
        return identified, score, margin

    def local_skill_state(self, frame, rect, skill):
        """Inspect only the already-known physical skill button.

        Used after a click to observe cooldown without re-running actor identity.
        """
        if frame is None or not skill or skill.get("center") is None:
            return None
        crop, box = self._crop_skill_at_screen_center(
            frame,
            rect,
            skill["center"],
        )
        if crop is None or crop.size == 0:
            return None
        template_path = (
            skill.get("matched_template_path")
            or skill.get("path")
            or self._skill_path(skill["skill_name"])
        )
        template = self._skill_template(template_path)
        if template is None:
            return None

        score = float(self._icon_similarity(crop, template))
        available_raw, value_ratio, sat_ratio = _availability_against_template(
            crop,
            template,
        )
        cooldown_fraction = _cooldown_overlay_fraction(crop, template)
        blocked_visual = (
            cooldown_fraction >= COOLDOWN_OVERLAY_STRONG
            or (
                cooldown_fraction >= COOLDOWN_OVERLAY_WEAK
                and value_ratio <= COOLDOWN_VALUE_RATIO_MAX
            )
        )

        local_min_score = (
            TRANSFORM_ANCHORED_SCORE_MIN
            if skill.get("attack_type") == "transform"
            else ANCHORED_SKILL_SCORE_MIN
        )

        if blocked_visual:
            availability = "unavailable"
        elif score >= local_min_score and available_raw:
            availability = "available"
        elif score >= local_min_score and not available_raw:
            availability = "unavailable"
        else:
            availability = "unknown"

        return {
            "score": score,
            "box": box,
            "available": availability == "available",
            "availability": availability,
            "cooldown_fraction": float(cooldown_fraction),
            "value_ratio": float(value_ratio),
            "sat_ratio": float(sat_ratio),
            "blocked_visual": bool(blocked_visual),
        }

    def _fast_expected_actor_a1(self, frame, rect, family):
        """Match only the already-expected actor's A1.

        This is intentionally NOT used for initial actor identification. It is
        only a cheap confirmation after the full first-frame decision has
        already identified the family with the normal all-A1 margin test.
        """
        mapped = self._a1_entry_by_family.get(family)
        if mapped is None:
            return None

        priority, entry = mapped
        name, skill_id, target_mode, attack_type = entry
        direct = self._direct_skill_match(frame, rect, name)
        if direct is None:
            return None

        return {
            **direct,
            "priority": priority,
            "skill_name": name,
            "skill_id": skill_id,
            "target_mode": target_mode,
            "attack_type": attack_type,
            "family": family,
            "path": self._skill_path(name),
            "physical_index": 0,
        }

    def fast_confirm_decision(self, frame, rect, decision):
        """Cheap second-frame/pre-click verification with safe fallback semantics.

        Returns a dict with ``ok`` and, when successful, a fresh ``skill`` item.
        A failure never means the decision is wrong; callers must fall back to
        the normal full scan instead of clicking.
        """
        if frame is None or decision is None:
            return {"ok": False, "reason": "no-frame-or-decision"}

        expected_family = decision.get("selected_family")
        previous_skill = decision.get("skill")
        if expected_family is None or previous_skill is None:
            return {"ok": False, "reason": "incomplete-decision"}

        a1_item = self._fast_expected_actor_a1(frame, rect, expected_family)
        if a1_item is None:
            return {"ok": False, "reason": "expected-a1-missing"}

        previous_conf = float(decision.get("family_confidence") or 0.0)
        dynamic_min = FAST_CONFIRM_A1_SCORE_MIN
        if previous_conf > 0.0:
            dynamic_min = max(
                dynamic_min,
                min(0.86, previous_conf - FAST_CONFIRM_MAX_A1_SCORE_DROP),
            )

        a1_score = float(a1_item.get("score", 0.0))
        if a1_score < dynamic_min:
            return {
                "ok": False,
                "reason": "expected-a1-not-strong",
                "a1_score": a1_score,
                "a1_min": dynamic_min,
            }

        # The expected A1 must also remain in the same physical place as on the
        # full-decision frame. This makes the fast path conservative on actor/UI
        # transitions without requiring a second all-champion scan.
        previous_a1 = next(
            (
                item for item in (decision.get("skill_scan") or {}).get("matches", [])
                if item.get("family") == expected_family
                and item.get("skill_id") == "A1"
            ),
            None,
        )
        if previous_a1 is not None:
            prev_center = previous_a1.get("center")
            new_center = a1_item.get("center")
            if prev_center is not None and new_center is not None:
                scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
                tolerance = FAST_CONFIRM_A1_CENTER_TOLERANCE_REF * scale
                if math.dist(prev_center, new_center) > tolerance:
                    return {
                        "ok": False,
                        "reason": "expected-a1-center-shift",
                        "a1_score": a1_score,
                    }

        skill_id = previous_skill.get("skill_id")
        if skill_id == "A1":
            current = dict(previous_skill)
            current.update({
                "score": a1_score,
                "center": a1_item.get("center", previous_skill.get("center")),
                "box": a1_item.get("box"),
                "available": True,
                "availability": "available",
                "cooldown_fraction": 0.0,
                "blocked_visual": False,
                "value_ratio": float(a1_item.get("value_ratio", 1.0)),
                "sat_ratio": float(a1_item.get("sat_ratio", 1.0)),
            })
        else:
            mapped = self._skill_entry_by_name.get(previous_skill.get("skill_name"))
            if mapped is None:
                return {"ok": False, "reason": "skill-entry-missing"}

            priority, entry = mapped
            current = self._anchored_skill_item(
                frame,
                rect,
                entry,
                priority,
                a1_item["center"],
            )
            if current is None:
                return {"ok": False, "reason": "anchored-skill-missing"}
            if current.get("availability") != "available":
                return {
                    "ok": False,
                    "reason": f"skill-{current.get('availability', 'unknown')}",
                    "skill": current,
                }

        return {
            "ok": True,
            "reason": "fast-confirm",
            "skill": current,
            "a1_score": a1_score,
            "a1_min": dynamic_min,
        }


    # --------------------------------------------------------
    # Targets / Stone Skin / affinity
    # --------------------------------------------------------
    def _region_score(self, frame, rect, region, path, scales, default=None):
        _check_deadline(self._deadline)
        if not os.path.exists(path):
            return default

        crop = _crop_abs(frame, rect, region)
        if crop is None or crop.size == 0:
            return default

        best = 0.0
        for scale in scales:
            _check_deadline(self._deadline)
            best = max(best, self.vision.best_score(
                crop, path, scales=(scale,),
                base_scale=self.vision.template_base_scale(frame),
            ))
            _check_deadline(self._deadline)
        return best

    def sheep_marker_score(self, frame, rect):
        """Return Sheep marker score in the allied half of the battlefield.

        This runs only on the rare family=None fallback path, so it does not add
        work to normal turns.
        """
        region = _rel_region(rect, *SHEEP_MARKER_FIELD_REF)
        score = self._region_score(
            frame,
            rect,
            region,
            SHEEP_TEMPLATE,
            scales=SHEEP_MARKER_SCALES,
            default=None,
        )
        return 0.0 if score is None else float(score)

    def _total_guard_score(self, frame, rect, geometry, slot):
        """Small local Total Guard match in one enemy buff ROI."""
        score = self._region_score(
            frame,
            rect,
            geometry["buff_regions"][slot],
            TOTAL_GUARD_TEMPLATE,
            scales=TOTAL_GUARD_SCALES,
            default=None,
        )
        return 0.0 if score is None else float(score)

    def choose_sheep_target(self, frame, rect, geometry):
        """Prefer an enemy carrying Total Guard; otherwise use normal targeting.

        A Sheep hit is useful for consuming a Total Guard stack, so unlike the
        normal damage path we intentionally prefer Total Guard when present.
        """
        states = self.scan_enemy_targets(frame, rect, geometry, allow_recent_fallback=True)
        alive = [s for s in states if s["alive"]]
        if not alive:
            return None, "no-live-target", 0.0

        visible = [s for s in alive if not s["veil"]]
        if not visible:
            return None, "all-live-targets-veiled", 0.0
        pool = visible
        pool, avoid_reason = self._target_avoid_pool(pool)

        scored = []
        for state in pool:
            score = self._total_guard_score(
                frame, rect, geometry, state["slot"]
            )
            if score >= TOTAL_GUARD_SCORE_MIN:
                scored.append((score, state))

        if scored:
            # Highest icon-confidence first; stable slot order breaks ties.
            score, chosen = max(
                scored,
                key=lambda pair: (pair[0], -pair[1]["slot"]),
            )
            return chosen, f"{avoid_reason}+prefer-total-guard(score={score:.3f})", score

        chosen, reason = self.choose_enemy_target(
            states,
            affinity_aware=False,
            lowest_hp=False,
        )
        return chosen, f"{avoid_reason}+no-total-guard+{reason}", 0.0

    def sheep_fallback_decision(self, frame, rect, tracker):
        """Build a safe pseudo-decision for a Polymorphed current actor.

        Required evidence:
        1) Sheep marker is visible on our side,
        2) the current skill bar contains exactly one physical skill button.
        """
        sheep_score = self.sheep_marker_score(frame, rect)
        if sheep_score < SHEEP_MARKER_SCORE_MIN:
            return None

        geometry = self.geometry(rect)
        physical = self.detect_skill_slots(frame, rect, geometry)
        if len(physical) != 1:
            return None

        only = physical[0]
        skill = {
            "skill_name": "skill_sheep_a1",
            "skill_id": "A1",
            "target_mode": "normal",
            "attack_type": "single",
            "family": "sheep",
            "center": only["center"],
            "radius": only.get("radius"),
            "physical_index": only.get("physical_index", 0),
            "score": sheep_score,
            "availability": "available",
            "available": True,
            "cooldown_fraction": 0.0,
            "blocked_visual": False,
            "value_ratio": 1.0,
            "sat_ratio": 1.0,
            "path": None,
        }

        return {
            "skill": skill,
            "target_slot": None,
            "target_point": None,
            "target_kind": "enemy",
            "reason": f"sheep-fallback marker={sheep_score:.3f}",
            "geometry": geometry,
            "enemy_states": [],
            "ally_ratios": {},
            "ally_tracker": tracker,
            "active_slot": None,
            "ring_ratios": {},
            "selected_family": "sheep",
            "family_confidence": sheep_score,
            "slot_family_memory": dict(slot_family_memory),
            "skill_scan": {
                "matches": [skill],
                "selected_family": "sheep",
                "family_confidence": sheep_score,
                "recognition_mode": "sheep-marker+single-physical-skill",
            },
            "tree_priority": 0,
            "tree_reason": "sheep-fallback",
        }

    def _target_avoid_patterns(self):
        """Load Block Damage / Unkillable / Counterattack templates once."""
        if self._target_avoid_assets is not None:
            return self._target_avoid_assets

        self._target_avoid_assets = {}
        root = Path("bilder")
        files = (
            {p.name.lower(): str(p) for p in root.iterdir() if p.is_file()}
            if root.is_dir() else {}
        )

        for kind, expected in TARGET_AVOID_TEMPLATES.items():
            path = files.get(Path(expected).name.lower(), expected)
            template = self._skill_template(path)
            if template is None or template.size == 0:
                continue
            self._target_avoid_assets[kind] = template
            self._target_avoid_sources[kind] = path

        return self._target_avoid_assets

    def _target_avoid_scores(self, frame, buff_crop):
        """Fast local matching for target-avoid buffs on the existing buff ROI."""
        _check_deadline(self._deadline)
        scores = {kind: None for kind in TARGET_AVOID_TEMPLATES}
        if buff_crop is None or buff_crop.size == 0:
            return scores

        patterns = self._target_avoid_patterns()
        if not patterns:
            return scores

        crop_gray = cv2.cvtColor(buff_crop, cv2.COLOR_BGR2GRAY)
        base_scale = float(self.vision.template_base_scale(frame))

        for kind, template in patterns.items():
            _check_deadline(self._deadline)
            key = (kind, round(base_scale, 4))
            variants = self._target_avoid_variant_cache.get(key)
            if variants is None:
                template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                variants = []
                seen_sizes = set()
                th, tw = template_gray.shape[:2]
                for local_scale in TARGET_AVOID_SCALE_FACTORS:
                    factor = base_scale * local_scale
                    size = (
                        max(8, int(round(tw * factor))),
                        max(8, int(round(th * factor))),
                    )
                    if size in seen_sizes:
                        continue
                    seen_sizes.add(size)
                    interpolation = cv2.INTER_AREA if factor < 1.0 else cv2.INTER_CUBIC
                    variants.append(cv2.resize(template_gray, size, interpolation=interpolation))

                if len(self._target_avoid_variant_cache) >= 24:
                    self._target_avoid_variant_cache.clear()
                self._target_avoid_variant_cache[key] = variants

            best = 0.0
            for variant in variants:
                _check_deadline(self._deadline)
                vh, vw = variant.shape[:2]
                if vh > crop_gray.shape[0] or vw > crop_gray.shape[1]:
                    continue
                result = cv2.matchTemplate(crop_gray, variant, cv2.TM_CCOEFF_NORMED)
                _, score, _, _ = cv2.minMaxLoc(result)
                if np.isfinite(score) and score > best:
                    best = float(score)
            scores[kind] = best

        return scores

    def _veil_patterns(self):
        if self._veil_assets is not None:
            return self._veil_assets
        self._veil_assets = {}
        root = Path("bilder")
        files = {p.name.lower(): str(p) for p in root.iterdir() if p.is_file()} if root.is_dir() else {}
        for kind, expected in zip(("veil", "perfect_veil"), VEIL_TEMPLATES):
            path = files.get(Path(expected).name.lower(), expected)
            template = self._skill_template(path)
            if template is not None:
                h, w = template.shape[:2]
                if not (.60 <= w / max(h, 1) <= 1.65):
                    print(f"COMBAT ASSET: {Path(path).name} is not a buff-icon crop; using embedded icon.")
                    template = None
            source = path
            if template is None:
                template = cv2.imdecode(np.frombuffer(base64.b64decode(_VEIL_ICON_PNG[kind]),
                                                      dtype=np.uint8), cv2.IMREAD_COLOR)
                source = "embedded-user-icon"
            if template is not None:
                self._veil_assets[kind] = template
                self._veil_sources[kind] = source
        return self._veil_assets

    def _veil_scores(self, frame, rect, region):
        """Match the two buff icons only above HP bars, with cached UI scales."""
        _check_deadline(self._deadline)
        crop = _crop_abs(frame, rect, region)
        if crop is None or crop.size == 0:
            return {}
        base_scale = self.vision.template_base_scale(frame)
        scores = {}
        for kind, template in self._veil_patterns().items():
            _check_deadline(self._deadline)
            key = (kind, round(base_scale, 5))
            variants = self._veil_variant_cache.get(key)
            if variants is None:
                variants = []
                sizes = set()
                for scale in VEIL_SCALES:
                    factor = base_scale * scale
                    h, w = template.shape[:2]
                    size = (max(8, round(w * factor)), max(8, round(h * factor)))
                    if size in sizes:
                        continue
                    sizes.add(size)
                    variants.append(cv2.resize(template, size,
                        interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC))
                # Resizing the game window must not grow this cache forever.
                if len(self._veil_variant_cache) >= 8:
                    self._veil_variant_cache.clear()
                self._veil_variant_cache[key] = variants
            best = 0.0
            for variant in variants:
                _check_deadline(self._deadline)
                h, w = variant.shape[:2]
                if h > crop.shape[0] or w > crop.shape[1]:
                    continue
                result = cv2.matchTemplate(crop, variant, cv2.TM_CCOEFF_NORMED)
                _, score, _, (x, y) = cv2.minMaxLoc(result)
                if not np.isfinite(score) or score <= best:
                    continue
                candidate = crop[y:y+h, x:x+w]
                hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV)
                blue = (hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 125) & (hsv[:, :, 1] >= 80)
                white = (hsv[:, :, 1] <= 100) & (hsv[:, :, 2] >= 150)
                if blue.mean() >= 0.20 and white.mean() >= 0.06:
                    best = float(score)
            scores[kind] = best
        _check_deadline(self._deadline)
        return scores

    @staticmethod
    def _longest_horizontal_run(mask):
        if mask is None or mask.size == 0:
            return 0
        best = 0
        for row in mask:
            values = (row > 0).astype(np.int16)
            diff = np.diff(np.r_[0, values, 0])
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            pairs = min(len(starts), len(ends))
            if pairs:
                best = max(best, int(np.max(ends[:pairs] - starts[:pairs])))
        return best

    def _enemy_hp_bar_evidence(self, frame, rect, region):
        """Detect actual HP-bar UI instead of red pixels on the battlefield."""
        crop = _crop_abs(frame, rect, region)
        empty = {"alive": False, "score": 0.0, "hp": 0.0,
                 "red_width": 0, "yellow_run": 0, "dark_run": 0}
        if crop is None or crop.size == 0:
            return empty

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        red = ((((hue <= 10) | (hue >= 170)) & (sat >= 100) & (val >= 70)).astype(np.uint8) * 255)
        yellow = (((hue >= 15) & (hue <= 40) & (sat >= 90) & (val >= 80)).astype(np.uint8) * 255)
        dark = ((val <= 75).astype(np.uint8) * 255)

        count, _, stats, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
        candidates = []
        for idx in range(1, count):
            x, y, w, h, area = stats[idx]
            aspect = w / float(max(1, h))
            if w < 7 * scale or h > 10 * scale or aspect < 1.60 or area < 8 * scale * scale:
                continue
            y1, y2 = max(0, y - 3), min(crop.shape[0], y + h + 16)
            x1, x2 = max(0, x - 8), min(crop.shape[1], x + w + 20)
            yellow_run = self._longest_horizontal_run(yellow[y1:y2, x1:x2])
            dark_run = self._longest_horizontal_run(
                dark[max(0, y - 4):min(crop.shape[0], y + h + 20),
                     max(0, x - 10):min(crop.shape[1], x + w + 25)]
            )
            score = float(w + 0.70 * yellow_run + 0.15 * dark_run)
            candidates.append({"score": score, "red_width": int(w),
                               "yellow_run": int(yellow_run), "dark_run": int(dark_run)})

        if not candidates:
            return empty
        best = max(candidates, key=lambda item: item["score"])
        fill = max(best["red_width"], best["yellow_run"])
        hp = max(0.0, min(1.0, fill / max(1.0, 60.0 * scale)))
        return {**best, "alive": best["score"] >= ENEMY_HP_BAR_SCORE_MIN, "hp": hp}

    def _special_effect_score(self, frame, rect, region, effect_name):
        path = SPECIAL_TARGET_EFFECT_TEMPLATES.get(effect_name)
        if not path:
            return None
        if not Path(path).is_file():
            if effect_name not in self._missing_special_effect_logged:
                self._missing_special_effect_logged.add(effect_name)
                print(f"COMBAT OPTIONAL ASSET: brak {Path(path).name}; reguła {effect_name} użyje fallbacku.")
            return None
        return self._region_score(
            frame,
            rect,
            region,
            path,
            scales=SPECIAL_TARGET_EFFECT_SCALES,
            default=None,
        )

    @staticmethod
    def _policy_effect_names(policy):
        if not policy:
            return ()
        names = []
        for key in ("avoid_effects", "prefer_effects"):
            for name in policy.get(key, ()):
                if name not in names and name not in (
                    "block_damage", "unkillable", "counterattack", "stoneskin"
                ):
                    names.append(name)
        return tuple(names)

    def ally_buff_count(self, frame, rect, geometry, slot):
        region = geometry.get("ally_buff_regions", {}).get(slot)
        if region is None:
            return None
        return _count_positive_buff_icons(_crop_abs(frame, rect, region))

    @staticmethod
    def lowest_hp_living_ally(ally_ratios, geometry):
        candidates = [
            (float(ratio), int(slot))
            for slot, ratio in (ally_ratios or {}).items()
            if float(ratio) >= ALLY_HP_ALIVE_THRESHOLD
            and geometry.get("ally_points", {}).get(slot) is not None
        ]
        if not candidates:
            return None, None
        ratio, slot = min(candidates, key=lambda row: (row[0], row[1]))
        return slot, geometry["ally_points"][slot]

    def scan_enemy_targets(self, frame, rect, geometry, allow_recent_fallback=False,
                           extra_effects=(), count_buffs=False):
        states = []
        hp_regions = geometry.get("enemy_hp_bar", geometry["enemy_hp"])
        for slot in (1, 2, 3, 4):
            hp_ui = self._enemy_hp_bar_evidence(frame, rect, hp_regions[slot])
            alive = bool(hp_ui["alive"])
            state = {
                "slot": slot, "alive": alive, "hp": float(hp_ui["hp"]),
                "hp_bar_score": float(hp_ui["score"]),
                "hp_bar_red_width": int(hp_ui["red_width"]),
                "hp_bar_yellow_run": int(hp_ui["yellow_run"]),
                "veil": False, "stoneskin": None, "stoneskin_score": None,
                "block_damage": None, "block_damage_score": None,
                "unkillable": None, "unkillable_score": None,
                "counterattack": None, "counterattack_score": None,
                "damage_immune": False, "damage_immune_kind": None,
                "target_avoid": False, "target_avoid_kind": None,
                "buff_count": None,
                "affinity": "unknown", "aim_point": geometry["enemy_points"][slot],
            }
            for effect_name in extra_effects:
                state[effect_name] = None
                state[f"{effect_name}_score"] = None
            if not alive:
                states.append(state)
                continue

            buff_region = geometry["buff_regions"][slot]
            buff_crop = _crop_abs(frame, rect, buff_region)

            if count_buffs:
                state["buff_count"] = _count_positive_buff_icons(buff_crop)

            for effect_name in extra_effects:
                score = self._special_effect_score(frame, rect, buff_region, effect_name)
                state[f"{effect_name}_score"] = score
                state[effect_name] = (
                    None if score is None
                    else bool(score >= SPECIAL_TARGET_EFFECT_SCORE_MIN)
                )

            veil_scores = self._veil_scores(frame, rect, buff_region)
            state["veil_known"] = len(veil_scores) == 2
            state["veil_scores"] = veil_scores
            best_kind = max(veil_scores, key=veil_scores.get) if veil_scores else None
            best_score = veil_scores.get(best_kind, 0.0)
            state["veil"] = best_score >= VEIL_SCORE_MIN
            state["veil_kind"] = best_kind if state["veil"] else None
            state["veil_score"] = best_score

            # V14.2: three tiny icon matches on the SAME buff crop/frame.
            # Counterattack adds only one local match; no screenshot is added.
            avoid_scores = self._target_avoid_scores(frame, buff_crop)
            active_avoid = []
            active_immunities = []
            for effect_name in ("block_damage", "unkillable", "counterattack"):
                effect_score = avoid_scores.get(effect_name)
                state[f"{effect_name}_score"] = effect_score
                if effect_score is None:
                    state[effect_name] = None
                else:
                    state[effect_name] = effect_score >= TARGET_AVOID_SCORE_MIN
                    if state[effect_name]:
                        active_avoid.append(effect_name)
                        if effect_name in ("block_damage", "unkillable"):
                            active_immunities.append(effect_name)
            state["damage_immune"] = bool(active_immunities)
            state["damage_immune_kind"] = "+".join(active_immunities) if active_immunities else None
            state["target_avoid"] = bool(active_avoid)
            state["target_avoid_kind"] = "+".join(active_avoid) if active_avoid else None

            ss_score = self._region_score(
                frame, rect, geometry["buff_regions"][slot], STONE_SKIN_TEMPLATE,
                scales=(0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.90,1.00,1.10,1.20),
                default=None,
            )
            state["stoneskin_score"] = ss_score
            if ss_score is not None:
                state["stoneskin"] = ss_score >= 0.78
            state["affinity"] = _affinity_relation(
                _crop_abs(frame, rect, geometry["affinity_regions"][slot])
            )
            states.append(state)
        alive_now = any(s.get("alive") for s in states)
        now = time.monotonic()
        if alive_now:
            self._enemy_state_cache = [dict(s) for s in states]
            self._enemy_state_cache_at = now
            return states

        if (
            allow_recent_fallback
            and self._enemy_state_cache
            and now - self._enemy_state_cache_at <= TARGET_STATE_CACHE_SECONDS
        ):
            cached = [dict(s) for s in self._enemy_state_cache]
            for state in cached:
                state["from_recent_cache"] = True
            return cached

        return states

    def update_ally_tracker(self, frame, rect, geometry, tracker):
        ratios = {}

        for slot in sorted(geometry["ally_hp"]):
            crop = _crop_abs(frame, rect, geometry["ally_hp"][slot])
            ratio = _green_hp_ratio(crop)
            ratios[slot] = ratio

            state = tracker.setdefault(
                slot,
                {
                    "seen_alive": False,
                    "alive_hits": 0,
                    "missing_hits": 0,
                    "dead": False,
                },
            )

            if ratio >= ALLY_HP_ALIVE_THRESHOLD:
                state["alive_hits"] += 1
                state["missing_hits"] = 0

                if state["alive_hits"] >= ALLY_ALIVE_CONFIRM_FRAMES:
                    state["seen_alive"] = True
                    state["dead"] = False
                continue

            if ratio <= ALLY_HP_DEAD_THRESHOLD:
                state["alive_hits"] = 0
                if state["seen_alive"]:
                    state["missing_hits"] += 1
                    if state["missing_hits"] >= ALLY_DEAD_CONFIRM_FRAMES:
                        state["dead"] = True
                continue

            state["alive_hits"] = 0

        return ratios

    @staticmethod
    def dead_ally(tracker, geometry):
        dead = [
            slot
            for slot, state in tracker.items()
            if state.get("seen_alive") and state.get("dead")
        ]
        if not dead:
            return None, None

        slot = min(dead)
        return slot, geometry["ally_points"].get(slot)

    @staticmethod
    def revive_target_candidates(
        rect, tracker, geometry, ally_ratios=None, preferred_slot=None
    ):
        """Ordered corpse-click candidates for ``attack_type == 'ally_dead'``.

        V15.25: retries are restricted to slots that have BOTH historical alive
        confirmation and consecutive dead confirmation.  The old fallback could
        eventually try a living/unknown ally slot after a missed corpse click.
        """
        points = geometry.get("ally_points") or {}
        if not points:
            return []

        confirmed_dead = [
            slot
            for slot, state in tracker.items()
            if state.get("seen_alive") and state.get("dead") and slot in points
        ]
        if not confirmed_dead:
            return []

        ordered_slots = []
        if preferred_slot in confirmed_dead:
            ordered_slots.append(preferred_slot)
        for slot in sorted(confirmed_dead):
            if slot not in ordered_slots:
                ordered_slots.append(slot)

        _, _, rw, rh = rect
        ref_w, ref_h = REFERENCE_SIZE
        sx = rw / float(max(1, ref_w))
        sy = rh / float(max(1, ref_h))

        candidates = []
        seen = set()

        for slot in ordered_slots:
            base = points.get(slot)
            if base is None:
                continue
            for idx, (dx_ref, dy_ref) in enumerate(REVIVE_CORPSE_OFFSETS_REF):
                point = (
                    int(round(base[0] + dx_ref * sx)),
                    int(round(base[1] + dy_ref * sy)),
                )
                key = (slot, point)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "slot": slot,
                    "point": point,
                    "reason": (
                        "confirmed-dead-slot"
                        if idx == 0
                        else f"confirmed-dead-corpse-offset-{idx}"
                    ),
                })

        return candidates

    @staticmethod
    def _affinity_pool(states):
        good = [
            s for s in states
            if s["affinity"] in ("positive", "neutral")
        ]
        if good:
            return good, "green/neutral"

        unknown = [s for s in states if s["affinity"] == "unknown"]
        if unknown:
            return unknown, "unknown-affinity"

        return states, "negative-only"

    @staticmethod
    def _target_avoid_pool(states):
        """Avoid Block Damage, Unkillable and Counterattack when alternatives exist.

        If every legal target is protected, keep a fallback so the bot never
        burns the whole turn waiting for an impossible safe target.
        """
        safe = [
            s for s in states
            if s.get("block_damage") is False
            and s.get("unkillable") is False
            and s.get("counterattack") is False
        ]
        if safe:
            if len(safe) < len(states):
                return safe, "avoid-block-damage/unkillable/counterattack"
            return safe, "no-target-avoid-buffs"

        unknown = [
            s for s in states
            if not s.get("target_avoid")
            and (
                s.get("block_damage") is None
                or s.get("unkillable") is None
                or s.get("counterattack") is None
            )
        ]
        if unknown:
            return unknown, "target-avoid-buff-unknown"

        return states, "all-targets-protected-fallback"

    @staticmethod
    def _damage_immunity_pool(states):
        # Compatibility for any older internal caller.
        safe = [
            s for s in states
            if s.get("block_damage") is False and s.get("unkillable") is False
        ]
        if safe:
            return safe, "avoid-block-damage/unkillable"
        unknown = [s for s in states if not s.get("damage_immune")]
        return (unknown or states), "damage-immunity-fallback"

    @staticmethod
    def _stoneskin_pool(states):
        no_ss = [s for s in states if s["stoneskin"] is False]
        if no_ss:
            return no_ss, "no-stoneskin"

        unknown = [s for s in states if s["stoneskin"] is None]
        if unknown:
            return unknown, "stoneskin-unknown"

        return states, "all-stoneskin"

    @staticmethod
    def _policy_avoid_pool(states, effects):
        pool = list(states)
        reasons = []
        for effect in effects or ():
            safe = [s for s in pool if s.get(effect) is False]
            if safe:
                if len(safe) < len(pool):
                    reasons.append(f"avoid-{effect}")
                pool = safe
                continue
            unknown = [s for s in pool if s.get(effect) is not True]
            if unknown:
                reasons.append(f"{effect}-unknown")
                pool = unknown
            else:
                reasons.append(f"all-{effect}-fallback")
        return pool, reasons

    @staticmethod
    def _strict_policy_has_target(states, effects, unknown_is_unsafe_effects=()):
        """Whether a skill-specific hard-avoid policy has a usable target.

        Explicitly safe targets win.  By default an unknown visual state may
        remain usable so a transient template miss does not disable a skill
        forever.  Individual policies can make selected effects fail-closed
        via ``unknown_is_unsafe_effects``.  Vestele A2 uses this for Unkillable:
        if Unkillable is present OR cannot be ruled out, A2 becomes ineligible
        and the priority tree falls through to A1.
        """
        alive = [s for s in states if s.get("alive")]
        if not alive:
            return False, "no-live-target"
        visible = [s for s in alive if not s.get("veil")]
        if not visible:
            return False, "all-live-targets-veiled"
        pool = visible
        reasons = []
        fail_closed = set(unknown_is_unsafe_effects or ())
        for effect in effects or ():
            safe = [s for s in pool if s.get(effect) is False]
            if safe:
                pool = safe
                reasons.append(f"strict-safe-{effect}")
                continue
            if effect in fail_closed:
                return False, f"no-explicit-safe-{effect}"
            unknown = [s for s in pool if s.get(effect) is not True]
            if unknown:
                pool = unknown
                reasons.append(f"strict-{effect}-unknown")
                continue
            return False, f"all-targets-{effect}"
        return bool(pool), "+".join(reasons) or "strict-target-ok"

    def choose_enemy_target(
        self, states, affinity_aware, lowest_hp, policy=None,
        family=None, skill_id=None, attack_type=None,
    ):
        policy = policy or {}
        alive = [s for s in states if s["alive"]]
        if not alive:
            return None, "no-live-target"
        visible = [s for s in alive if not s["veil"]]
        # V15.20: Veil / Perfect Veil is a HARD legality filter.
        # Never fall back to clicking a veiled champion: RAID can reject that
        # target and the bot then burns the turn retrying an impossible click.
        if not visible:
            return None, "all-live-targets-veiled"
        pool = visible
        reason = ["exclude-veil"] if len(visible) < len(alive) else []

        # Hard global safety first.
        pool, avoid_reason = self._target_avoid_pool(pool)
        reason.append(avoid_reason)

        # Skill-specific hard avoids (Fabian A2, Vestele A2, ...).
        pool, policy_reasons = self._policy_avoid_pool(
            pool, policy.get("avoid_effects", ())
        )
        reason.extend(policy_reasons)

        # Existing soft Stone Skin preference remains intact.
        pool, ss_reason = self._stoneskin_pool(pool)
        reason.append(ss_reason)

        # Explicit user target preferences outrank generic affinity/HP fallback.
        prefer_effects = tuple(policy.get("prefer_effects", ()))
        if prefer_effects:
            preferred = [
                s for s in pool
                if any(s.get(effect) is True for effect in prefer_effects)
            ]
            if preferred:
                pool = preferred
                reason.append("prefer-" + "+".join(prefer_effects))

        buff_mode = policy.get("buff_count")
        if buff_mode in ("min", "max"):
            known = [s for s in pool if isinstance(s.get("buff_count"), int)]
            if known:
                value = (
                    min(s["buff_count"] for s in known)
                    if buff_mode == "min"
                    else max(s["buff_count"] for s in known)
                )
                pool = [s for s in known if s["buff_count"] == value]
                reason.append(f"buff-count-{buff_mode}={value}")

        if affinity_aware and len(pool) > 1:
            pool, affinity_reason = self._affinity_pool(pool)
            reason.append(affinity_reason)

        if lowest_hp:
            # Explicit lowest_hp is a hard skill semantic, not a soft preference.
            target = min(pool, key=lambda s: (s["hp"], s["slot"]))
            reason.append("lowest-hp")
        elif self.autonomy_target_enabled and pool:
            target, auto_reason, target_trace = self.autonomy.choose_target(
                pool,
                attack_type=str(attack_type or "single"),
                lowest_hp=False,
                affinity_aware=bool(affinity_aware),
                policy=policy,
            )
            if target is None:
                return None, "+".join(reason + ["autonomy-no-target"])
            reason.append(auto_reason)
            try:
                self.autonomy.telemetry.emit(
                    "combat_target_rank",
                    {
                        "family": family,
                        "skill_id": skill_id,
                        "trace": target_trace,
                    },
                )
            except Exception:
                pass
        else:
            target = min(pool, key=lambda s: s["slot"])
            reason.append("stable-slot")
        return target, "+".join(reason)

    def selected_skill(self, frame, rect, skill):
        """Detect RAID's cyan selected-skill rim before a target click.

        V15.10 restores this method after the large-roster merge accidentally
        dropped it while CombatEngine still called it from three confirmation
        paths.  The detector reuses the already captured combat frame and only
        inspects a tiny crop around the chosen skill, so it adds no screenshot.
        """
        if frame is None or rect is None or not skill:
            return False

        center = skill.get("center")
        if center is None or len(center) != 2:
            return False

        x, y = center
        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) / 2.0
        half = max(20, round(55 * scale))

        crop = _crop_abs(
            frame,
            rect,
            (
                int(round(x - half)),
                int(round(y - half)),
                int(half * 2),
                int(half * 2),
            ),
        )
        if crop is None or crop.size == 0:
            return False

        hsv = cv2.cvtColor(
            cv2.resize(crop, (110, 110), interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2HSV,
        )

        yy, xx = np.ogrid[:110, :110]
        radius_sq = (xx - 55) ** 2 + (yy - 55) ** 2
        ring = (radius_sq >= 43 ** 2) & (radius_sq <= 52 ** 2)

        cyan = (
            (hsv[:, :, 0] >= 80)
            & (hsv[:, :, 0] <= 105)
            & (hsv[:, :, 1] >= 95)
            & (hsv[:, :, 2] >= 150)
        )

        ring_pixels = int(ring.sum())
        if ring_pixels <= 0:
            return False

        cyan_ratio = float(cyan[ring].mean())
        return cyan_ratio >= 0.22

    def ally_confirm_target(self, frame, rect, geometry):
        """Select a living ally only when the UI shows its green target marker."""
        template = cv2.imdecode(np.frombuffer(base64.b64decode(
            _ALLY_CONFIRM_MARKER_PNG), np.uint8), cv2.IMREAD_GRAYSCALE)
        base = ((rect[2] / 1024.0) + (rect[3] / 769.0)) / 2
        for slot, region in sorted(geometry["ally_hp"].items()):
            if _green_hp_ratio(_crop_abs(frame, rect, region)) < ALLY_HP_ALIVE_THRESHOLD:
                continue
            x, y, w, h = region
            crop = _crop_abs(frame, rect, (x, y-round(15*base), w, round(50*base)))
            if crop is None or crop.size == 0:
                continue
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            green = cv2.inRange(hsv, np.array([40,120,100],np.uint8),
                               np.array([90,255,255],np.uint8))
            for relative in (.85, 1.0, 1.15):
                size = max(5, round(21 * base * relative))
                if size > min(green.shape):
                    continue
                needle = cv2.resize(template, (size,size), interpolation=cv2.INTER_NEAREST)
                score = cv2.minMaxLoc(cv2.matchTemplate(green, needle, cv2.TM_CCORR_NORMED))[1]
                if score >= .84:
                    return slot, geometry["ally_points"][slot], "ally-selection-marker"
        return None, None, "no-ally-selection-marker"

    def _skill_decision_rank(self, item, family):
        priorities = SKILL_PRIORITY_BY_FAMILY.get(family, [])

        # V12: skill musi być JAWNIE obecny w priority tej rodziny.
        # Dzięki temu Mikage nie dotknie A4, jeśli jej plan to A3>A2>A1.
        try:
            return float(priorities.index(item["skill_id"]))
        except ValueError:
            return 999.0

    def _apply_skill_rules(self, frame, rect, geometry, family, own,
                           dead_point, active_slot, combat_context):
        rules = SKILL_RULES_BY_FAMILY.get(family, {})
        if not rules:
            return
        for skill_id, rule in rules.items():
            item = own.get(skill_id)
            if item is None:
                continue
            item["eligibility"] = "eligible"
            item["eligibility_reason"] = f"priority-{skill_id}-ready"

            opening_enemies = tuple(
                _family_root(x)
                for x in rule.get("opening_skip_if_enemy_any", ())
                if _family_root(x)
            )
            if opening_enemies:
                action_counts = (combat_context or {}).get("family_action_counts", {})
                family_root = _family_root(family)
                already_acted = int(action_counts.get(family_root, 0)) > 0
                matched_enemy = next(
                    (
                        enemy
                        for enemy in opening_enemies
                        if enemy in self.final_opponent_family_hints
                    ),
                    None,
                )
                if matched_enemy is not None and not already_acted:
                    item["eligibility"] = "ineligible"
                    item["eligibility_reason"] = (
                        f"{skill_id}-opening-skip-vs-{matched_enemy}"
                    )
                    log_key = (family_root, skill_id, matched_enemy)
                    if log_key not in self._opening_rule_logged:
                        self._opening_rule_logged.add(log_key)
                        print(
                            "COMBAT OPENING RULE -> "
                            f"{family_root}: pomijam {skill_id} na pierwszej akcji "
                            f"vs {matched_enemy}."
                        )
                    continue

            if rule.get("requires_dead_ally"):
                if dead_point is None:
                    item["eligibility"] = "ineligible"
                    item["eligibility_reason"] = f"{skill_id}-needs-dead-ally"
                    continue
                item["eligibility_reason"] = f"{skill_id}-dead-ally-confirmed"

            if rule.get("requires_extra_turn"):
                if not bool((combat_context or {}).get("extra_turn")):
                    item["eligibility"] = "ineligible"
                    item["eligibility_reason"] = f"{skill_id}-extra-turn-only"
                    continue
                item["eligibility_reason"] = f"{skill_id}-extra-turn-confirmed"

            counts = rule.get("self_buff_count_in")
            if counts is not None:
                if active_slot is None:
                    item["eligibility"] = "unknown"
                    item["eligibility_reason"] = f"{skill_id}-self-buff-slot-unknown"
                    continue
                count = self.ally_buff_count(frame, rect, geometry, active_slot)
                item["self_buff_count"] = count
                if count is None:
                    item["eligibility"] = "unknown"
                    item["eligibility_reason"] = f"{skill_id}-self-buff-count-unknown"
                elif int(count) in set(int(x) for x in counts):
                    item["eligibility_reason"] = f"{skill_id}-self-buffs={count}"
                else:
                    item["eligibility"] = "ineligible"
                    item["eligibility_reason"] = f"{skill_id}-self-buffs={count}-not-trigger"

    # --------------------------------------------------------
    # Main decision
    # --------------------------------------------------------
    def choose_decision(
        self,
        frame,
        rect,
        tracker,
        slot_family_memory,
        allow_a1_fallback=False,
        combat_context=None,
    ):
        geometry = self.geometry(rect)

        # Ring jest tylko diagnostyką. Nie decyduje już o rodzinie championa.
        active_slot, ring_ratios = self.detect_active_ally_slot(
            frame,
            rect,
            geometry,
        )

        skill_scan = self.scan_skill_slots(
            frame,
            rect,
            geometry,
            active_slot=active_slot,
            slot_family_memory=slot_family_memory,
        )

        family = skill_scan["selected_family"]
        family_confidence = skill_scan["family_confidence"]

        enemy_states = []  # Scan enemies only when a candidate actually needs one.

        ally_ratios = self.update_ally_tracker(
            frame,
            rect,
            geometry,
            tracker,
        )
        dead_slot, dead_point = self.dead_ally(tracker, geometry)

        # ----------------------------------------------------
        # V13: py_trees owns skill priority logic.
        # Default for every champion: A3 -> A2 -> A1.
        # A lower skill is considered only when the higher one is
        # confirmed unavailable/ineligible. Unknown != cooldown.
        # ----------------------------------------------------
        own = {
            m["skill_id"]: m
            for m in skill_scan["matches"]
            if family is not None and m["family"] == family
        }
        declared_skill_ids = {
            entry[1]
            for entry in self.skill_plan
            if family is not None and _skill_family(entry[0]) == family
        }

        self._apply_skill_rules(
            frame, rect, geometry, family, own, dead_point, active_slot, combat_context or {}
        )

        dynamic_priority = None
        autonomy_skill_scores = {}
        if self.autonomy_combat_enabled and family is not None:
            # One shared state scan powers skill utility + later target selection.
            # Hard target rules may request extra effect templates below; this base
            # scan remains conservative and is cached by the analyzer.
            enemy_states = self.scan_enemy_targets(
                frame, rect, geometry, allow_recent_fallback=True,
                extra_effects=(), count_buffs=False,
            )
            static_priority = self.decision_tree.priority_for(family)
            dynamic_priority, autonomy_skill_scores = self.autonomy.rank_skill_ids(
                family, own, static_priority,
                enemy_states=enemy_states,
                ally_tracker=tracker,
                ally_ratios=ally_ratios,
                combat_context=combat_context or {},
                opponent_families=self.final_opponent_family_hints,
                min_score=SKILL_MATCH_MIN,
                reorder_margin=AUTONOMY_SKILL_REORDER_MARGIN,
            )

        tree_result = self.decision_tree.decide(
            family=family,
            skills=own,
            declared_skill_ids=declared_skill_ids,
            dead_ally_available=(dead_point is not None),
            min_score=SKILL_MATCH_MIN,
            prefer_fallback=bool(allow_a1_fallback),
            priority_override=dynamic_priority,
        )

        # Some skills have a user-defined HARD target condition. Example:
        # Fabian A2 must not be spent into Block Debuffs/Total Guard and
        # Vestele A2 requires a target without Unkillable/Total Guard (Mercurial). If every
        # known target violates that condition, mark only that skill ineligible
        # and let the same strict tree fall through to A1. This scan happens
        # only when such a skill is actually the selected candidate.
        for _ in range(4):
            selected = tree_result.skill
            if selected is None:
                break
            selected_policy = TARGET_POLICY_BY_FAMILY_SKILL.get(
                (family, selected["skill_id"]), {}
            )
            if not selected_policy.get("strict_avoid"):
                break

            selected_effects = self._policy_effect_names(selected_policy)
            if not enemy_states:
                enemy_states = self.scan_enemy_targets(
                    frame, rect, geometry, allow_recent_fallback=True,
                    extra_effects=selected_effects, count_buffs=False,
                )

            target_ok, target_rule_reason = self._strict_policy_has_target(
                enemy_states,
                selected_policy.get("avoid_effects", ()),
                selected_policy.get("unknown_is_unsafe_effects", ()),
            )
            if target_ok:
                selected["eligibility_reason"] = (
                    selected.get("eligibility_reason")
                    or f"{selected['skill_id']}-target-rule-ok"
                )
                break

            selected["eligibility"] = "ineligible"
            selected["eligibility_reason"] = (
                f"{selected['skill_id']}-target-rule-{target_rule_reason}"
            )
            tree_result = self.decision_tree.decide(
                family=family,
                skills=own,
                declared_skill_ids=declared_skill_ids,
                dead_ally_available=(dead_point is not None),
                min_score=SKILL_MATCH_MIN,
                prefer_fallback=bool(allow_a1_fallback),
                priority_override=dynamic_priority,
            )

        priority_reason = tree_result.reason
        tree_priority = tree_result.priority
        tree_state = tree_result.state
        tree_unknown_reasons = tuple(getattr(tree_result, "unknown_reasons", ()) or ())
        autonomy_trace = {
            sid: score.as_dict()
            for sid, score in (autonomy_skill_scores or {}).items()
        }
        fallback_skill = None

        if (
            allow_a1_fallback
            and tree_result.skill is None
            and tree_result.state == "wait"
            and family is not None
        ):
            wait_reason = str(tree_result.reason or "")
            perception_wait = any(
                wait_reason.endswith(suffix)
                for suffix in (
                    "-availability-unknown",
                    "-not-recognised",
                    "-match-uncertain",
                )
            )
            a1 = own.get("A1")
            if (
                perception_wait
                and a1 is not None
                and "A1" in tree_result.priority
                and "A1" in declared_skill_ids
                and a1.get("eligibility", "eligible") == "eligible"
                and a1.get("availability") == "available"
                and float(a1.get("score", 0.0)) >= SKILL_MATCH_MIN
            ):
                fallback_skill = dict(a1)
                fallback_skill["fallback"] = True
                priority_reason = f"safe-A1-fallback-after-{wait_reason}"
                tree_state = "selected"

        selected_skill = fallback_skill or tree_result.skill
        candidates = [selected_skill] if selected_skill is not None else []

        for skill in candidates:
            attack_type = skill["attack_type"]
            target_mode = skill["target_mode"]
            target_policy = TARGET_POLICY_BY_FAMILY_SKILL.get(
                (family, skill["skill_id"]), {}
            )
            policy_effects = self._policy_effect_names(target_policy)
            policy_count_buffs = target_policy.get("buff_count") in ("min", "max")

            # V15.20: mythical transform is a TWO-STEP self-confirm action in RAID:
            #   1) click A4,
            #   2) click the model of the currently acting mythical champion.
            # Komidus therefore must never use the direct/no-target path. Resolve
            # the active actor from the large floor ring before the skill click and
            # keep the current slot only as a fallback.
            if attack_type == "transform":
                # Mythical transform must click the champion MODEL, not the floor
                # ring.  The calibrated ally point is centred much higher on the
                # model and is substantially more reliable for Komidus A4.
                # The floor-ring point is only a fallback when the active slot is
                # temporarily ambiguous.
                self_point = (
                    geometry["ally_points"].get(active_slot)
                    if active_slot is not None
                    else None
                )
                self_debug = {"reason": "active-slot-model"} if self_point is not None else {}
                if self_point is not None:
                    self_reason = "mythical-transform-active-slot-model"
                else:
                    self_point, self_debug = self.detect_active_actor_floor_point(frame, rect)
                    if self_point is not None:
                        self_reason = "mythical-transform-floor-fallback"
                    else:
                        self_reason = "mythical-transform-await-active-model"

                return {
                    "skill": skill,
                    "target_slot": active_slot,
                    "target_point": self_point,
                    "target_kind": "self_actor",
                    "reason": self_reason,
                    "self_actor_debug": self_debug,
                    "geometry": geometry,
                    "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios,
                    "ally_tracker": tracker,
                    "active_slot": active_slot,
                    "ring_ratios": ring_ratios,
                    "selected_family": family,
                    "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory),
                    "skill_scan": skill_scan,
                    "tree_priority": tree_priority,
                    "tree_reason": priority_reason,
                    "tree_state": tree_state,
                    "tree_unknown_reasons": tree_unknown_reasons,
                    "autonomy_skill_scores": autonomy_trace,
                }

            # Non-transform A4 is NOT automatically self-targeted.  Arbiter A4
            # is a revive (ally_dead), while other future A4 skills may be targeted.
            # Route by attack_type exactly like A1/A2/A3.
            if skill.get("skill_id") == "A4" and attack_type == SELF_TARGET_ATTACK_TYPE:
                self_point, self_debug = self.detect_active_actor_floor_point(frame, rect)
                if self_point is None and active_slot is not None:
                    self_point = geometry["ally_points"].get(active_slot)
                    self_reason = "a4-self-active-slot"
                elif self_point is not None:
                    self_reason = "a4-self-active-floor-ring"
                else:
                    self_reason = "a4-self-await-floor-ring"

                return {
                    "skill": skill,
                    "target_slot": active_slot,
                    "target_point": self_point,
                    "target_kind": "self_actor",
                    "reason": self_reason,
                    "self_actor_debug": self_debug,
                    "geometry": geometry,
                    "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios,
                    "ally_tracker": tracker,
                    "active_slot": active_slot,
                    "ring_ratios": ring_ratios,
                    "selected_family": family,
                    "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory),
                    "skill_scan": skill_scan,
                    "tree_priority": tree_priority,
                    "tree_reason": priority_reason,
                    "tree_state": tree_state,
                    "tree_unknown_reasons": tree_unknown_reasons,
                    "autonomy_skill_scores": autonomy_trace,
                }

            if attack_type == "ally_dead":
                if dead_point is None:
                    continue

                return {
                    "skill": skill,
                    "target_slot": dead_slot,
                    "target_point": dead_point,
                    "target_kind": "ally",
                    "reason": f"confirmed-dead-ally-slot-{dead_slot}",
                    "geometry": geometry,
                    "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios,
                    "ally_tracker": tracker,
                    "active_slot": active_slot,
                    "ring_ratios": ring_ratios,
                    "selected_family": family,
                    "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory),
                    "skill_scan": skill_scan,
                    "tree_priority": tree_priority,
                    "tree_reason": priority_reason,
                    "tree_state": tree_state,
                    "tree_unknown_reasons": tree_unknown_reasons,
                    "autonomy_skill_scores": autonomy_trace,
                }

            if attack_type == "ally_living":
                ally_slot, ally_point = self.lowest_hp_living_ally(ally_ratios, geometry)
                if ally_point is None:
                    continue
                return {
                    "skill": skill,
                    "target_slot": ally_slot,
                    "target_point": ally_point,
                    "target_kind": "ally_living",
                    "reason": f"lowest-hp-living-ally-slot-{ally_slot}",
                    "geometry": geometry,
                    "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios,
                    "ally_tracker": tracker,
                    "active_slot": active_slot,
                    "ring_ratios": ring_ratios,
                    "selected_family": family,
                    "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory),
                    "skill_scan": skill_scan,
                    "tree_priority": tree_priority,
                    "tree_reason": priority_reason,
                    "tree_state": tree_state,
                    "tree_unknown_reasons": tree_unknown_reasons,
                    "autonomy_skill_scores": autonomy_trace,
                    "target_policy": target_policy,
                }

            if attack_type == "aoe":
                # V13.5: the replay proves that Harima A3 remained selected
                # until the timer expired when we only clicked the skill button.
                # RAID needs a target-confirm click for these combat AoEs.
                if not enemy_states:
                    enemy_states = self.scan_enemy_targets(
                        frame, rect, geometry, allow_recent_fallback=True,
                        extra_effects=policy_effects, count_buffs=policy_count_buffs,
                    )

                alive = [s for s in enemy_states if s["alive"]]
                if not alive:
                    continue

                # Even an AoE needs a target-confirm click in RAID. Prefer a
                # confirmation target without Block Damage/Unkillable when one
                # exists; this uses the already-scanned enemy states.
                confirm_target, confirm_reason = self.choose_enemy_target(
                    enemy_states,
                    affinity_aware=False,
                    lowest_hp=False,
                    policy=target_policy,
                    family=family, skill_id=skill.get("skill_id"), attack_type=attack_type,
                )
                if confirm_target is None:
                    continue

                return {
                    "skill": skill,
                    "target_slot": confirm_target["slot"],
                    "target_point": confirm_target.get(
                        "aim_point",
                        geometry["enemy_points"][confirm_target["slot"]],
                    ),
                    "target_kind": "enemy_confirm",
                    "reason": f"aoe-confirm+{confirm_reason}",
                    "geometry": geometry,
                    "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios,
                    "ally_tracker": tracker,
                    "active_slot": active_slot,
                    "ring_ratios": ring_ratios,
                    "selected_family": family,
                    "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory),
                    "skill_scan": skill_scan,
                    "tree_priority": tree_priority,
                    "tree_reason": priority_reason,
                    "tree_state": tree_state,
                    "tree_unknown_reasons": tree_unknown_reasons,
                    "autonomy_skill_scores": autonomy_trace,
                    "target_policy": target_policy,
                }

            if attack_type == SELF_TARGET_ATTACK_TYPE:
                # Team-wide/support buffs always confirm on the CURRENT actor.
                # Never scan/select another ally.
                # V15.26: Tekteon A3 needs a click on his MODEL.  The large floor
                # ring is useful for actor detection, but its derived click point
                # can land too low/right and fail to confirm the cast.  Keep this
                # change local to Tekteon to avoid changing other champions.
                if (
                    _family_root(family) == "tekteon"
                    and active_slot is not None
                    and geometry["ally_points"].get(active_slot) is not None
                ):
                    self_point = geometry["ally_points"][active_slot]
                    self_debug = {"reason": "active-slot-model"}
                    self_reason = "self-active-slot-model"
                else:
                    self_point, self_debug = self.detect_active_actor_floor_point(frame, rect)
                    if self_point is None and active_slot is not None:
                        self_point = geometry["ally_points"].get(active_slot)
                        self_reason = "self-active-slot"
                    elif self_point is not None:
                        self_reason = "self-active-floor-ring"
                    else:
                        self_reason = "self-await-floor-ring"
                return {
                    "skill": skill, "target_slot": active_slot,
                    "target_point": self_point, "target_kind": "self_actor",
                    "reason": self_reason, "self_actor_debug": self_debug,
                    "geometry": geometry, "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios, "ally_tracker": tracker,
                    "active_slot": active_slot, "ring_ratios": ring_ratios,
                    "selected_family": family, "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory), "skill_scan": skill_scan,
                    "tree_priority": tree_priority, "tree_reason": priority_reason,
                    "autonomy_skill_scores": autonomy_trace,
                }

            if attack_type in ("single", "targeted"):
                if not enemy_states:
                    enemy_states = self.scan_enemy_targets(
                        frame, rect, geometry, allow_recent_fallback=True,
                        extra_effects=policy_effects, count_buffs=policy_count_buffs,
                    )
                target, reason = self.choose_enemy_target(
                    enemy_states,
                    affinity_aware=(attack_type == "single"),
                    lowest_hp=(target_mode == "lowest_hp"),
                    policy=target_policy,
                    family=family, skill_id=skill.get("skill_id"), attack_type=attack_type,
                )
                if target is None:
                    continue

                return {
                    "skill": skill,
                    "target_slot": target["slot"],
                    "target_point": target.get(
                        "aim_point",
                        geometry["enemy_points"][target["slot"]],
                    ),
                    "target_kind": "enemy",
                    "reason": reason,
                    "geometry": geometry,
                    "enemy_states": enemy_states,
                    "ally_ratios": ally_ratios,
                    "ally_tracker": tracker,
                    "active_slot": active_slot,
                    "ring_ratios": ring_ratios,
                    "selected_family": family,
                    "family_confidence": family_confidence,
                    "slot_family_memory": dict(slot_family_memory),
                    "skill_scan": skill_scan,
                    "tree_priority": tree_priority,
                    "tree_reason": priority_reason,
                    "tree_state": tree_state,
                    "tree_unknown_reasons": tree_unknown_reasons,
                    "autonomy_skill_scores": autonomy_trace,
                    "target_policy": target_policy,
                }

        return {
            "skill": None,
            "target_slot": None,
            "target_point": None,
            "target_kind": None,
            "reason": priority_reason or "no-eligible-skill",
            "geometry": geometry,
            "enemy_states": enemy_states,
            "ally_ratios": ally_ratios,
            "ally_tracker": tracker,
            "active_slot": active_slot,
            "ring_ratios": ring_ratios,
            "selected_family": family,
            "family_confidence": family_confidence,
            "slot_family_memory": dict(slot_family_memory),
            "skill_scan": skill_scan,
            "tree_priority": tree_priority,
            "tree_reason": priority_reason,
            "tree_state": tree_state,
            "tree_unknown_reasons": tree_unknown_reasons,
            "autonomy_skill_scores": autonomy_trace,
        }

    @staticmethod
    def top_skill_scores(decision, limit=8):
        scan = decision.get("skill_scan") or {}
        matches = scan.get("matches") or []
        selected = decision.get("selected_family")

        ordered = sorted(
            matches,
            key=lambda x: (
                0 if x.get("family") == selected else 1,
                -x["score"],
            ),
        )
        return [
            (
                x["skill_name"],
                round(x["score"], 3),
                x["center"],
                bool(x.get("available", True)),
            )
            for x in ordered[:limit]
        ]


class CombatEngine:
    def __init__(
        self,
        vision,
        mouse,
        find_raid_rect,
        wait_if_paused,
        sleep_func,
        set_state,
        consume_diagnostic=None,
        debug_dir="./debug",
        active_families=None,
        opponent_families=None,
        combat_condition_families=None,
    ):
        self.vision = vision
        self.mouse = mouse
        self.find_raid_rect = find_raid_rect
        self.wait_if_paused = wait_if_paused
        self._raw_sleep = sleep_func
        self._paused_total = 0.0
        self._pause_epoch = 0
        self.sleep = self._pauseable_sleep
        self.set_state = set_state
        self.consume_diagnostic = consume_diagnostic
        self.debug_dir = Path(debug_dir)
        self.active_families = tuple(active_families or ())
        self.opponent_families = tuple(opponent_families or ())
        self.combat_condition_families = tuple(combat_condition_families or ())
        self.autonomy = get_autonomy_controller()
        self.analyzer = CombatAnalyzer(
            vision,
            active_families=self.active_families,
            opponent_families=self.opponent_families,
            combat_condition_families=self.combat_condition_families,
        )

        self._your_turn_icon = None
        try:
            self._your_turn_icon = cv2.imread(YOUR_TURN_TEMPLATE, cv2.IMREAD_COLOR)
        except Exception:
            self._your_turn_icon = None
        self._last_obscured_click_log_at = 0.0

    def _pause_barrier(self):
        """Block on the global pause and report whether time really elapsed.

        RAID keeps running while the bot is paused. A frame/point captured before
        a pause must therefore never be clicked blindly after resume.
        """
        started = time.monotonic()
        self.wait_if_paused()
        waited = max(0.0, time.monotonic() - started)
        if waited >= PAUSE_STALE_AFTER_SECONDS:
            self._paused_total += waited
            self._pause_epoch += 1
        return waited

    def _clock(self):
        """Active-work clock: bot pause time does not consume local timeouts."""
        return time.monotonic() - self._paused_total

    def _pauseable_sleep(self, seconds):
        """Wrap arenalive's sleep callback and account for time spent paused."""
        seconds = max(0.0, float(seconds))
        self._pause_barrier()
        started = time.monotonic()
        self._raw_sleep(seconds)
        elapsed = max(0.0, time.monotonic() - started)
        extra = max(0.0, elapsed - seconds)
        if extra >= 0.03:
            self._paused_total += extra
            self._pause_epoch += 1

    def _capture(self, rect):
        return self.vision.capture(rect)

    @staticmethod
    def _screen_point(rect, frame_point):
        if frame_point is None:
            return None
        left, top, _, _ = rect
        return (
            left + int(frame_point[0]),
            top + int(frame_point[1]),
        )

    @staticmethod
    def _point_hits_raid_window(point):
        """Return False when another top-level window overlays the click point.

        Windows toast/browser notifications can cover the skill bar.  Sending a
        click through pyautogui in that state activates the overlay instead of
        RAID.  WindowFromPoint gives us a cheap last-millisecond guard.
        """
        if os.name != "nt" or point is None:
            return True
        try:
            user32 = ctypes.windll.user32
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int

            pt = wintypes.POINT(int(point[0]), int(point[1]))
            hwnd = user32.WindowFromPoint(pt)
            if not hwnd:
                return False
            root = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
            n = user32.GetWindowTextLengthW(root)
            if n <= 0:
                return False
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(root, buf, n + 1)
            title = buf.value.strip().lower()
            return title in {"raid: shadow legends", "raid shadow legends"}
        except Exception:
            # Never disable combat because an OS-level safety query failed.
            return True

    def _click(self, point, rect, min_duration=0.09, max_duration=0.22,
               deadline=None):
        def guard():
            # If a pause happened after this point/frame was chosen, abort this
            # click. The run loop will recapture and re-evaluate on resume.
            if self._pause_barrier() >= PAUSE_STALE_AFTER_SECONDS:
                raise CombatDeadline()
            _check_deadline(deadline, CLICK_RESERVE_SECONDS)
            if self.find_raid_rect() != rect:
                raise CombatDeadline()
            if not self._point_hits_raid_window(point):
                now = self._clock()
                if now - self._last_obscured_click_log_at >= 1.0:
                    print(
                        "CLICK GUARD: punkt RAID jest zasłonięty innym oknem/"
                        "powiadomieniem -> anuluję klik i skanuję ponownie."
                    )
                    self._last_obscured_click_log_at = now
                raise CombatDeadline()
        try:
            guard()
            return self.mouse.click(
                point, window_rect=rect, min_duration=min_duration,
                max_duration=max_duration, wait_if_paused=guard,
            )
        except CombatDeadline:
            return False

    def _your_turn_text_score(self, frame):
        """Cheap direct match in the small top-center turn-label ROI."""
        template = self._your_turn_icon
        if template is None or frame is None or frame.size == 0:
            return 0.0

        crop = _frame_rel_region(frame, YOUR_TURN_ROI_REF)
        if crop is None or crop.size == 0:
            return 0.0

        fh, fw = frame.shape[:2]
        ref_w, ref_h = REFERENCE_SIZE
        base = ((fw / ref_w) + (fh / ref_h)) * 0.5

        best = 0.0
        for factor in (0.94, 1.00, 1.06):
            scale = base * factor
            h, w = template.shape[:2]
            tw = max(8, round(w * scale))
            th = max(8, round(h * scale))
            if tw > crop.shape[1] or th > crop.shape[0]:
                continue

            variant = cv2.resize(
                template,
                (tw, th),
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
            )
            result = cv2.matchTemplate(crop, variant, cv2.TM_CCOEFF_NORMED)
            if result.size:
                best = max(best, float(cv2.minMaxLoc(result)[1]))

        return best

    def _turn_state(self, frame):
        """Return one authoritative turn result for this frame.

        Strong 'Your Turn' text is allowed to override a stale portrait-border
        reading. This avoids waiting for the portrait animation to catch up.
        """
        portrait = detect_combat_turn_owner(frame)
        text_score = self._your_turn_text_score(frame)

        # V15.20: an explicit opponent border wins over potentially lingering
        # Your Turn text.  This removes PLAYER->OPPONENT races seen in the replay.
        if portrait == "opponent":
            return {
                "owner": "opponent",
                "found": False,
                "source": "portrait",
                "score": 1.0,
                "portrait": portrait,
            }

        if text_score >= YOUR_TURN_SCORE_MIN:
            return {
                "owner": "player",
                "found": True,
                "source": "your-turn-text",
                "score": text_score,
                "portrait": portrait,
            }

        if portrait == "player":
            return {
                "owner": "player",
                "found": True,
                "source": "portrait",
                "score": 1.0,
                "portrait": portrait,
            }

        return {
            "owner": None,
            "found": False,
            "source": "none",
            "score": text_score,
            "portrait": portrait,
        }

    def _owns_turn(self, frame):
        return self._turn_state(frame)["owner"] == "player"

    def _same_actor(self, frame, rect, decision):
        """Verify current actor from A1, not from the selected skill template."""
        if self._turn_state(frame)["owner"] != "player":
            return False

        family, score, margin = self.analyzer.fast_actor_family(
            frame,
            rect,
        )

        expected = decision.get("selected_family")
        return (
            family is not None
            and expected is not None
            and family == expected
            and score >= ACTOR_A1_SCORE_MIN
            and margin >= ACTOR_A1_MARGIN_MIN
        )


    def _bar_departed(self, frame, rect, decision):
        own = [m for m in decision["skill_scan"]["matches"]
               if m["family"] == decision["selected_family"]
               and m["skill_id"] in ("A1", decision["skill"]["skill_id"])]
        if not own:
            return False
        for item in own:
            current = self.analyzer._direct_skill_match(frame, rect, item["skill_name"])
            if current is None or current["score"] >= .30:
                return False
        return True

    @staticmethod
    def _decision_key(decision):
        skill = decision.get("skill")
        return (decision.get("selected_family"), skill["skill_id"] if skill else None,
                decision.get("target_kind"), decision.get("target_slot"))

    def _your_turn(self, frame):
        # Compatibility wrapper for old callers.
        state = self._turn_state(frame)
        return {
            "found": state["owner"] == "player",
            "score": state["score"],
            "source": state["source"],
        }

    def _return_match(self, frame):
        if not os.path.exists(RETURN_TEMPLATE):
            return {"found": False, "score": 0.0, "center": None}

        return self.vision.match(
            frame,
            RETURN_TEMPLATE,
            confidence=0.74,
            grayscale=True,
            scales=(0.94, 1.00, 1.06),
            auto_roi=True,
        )

    def _save_diagnostic(self, frame, rect, decision, prefix="combat_diag"):
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            png = self.debug_dir / f"{prefix}_{stamp}.png"
            txt = self.debug_dir / f"{prefix}_{stamp}.txt"

            overlay = frame.copy()

            # Active ring regions / chosen slot.
            active_slot = decision.get("active_slot")
            geometry = decision.get("geometry") or {}
            for slot, region in (geometry.get("active_ring_regions") or {}).items():
                left, top, _, _ = rect
                x, y, w, h = region
                p1 = (x - left, y - top)
                p2 = (x - left + w, y - top + h)
                color = (0, 255, 0) if slot == active_slot else (90, 90, 90)
                cv2.rectangle(overlay, p1, p2, color, 1)

            # Physical skill circles.
            scan = decision.get("skill_scan") or {}
            for idx, slot in enumerate(scan.get("physical_slots") or [], start=1):
                sx, sy = slot["center"]
                left, top, _, _ = rect
                p = (sx - left, sy - top)
                cv2.circle(
                    overlay,
                    p,
                    max(10, slot["radius"]),
                    (255, 255, 0),
                    2,
                )
                cv2.putText(
                    overlay,
                    f"S{idx}",
                    (p[0] - 10, p[1] - slot["radius"] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 255, 0),
                    1,
                )

            cv2.imwrite(str(png), overlay)

            serializable = {
                "rect": rect,
                "active_slot": active_slot,
                "ring_ratios": decision.get("ring_ratios"),
                "selected_family": decision.get("selected_family"),
                "family_confidence": decision.get("family_confidence"),
                "slot_family_memory": decision.get("slot_family_memory"),
                "recognition_mode": scan.get("recognition_mode"),
                "reason": decision.get("reason"),
                "tree_state": decision.get("tree_state"),
                "tree_reason": decision.get("tree_reason"),
                "tree_unknown_reasons": list(decision.get("tree_unknown_reasons") or ()),
                "skill": decision.get("skill"),
                "skill_evidence": [
                    {
                        "name": item.get("skill_name"),
                        "id": item.get("skill_id"),
                        "score": item.get("score"),
                        "raw_score": item.get("raw_score", item.get("score")),
                        "combined_score": item.get("combined_score", item.get("score")),
                        "evidence_rescue": bool(item.get("evidence_rescue", False)),
                        "availability": item.get("availability"),
                        "value_ratio": item.get("value_ratio"),
                        "sat_ratio": item.get("sat_ratio"),
                        "cooldown_fraction": item.get("cooldown_fraction"),
                    }
                    for item in (scan.get("matches") or [])
                ],
                "target_slot": decision.get("target_slot"),
                "enemy_states": decision.get("enemy_states"),
                "ally_ratios": decision.get("ally_ratios"),
                "ally_tracker": decision.get("ally_tracker"),
                "physical_skill_slots": scan.get("physical_slots"),
                "top_skills": self.analyzer.top_skill_scores(decision, limit=12),
            }

            txt.write_text(
                json.dumps(serializable, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            print(f"COMBAT DIAG: {png}")
            print(f"COMBAT DIAG DATA: {txt}")
        except Exception as exc:
            print("COMBAT DIAG error:", exc)

    def _verify_action(self, rect, decision, deadline):
        """Require two observations of real turn/actor/cooldown progress.

        A glow or generic pixel change is never execution confirmation.
        Absence of a Your Turn template alone is not proof either.
        """
        end = min(deadline, time.monotonic() + 0.55)
        previous_reason = None
        hits = 0
        skill = decision["skill"]
        while time.monotonic() + .08 < end:
            self.sleep(.08)
            if self.find_raid_rect() != rect:
                return False
            fresh = self._capture(rect)
            if fresh is None:
                continue
            _check_deadline(deadline)
            reason = None
            if self._return_match(fresh).get("found"):
                reason = "result-screen"
            elif detect_combat_turn_owner(fresh) == "opponent":
                reason = "opponent-turn"
            elif self._owns_turn(fresh):
                if self._same_actor(fresh, rect, decision):
                    if skill["skill_id"] != "A1":
                        current = self.analyzer._direct_skill_match(fresh, rect, skill["skill_name"])
                        if (current and current["score"] >= SKILL_MATCH_MIN
                                and not current["available"]
                                and (current.get("blocked_visual", False)
                                     or current["value_ratio"] < .48 or current["sat_ratio"] < .32)):
                            reason = "skill-cooldown"
                else:
                    scan = self.analyzer.scan_skill_slots(
                        fresh, rect, self.analyzer.geometry(rect), identity_only=True)
                    family = scan["selected_family"]
                    if family and family != decision["selected_family"]:
                        reason = "different-champion"
            hits = hits + 1 if reason and reason == previous_reason else int(bool(reason))
            previous_reason = reason
            if hits >= 2:
                self.last_verification_reason = reason
                return True
        return False

    def _fresh_target(self, frame, rect, decision, tracker):
        geometry = self.analyzer.geometry(rect)
        skill = decision["skill"]
        kind = decision["target_kind"]

        if kind == "self_actor":
            # V15.26: self-target confirmation must be recomputed from the CURRENT
            # window geometry.  Do not blindly reuse an absolute point captured
            # on an earlier frame.  Tekteon A3 in particular was repeatedly
            # clicking the floor-ring point (too low/right on the model) and the
            # skill stayed selected.  Prefer the calibrated champion-model point
            # for the confirmed active slot; the floor ring remains a fallback.
            slot = decision.get("active_slot") or decision.get("target_slot")
            family = _family_root(decision.get("selected_family"))
            if (
                family == "tekteon"
                and slot is not None
                and geometry["ally_points"].get(slot) is not None
            ):
                point = geometry["ally_points"][slot]
                decision["target_point"] = point
                decision["target_slot"] = slot
                return slot, point, "current-actor-model-recalculated"

            # Preserve existing behaviour for all other champions.
            if decision.get("target_point") is not None:
                return decision.get("target_slot"), decision["target_point"], "current-actor-pinned"
            point, _ = self.analyzer.detect_active_actor_floor_point(frame, rect)
            if point is not None:
                decision["target_point"] = point
                return decision.get("active_slot"), point, "current-actor-floor-ring"
            if slot is not None and geometry["ally_points"].get(slot) is not None:
                point = geometry["ally_points"][slot]
                decision["target_point"] = point
                return slot, point, "current-actor-slot"
            return None, None, "current-actor-not-found"

        if kind in ("enemy", "enemy_confirm"):
            policy = decision.get("target_policy") or {}
            effects = self.analyzer._policy_effect_names(policy)
            states = self.analyzer.scan_enemy_targets(
                frame, rect, geometry, allow_recent_fallback=True,
                extra_effects=effects,
                count_buffs=policy.get("buff_count") in ("min", "max"),
            )
            locked_slot = decision.get("_locked_target_slot")
            if locked_slot is not None:
                locked = next((s for s in states if s["slot"] == locked_slot), None)
                # V15.22: retry must re-run the SAME legality policy as the first
                # target choice. Previously the sticky lock only rechecked global
                # Block Damage/Unkillable/Counterattack, so a newly recognised
                # Stoneskin, Veil or skill-specific avoid (e.g. Vestele A2) could
                # remain locked and be clicked again.
                if locked is not None and locked["alive"] and not locked.get("veil"):
                    probe, probe_reason = self.analyzer.choose_enemy_target(
                        states,
                        affinity_aware=(
                            kind == "enemy" and skill["attack_type"] == "single"
                        ),
                        lowest_hp=(
                            kind == "enemy" and skill["target_mode"] == "lowest_hp"
                        ),
                        policy=policy,
                    )
                    if probe is not None and probe["slot"] == locked_slot:
                        return (
                            locked["slot"],
                            locked["aim_point"],
                            "locked-target-revalidated+" + probe_reason,
                        )
                decision.pop("_locked_target_slot", None)
                decision.pop("_locked_target_point", None)

            if kind == "enemy_confirm":
                target, reason = self.analyzer.choose_enemy_target(
                    states,
                    affinity_aware=False,
                    lowest_hp=False,
                    policy=policy,
                )
                if target is None:
                    return None, None, "no-live-enemy"
                reason = f"aoe-confirm+{reason}"
            else:
                target, reason = self.analyzer.choose_enemy_target(
                    states,
                    affinity_aware=skill["attack_type"] == "single",
                    lowest_hp=skill["target_mode"] == "lowest_hp",
                    policy=policy,
                )
                if target is None:
                    return None, None, "no-legal-enemy"
            decision["_locked_target_slot"] = target["slot"]
            decision["_locked_target_point"] = target["aim_point"]
            return target["slot"], target["aim_point"], reason

        if kind == "ally_living":
            ally_ratios = self.analyzer.update_ally_tracker(
                frame, rect, geometry, tracker
            )
            slot, point = self.analyzer.lowest_hp_living_ally(ally_ratios, geometry)
            if point is None:
                return None, None, "no-living-ally"
            decision["target_slot"] = slot
            decision["target_point"] = point
            return slot, point, "lowest-hp-living-ally"

        if kind == "ally":
            ally_ratios = self.analyzer.update_ally_tracker(
                frame, rect, geometry, tracker
            )

            if skill.get("attack_type") == "ally_dead":
                tried = decision.setdefault("_revive_tried_points", [])
                tried_set = {
                    (int(item[0]), int(item[1]))
                    for item in tried
                    if isinstance(item, (tuple, list)) and len(item) == 2
                }

                candidates = self.analyzer.revive_target_candidates(
                    rect,
                    tracker,
                    geometry,
                    ally_ratios=ally_ratios,
                    preferred_slot=decision.get("target_slot"),
                )

                for candidate in candidates:
                    point = candidate["point"]
                    if point in tried_set:
                        continue
                    tried.append(point)
                    decision["target_slot"] = candidate["slot"]
                    decision["target_point"] = point
                    return (
                        candidate["slot"],
                        point,
                        "revive-" + candidate["reason"],
                    )

                return None, None, "revive-no-untried-target"

            slot = decision["target_slot"]
            state = tracker.get(slot, {})
            ratio = _green_hp_ratio(
                _crop_abs(frame, rect, geometry["ally_hp"][slot])
            )
            if (
                state.get("seen_alive")
                and state.get("dead")
                and ratio <= ALLY_HP_DEAD_THRESHOLD
            ):
                return slot, geometry["ally_points"][slot], "confirmed-dead-ally"
        return None, None, "no-legal-fresh-target"

    def _wait_for_skill_selection(self, rect, decision):
        """Wait until RAID has actually armed the selected skill.

        Returns:
          ("selected", frame)  - cyan rim is visible, target click is safe;
          ("progress", frame)  - turn/actor already changed (instant execution);
          ("timeout", frame)   - skill never entered selection mode.
        """
        skill = decision["skill"]
        expected_family = decision.get("selected_family")
        end = self._clock() + SKILL_SELECT_CONFIRM_TIMEOUT
        last = None
        before_actor = decision.get("_actor_floor_point_before")
        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
        move_threshold = ACTIVE_ACTOR_MOVE_CONFIRM_REF * scale

        while self._clock() < end:
            self.sleep(0.04)

            if self.find_raid_rect() != rect:
                return "progress", last

            fresh = self._capture(rect)
            if fresh is None:
                continue

            last = fresh
            turn = self._turn_state(fresh)

            if turn["owner"] != "player":
                return "progress", fresh

            if self.analyzer.selected_skill(fresh, rect, skill):
                return "selected", fresh

            # Do NOT run all-team A1 identity every 40 ms here.  Turn ownership,
            # selected-skill rim and actor-floor movement are cheaper independent
            # progress signals.  A heavier identity/cooldown check remains at timeout.
            if before_actor is not None:
                after_actor, _ = self.analyzer.detect_active_actor_floor_point(fresh, rect)
                if (
                    after_actor is not None
                    and math.dist(before_actor, after_actor) >= move_threshold
                ):
                    self.last_verification_reason = "actor-ring-progress-before-select"
                    return "progress", fresh

        # One heavier check only at timeout: some support skills execute so fast
        # that the cyan rim is never visible in a captured frame. If A2/A3 is
        # already on cooldown or the actor changed, the click DID execute.
        if last is not None and skill.get("skill_id") != "A1":
            final_scan = self.analyzer.scan_skill_slots(
                last, rect, self.analyzer.geometry(rect)
            )
            final_family = final_scan.get("selected_family")
            if (
                final_family is not None
                and expected_family is not None
                and final_family != expected_family
            ):
                self.last_verification_reason = "different-champion-at-select-timeout"
                return "progress", last
            same = next(
                (
                    item for item in final_scan.get("matches", [])
                    if item.get("skill_id") == skill.get("skill_id")
                ),
                None,
            )
            if same is not None and same.get("availability") == "unavailable":
                self.last_verification_reason = "skill-cooldown-at-select-timeout"
                return "progress", last

        return "timeout", last

    def _wait_after_target_click(self, rect, decision):
        """Confirm target consumption without prematurely switching/retrying."""
        skill = decision["skill"]
        expected_family = decision.get("selected_family")
        before_actor = decision.get("_actor_floor_point_before")
        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
        move_threshold = ACTIVE_ACTOR_MOVE_CONFIRM_REF * scale
        end = self._clock() + TARGET_ACCEPT_TIMEOUT
        last = None
        next_local_check = 0.0
        while self._clock() < end:
            self.sleep(0.04)
            if self.find_raid_rect() != rect:
                return True, last
            fresh = self._capture(rect)
            if fresh is None:
                continue
            last = fresh
            turn = self._turn_state(fresh)
            if turn["owner"] != "player":
                self.last_verification_reason = "turn-progress"
                return True, fresh
            if not self.analyzer.selected_skill(fresh, rect, skill):
                self.last_verification_reason = "selection-consumed"
                return True, fresh
            # Avoid an all-team A1 scan on every 40 ms target-confirm frame.
            if before_actor is not None:
                after_actor, _ = self.analyzer.detect_active_actor_floor_point(fresh, rect)
                if after_actor is not None and math.dist(before_actor, after_actor) >= move_threshold:
                    self.last_verification_reason = "actor-ring-changed"
                    return True, fresh

            # Some RAID animations keep the cyan selection rim visible briefly
            # even after the cast was accepted.  A local cooldown state is an
            # independent confirmation and is much cheaper than a team-wide scan.
            now = self._clock()
            if skill.get("skill_id") != "A1" and now >= next_local_check:
                next_local_check = now + 0.12
                same = self.analyzer.local_skill_state(fresh, rect, skill)
                if same is not None and same.get("availability") == "unavailable":
                    self.last_verification_reason = "skill-cooldown-after-target"
                    return True, fresh

        # One final identity check catches a champion hand-off/transform whose
        # selected rim happened to linger until the timeout boundary.
        if last is not None and expected_family is not None:
            family_now, score_now, margin_now = self.analyzer.fast_actor_family(last, rect)
            if (
                family_now is not None
                and family_now != expected_family
                and score_now >= ACTOR_A1_SCORE_MIN
                and margin_now >= ACTOR_A1_MARGIN_MIN
            ):
                self.last_verification_reason = "different-champion-after-target"
                return True, last
        return False, last


    def _execute(self, rect, decision, tracker, deadline=None):
        """Execute one skill without blind full-skill retries.

        V13.5 fixes the replay failure:
        - Fenax A1: target was clicked before target mode was fully armed;
        - Harima A3: the skill stayed selected because no enemy confirm was sent;
        - Ankora A2: the skill stayed selected because no self/ally confirm was sent.
        """
        try:
            if self.find_raid_rect() != rect:
                return "cancelled"

            fresh = self._capture(rect)
            if fresh is None:
                return "cancelled"

            # V13.8: one cheap verification first. In the normal case this
            # replaces the old pair `_same_actor()` + full `scan_skill_slots()`,
            # which both repeated A1 template work immediately before the click.
            # Any ambiguity falls back to the original full scan below.
            if self._turn_state(fresh)["owner"] != "player":
                return "cancelled"

            skill = decision["skill"]
            geometry = self.analyzer.geometry(rect)
            fast = (
                self.analyzer.fast_confirm_decision(fresh, rect, decision)
                if FAST_CONFIRM_ENABLED
                else {"ok": False, "reason": "fast-confirm-disabled"}
            )

            if fast.get("ok"):
                current = fast["skill"]
            else:
                # Safe fallback: retain the old full actor + skill verification.
                scan = self.analyzer.scan_skill_slots(
                    fresh,
                    rect,
                    geometry,
                )

                if scan.get("selected_family") != decision.get("selected_family"):
                    return "cancelled"

                current = next(
                    (
                        item
                        for item in scan.get("matches", [])
                        if item.get("skill_id") == skill.get("skill_id")
                    ),
                    None,
                )

                if current is None:
                    return "cancelled"

                if current.get("availability") != "available":
                    return "cancelled"

            # Use the fresh physical item for selection-rim tracking.
            decision["skill"] = current
            skill = current

            actor_floor_point, actor_floor_debug = self.analyzer.detect_active_actor_floor_point(
                fresh, rect
            )
            decision["_actor_floor_point_before"] = actor_floor_point
            decision["_actor_floor_debug_before"] = actor_floor_debug
            if (decision.get("target_kind") == "self_actor"
                    and decision.get("target_point") is None
                    and actor_floor_point is not None):
                decision["target_point"] = actor_floor_point

            print(
                _console_rgb(
                    "SKILL CLICK -> "
                    f"{skill['skill_name']} "
                    f"center={skill['center']} "
                    f"score={skill['score']:.3f} "
                    f"cd={skill.get('cooldown_fraction', 0.0):.3f}",
                    COLOR_SKILL_CLICK,
                )
            )

            if not self._click(
                skill["center"],
                rect,
                .07,
                .14,
                None,
            ):
                return "cancelled"

            # V15.21 KOMIDUS / MYTHICAL TRANSFORM:
            # RAID handles metamorph as A4 -> click own champion model.  Do not
            # route it through the generic targeted-skill path because the cyan
            # rim can be short/absent and the floor-ring point sits too low on
            # the model.  We already re-validated A4 immediately before this
            # click, so a short direct self-confirm is safe.
            if skill.get("attack_type") == "transform":
                self.sleep(0.12)

                target_frame = self._capture(rect)
                if target_frame is None:
                    target_frame = fresh

                # Prefer the calibrated centre of the CURRENT active ally slot.
                # This is the actual clickable champion model.
                current_slot = None
                if target_frame is not None:
                    current_slot, _ = self.analyzer.detect_active_ally_slot(
                        target_frame, rect, geometry
                    )
                if current_slot is None:
                    current_slot = decision.get("active_slot")

                self_point = (
                    geometry["ally_points"].get(current_slot)
                    if current_slot is not None
                    else None
                )
                if self_point is None:
                    self_point = decision.get("target_point")
                if self_point is None and target_frame is not None:
                    self_point, _ = self.analyzer.detect_active_actor_floor_point(
                        target_frame, rect
                    )
                if self_point is None:
                    print("TRANSFORM ABORT -> nie znaleziono modelu aktywnego championa.")
                    return "unconfirmed"

                print(
                    f"TRANSFORM SELF CLICK -> slot={current_slot} "
                    f"point={self_point} family={decision.get('selected_family')}"
                )
                if not self._click(self_point, rect, .07, .14, None):
                    return "unconfirmed"

                expected_family = decision.get("selected_family")
                expected_root = _family_root(expected_family)

                def transform_accepted(after):
                    if after is None:
                        return False
                    if self._turn_state(after)["owner"] != "player":
                        self.last_verification_reason = "transform-turn-progress"
                        return True
                    if not self.analyzer.selected_skill(after, rect, skill):
                        self.last_verification_reason = "transform-selection-consumed"
                        return True

                    family_now, score_now, margin_now = (
                        self.analyzer.fast_actor_family_for_root(
                            after, rect, expected_family
                        )
                        if expected_family is not None
                        else (None, 0.0, 0.0)
                    )
                    if (
                        family_now is not None
                        and expected_family is not None
                        and _family_root(family_now) == expected_root
                        and family_now != expected_family
                        and score_now >= A1_FIXED_MYTHICAL_ROOT_SCORE_MIN
                    ):
                        self.last_verification_reason = (
                            f"transform-form-changed:{expected_family}->{family_now}"
                        )
                        return True

                    same = self.analyzer.local_skill_state(after, rect, skill)
                    if same is not None and same.get("availability") == "unavailable":
                        self.last_verification_reason = "transform-a4-consumed"
                        return True
                    return False

                # Give the form switch/animation enough time to become visible.
                end = self._clock() + 1.35
                last_after = None
                while self._clock() < end:
                    self.sleep(0.05)
                    last_after = self._capture(rect)
                    if transform_accepted(last_after):
                        return "confirmed"

                # If A4 is STILL visibly armed, the first model click missed the
                # clickable body. Retry the model click once; never re-click A4.
                if (
                    last_after is not None
                    and self.analyzer.selected_skill(last_after, rect, skill)
                ):
                    retry_slot, _ = self.analyzer.detect_active_ally_slot(
                        last_after, rect, geometry
                    )
                    retry_point = (
                        geometry["ally_points"].get(retry_slot)
                        if retry_slot is not None
                        else self_point
                    )
                    print(
                        f"TRANSFORM SELF RETRY -> slot={retry_slot or current_slot} "
                        f"point={retry_point}"
                    )
                    if self._click(retry_point, rect, .07, .14, None):
                        end = self._clock() + 0.75
                        while self._clock() < end:
                            self.sleep(0.05)
                            last_after = self._capture(rect)
                            if transform_accepted(last_after):
                                return "confirmed"

                # We did send A4 + self-model. Avoid toggling A4 off by routing
                # through the generic retry path; the run loop will re-evaluate
                # the actor/form on fresh pixels.
                return "submitted"

            # Truly direct skills do not need a target confirmation.
            if decision["target_kind"] is None:
                # Do not re-click the whole skill from the run loop. Give the
                # game a short window to start animation / cooldown.
                end = self._clock() + 0.65
                while self._clock() < end:
                    self.sleep(0.05)
                    after = self._capture(rect)
                    if after is None:
                        continue

                    turn = self._turn_state(after)
                    if turn["owner"] != "player":
                        self.last_verification_reason = "turn-progress"
                        return "confirmed"

                    # The old loop did a full actor scan + full skill scan every
                    # 50 ms.  A local cooldown check on the button we just clicked
                    # is sufficient and dramatically cheaper.
                    if skill["skill_id"] != "A1":
                        same = self.analyzer.local_skill_state(
                            after,
                            rect,
                            skill,
                        )
                        if (
                            same is not None
                            and same.get("availability") == "unavailable"
                        ):
                            self.last_verification_reason = "skill-cooldown-local"
                            return "confirmed"

                    before_actor = decision.get("_actor_floor_point_before")
                    if before_actor is not None:
                        after_actor, _ = self.analyzer.detect_active_actor_floor_point(
                            after,
                            rect,
                        )
                        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
                        if (
                            after_actor is not None
                            and math.dist(before_actor, after_actor)
                            >= ACTIVE_ACTOR_MOVE_CONFIRM_REF * scale
                        ):
                            self.last_verification_reason = "actor-ring-progress"
                            return "confirmed"

                return "submitted"

            # Targeted / target-confirmed skill:
            # never click the target until the cyan selected-skill rim appears.
            select_state, selected_frame = self._wait_for_skill_selection(
                rect,
                decision,
            )

            if select_state == "progress":
                return "confirmed"

            if select_state != "selected":
                print(
                    "SKILL SELECT TIMEOUT -> "
                    f"{skill['skill_name']}; nie klikam celu w ciemno."
                )
                return "unconfirmed"

            # Ordinary skills keep two retries. Revive skills may need several
            # different corpse/empty-slot click points while the skill stays armed.
            target_attempts = (
                REVIVE_TARGET_MAX_ATTEMPTS
                if skill.get("attack_type") == "ally_dead"
                else TARGET_ONLY_MAX_ATTEMPTS
            )
            target_retry_delay = (
                REVIVE_TARGET_RETRY_DELAY
                if skill.get("attack_type") == "ally_dead"
                else TARGET_ONLY_RETRY_DELAY
            )

            for attempt in range(target_attempts):
                if attempt > 0:
                    backoff = min(
                        float(TARGET_RETRY_BACKOFF_MAX),
                        1.0 + float(TARGET_RETRY_BACKOFF_FACTOR) * attempt,
                    )
                    self.sleep(target_retry_delay * backoff)

                frame_for_target = (
                    selected_frame
                    if attempt == 0 and selected_frame is not None
                    else self._capture(rect)
                )
                if frame_for_target is None:
                    continue

                slot, point, reason = self._fresh_target(
                    frame_for_target,
                    rect,
                    decision,
                    tracker,
                )

                # V15.20 HARD TARGET LEGALITY:
                # Never resurrect a stale enemy point after the fresh scan rejected
                # it.  That old fallback bypassed Veil/Perfect Veil and could click
                # an impossible target for the rest of the turn.  Self/ally casts
                # may keep their pre-resolved point because legality is different.
                if point is None:
                    if decision.get("target_kind") in ("enemy", "enemy_confirm"):
                        print(
                            "TARGET ABORT -> świeży skan nie ma legalnego celu "
                            f"({reason}); nie używam starego punktu."
                        )
                        return "unconfirmed"
                    slot = decision.get("target_slot")
                    point = decision.get("target_point")
                    reason = decision.get("reason", "preselected-target")

                if point is None:
                    return "unconfirmed"

                if skill.get("attack_type") == "ally_dead":
                    label = (
                        "REVIVE TARGET CLICK"
                        if attempt == 0
                        else f"REVIVE TARGET RETRY {attempt}"
                    )
                else:
                    label = (
                        "TARGET CLICK"
                        if attempt == 0
                        else "TARGET ONLY RETRY"
                    )
                print(
                    f"{label} -> kind={decision['target_kind']} "
                    f"slot={slot} point={point} reason={reason}"
                )

                if not self._click(
                    point,
                    rect,
                    .07,
                    .14,
                    None,
                ):
                    continue

                accepted, selected_frame = self._wait_after_target_click(
                    rect,
                    decision,
                )

                if accepted:
                    return "confirmed"

                # If selection mode disappeared for another reason, do not retry.
                if selected_frame is not None and not self.analyzer.selected_skill(
                    selected_frame,
                    rect,
                    skill,
                ):
                    return "submitted"

            return "unconfirmed"

        finally:
            self.analyzer._deadline = None


    def _execute_sheep(self, rect, decision, tracker):
        """Execute the single Sheep attack without relying on champion A1 templates."""
        if self.find_raid_rect() != rect:
            return "cancelled"

        fresh = self._capture(rect)
        if fresh is None or self._turn_state(fresh)["owner"] != "player":
            return "cancelled"

        # Re-validate Sheep evidence immediately before input.
        sheep_score = self.analyzer.sheep_marker_score(fresh, rect)
        if sheep_score < SHEEP_MARKER_SCORE_MIN:
            return "cancelled"

        geometry = self.analyzer.geometry(rect)
        physical = self.analyzer.detect_skill_slots(fresh, rect, geometry)
        if len(physical) != 1:
            return "cancelled"

        current_center = physical[0]["center"]
        old_center = decision["skill"]["center"]
        scale = ((rect[2] / 1024.0) + (rect[3] / 769.0)) * 0.5
        if math.dist(current_center, old_center) > SHEEP_SKILL_CENTER_TOLERANCE_REF * scale:
            return "cancelled"

        decision["skill"]["center"] = current_center

        actor_floor_point, actor_floor_debug = (
            self.analyzer.detect_active_actor_floor_point(fresh, rect)
        )
        decision["_actor_floor_point_before"] = actor_floor_point
        decision["_actor_floor_debug_before"] = actor_floor_debug

        print(
            _console_rgb(
                "SHEEP SKILL CLICK -> "
                f"center={current_center} marker={sheep_score:.3f}",
                COLOR_SKILL_CLICK,
            )
        )

        if not self._click(current_center, rect, .07, .14, None):
            return "cancelled"

        # The normal cyan-rim detector only needs the skill center, so it also
        # works for the unknown Sheep icon.
        end = self._clock() + SKILL_SELECT_CONFIRM_TIMEOUT
        selected_frame = None
        while self._clock() < end:
            self.sleep(0.04)
            if self.find_raid_rect() != rect:
                return "confirmed"
            after = self._capture(rect)
            if after is None:
                continue
            if self._turn_state(after)["owner"] != "player":
                return "confirmed"
            if self.analyzer.selected_skill(after, rect, decision["skill"]):
                selected_frame = after
                break

        if selected_frame is None:
            print("SHEEP SELECT TIMEOUT -> nie klikam celu w ciemno.")
            return "unconfirmed"

        geometry = self.analyzer.geometry(rect)
        target, reason, tg_score = self.analyzer.choose_sheep_target(
            selected_frame, rect, geometry
        )
        if target is None:
            return "unconfirmed"

        decision["target_slot"] = target["slot"]
        decision["target_point"] = target["aim_point"]
        decision["reason"] = reason

        print(
            "SHEEP TARGET -> "
            f"slot={target['slot']} point={target['aim_point']} "
            f"reason={reason}"
        )

        if not self._click(target["aim_point"], rect, .07, .14, None):
            return "unconfirmed"

        accepted, _ = self._wait_after_target_click(rect, decision)
        return "confirmed" if accepted else "submitted"

    def run(self):
        a1_candidates, identity_scope = self.analyzer._candidate_a1_entries()
        identity_mode = (
            "exact" if len(a1_candidates) <= COMBAT_A1_EXACT_SCAN_LIMIT
            else "prefilter+bounded-exact"
        )
        print(
            "START: COMBAT V16.1 AUTONOMY -> full enemy model + state-ranked legal skills/targets + V15 safety guards; "
            f"A1 candidates={len(a1_candidates)} scope={identity_scope} mode={identity_mode}."
        )
        self.set_state(STATE_COMBAT)

        tracker = {}
        # V15.12: battle-local mapping of the green active ally slot to champion
        # family.  It is intentionally reset at the start of every battle.
        slot_family_memory = {}

        stable_key = None
        stable_hits = 0
        stable_point = None
        pending_decision = None

        latched = False
        latched_status = None
        latched_since = 0.0
        acted_decision = None
        action_attempts_for_actor = 0
        next_action_at = 0.0
        next_actor_probe_at = 0.0
        extra_turn_active = False
        # Per champion ROOT, reset every battle.  Used by one-time opening rules
        # such as Fabian A2 opener vs Gliseah.
        family_action_counts = {}
        # V16.1: execution failures are remembered only within the current
        # player-turn window.  A repeatedly unconfirmed skill is penalised by the
        # autonomous scorer instead of being selected again indefinitely.
        turn_failed_skills = {}

        last_turn_owner = None
        turn_started_at = None
        turn_wait_logged = False
        last_wait_log = 0.0
        last_return_check = 0.0

        # V15.25: timeout counts only while the SAME uncertain decision persists.
        # This is safer than arming A1 fallback from total turn age.
        decision_wait_signature = None
        decision_wait_since = None

        # V16 learning/telemetry uses only conservative battle-outcome hints.
        last_enemy_states = []
        autonomy_outcome_recorded = False

        while True:
            paused_for = self._pause_barrier()
            if paused_for >= PAUSE_STALE_AFTER_SECONDS:
                # The game did not pause with us. Never continue a pre-pause
                # confirmation/click chain from stale pixels. A latched action is
                # intentionally kept latched to avoid double-casting after resume.
                stable_key, stable_hits, stable_point = None, 0, None
                pending_decision = None
                next_action_at = 0.0
                decision_wait_signature = None
                decision_wait_since = None
                if not latched:
                    turn_started_at = None
                print(
                    f"PAUSE -> RESUME: stale decision discarded "
                    f"({paused_for:.2f}s); recapturing combat state."
                )

            rect = self.find_raid_rect()
            if rect is None:
                self.sleep(0.05)
                continue

            frame = self._capture(rect)
            if frame is None:
                self.sleep(0.025)
                continue

            now = self._clock()

            if now - last_return_check >= RETURN_CHECK_INTERVAL:
                last_return_check = now
                result = self._return_match(frame)
                if result.get("found"):
                    # V15.23 — reliable Return To Arena handling.
                    # Previously a single click was sent and CombatEngine returned
                    # immediately without checking whether RAID accepted it.  If
                    # the result overlay was still settling (especially after
                    # "Opponent left the Battle") the click could be ignored,
                    # leaving the Return To Arena button visible while the outer
                    # state machine already waited for Find Opponent.
                    point = self._screen_point(rect, result.get("center"))
                    if point is None:
                        print("COMBAT RETURN: wykryto przycisk, ale brak poprawnego punktu kliknięcia -> ponawiam skan.")
                        self.sleep(0.15)
                        continue

                    print(
                        f"COMBAT: wykryto ekran Return "
                        f"(score={float(result.get('score') or 0.0):.3f}) -> klik."
                    )
                    clicked = self._click(
                        point,
                        rect,
                        min_duration=0.10,
                        max_duration=0.20,
                    )
                    if not clicked:
                        print("COMBAT RETURN: klik anulowany przez guard -> ponawiam na świeżej klatce.")
                        self.sleep(0.18)
                        continue

                    # Do not leave combat until the button has actually gone away.
                    # This keeps all retry logic local to the result screen and
                    # cannot affect champion skill/target behaviour.
                    verify_until = self._clock() + 1.40
                    return_consumed = False
                    while self._clock() < verify_until:
                        self.sleep(0.08)
                        verify_rect = self.find_raid_rect()
                        if verify_rect is None:
                            continue
                        verify_frame = self._capture(verify_rect)
                        if verify_frame is None:
                            continue
                        verify_match = self._return_match(verify_frame)
                        if not verify_match.get("found"):
                            return_consumed = True
                            break

                    if return_consumed:
                        print("COMBAT RETURN: klik potwierdzony; przycisk zniknął.")

                        if (
                            AUTONOMY_ENABLED
                            and AUTONOMY_LEARNING_ENABLED
                            and self.autonomy.enabled
                            and not autonomy_outcome_recorded
                        ):
                            seen_allies = [
                                st for st in tracker.values() if st.get("seen_alive")
                            ]
                            all_confirmed_dead = bool(seen_allies) and all(
                                st.get("dead") for st in seen_allies
                            )
                            outcome = None
                            weight = 0.0
                            reason = "unknown-result"
                            if len(seen_allies) >= 3 and all_confirmed_dead:
                                outcome, weight, reason = False, 0.85, "all-allies-confirmed-dead"
                            elif (
                                last_turn_owner == "player"
                                and acted_decision is not None
                                and latched_status in ("submitted", "confirmed", "unconfirmed")
                            ):
                                outcome, weight, reason = True, 0.25, "result-after-player-action"

                            if outcome is not None:
                                self.autonomy.learning.record_outcome(
                                    self.active_families,
                                    self.opponent_families,
                                    bool(outcome),
                                    weight=weight,
                                )
                                autonomy_outcome_recorded = True
                            self.autonomy.telemetry.emit(
                                "battle_result_hint",
                                {
                                    "won": outcome,
                                    "weight": weight,
                                    "reason": reason,
                                    "own": list(self.active_families),
                                    "enemy": list(self.opponent_families),
                                    "last_enemy_states": last_enemy_states,
                                },
                            )
                        return

                    print(
                        "COMBAT RETURN: przycisk nadal widoczny po kliknięciu -> "
                        "nie kończę walki, ponawiam próbę."
                    )
                    self.sleep(0.20)
                    continue

            turn = self._turn_state(frame)
            owner = turn["owner"]

            # A top-level player edge still matters, but it is NOT the only way
            # a new allied champion can receive the turn.
            if owner == "player" and last_turn_owner != "player":
                turn_started_at = now
                turn_wait_logged = False
                latched = False
                latched_status = None
                acted_decision = None
                action_attempts_for_actor = 0
                stable_key, stable_hits, stable_point = None, 0, None
                pending_decision = None
                next_action_at = 0.0
                next_actor_probe_at = 0.0
                extra_turn_active = False
                decision_wait_signature = None
                decision_wait_since = None
                turn_failed_skills = {}

                print(
                    _console_rgb(
                        "TURN -> PLAYER "
                        f"source={turn['source']} "
                        f"score={turn['score']:.3f}; "
                        "uzbrajam wybór skilla.",
                        COLOR_TURN_PLAYER,
                    )
                )

            if owner == "opponent" and last_turn_owner != "opponent":
                print(
                    _console_rgb(
                        "TURN -> OPPONENT "
                        f"source={turn['source']}; czekam.",
                        COLOR_TURN_OPPONENT,
                    )
                )

            if owner != "player":
                stable_key, stable_hits, stable_point = None, 0, None
                pending_decision = None
                last_turn_owner = owner
                latched = False
                latched_status = None
                acted_decision = None
                action_attempts_for_actor = 0
                extra_turn_active = False
                decision_wait_signature = None
                decision_wait_since = None
                turn_failed_skills = {}
                self.sleep(0.035)
                continue

            last_turn_owner = "player"

            if turn_started_at is None:
                turn_started_at = now
                turn_wait_logged = False

            if now < next_action_at:
                self.sleep(0.025)
                continue

            # V15.20: wait a fraction of a second after every newly armed allied
            # actor.  This filters the transition frame where the Your Turn label
            # or old skill bar may still belong to the previous actor.
            if (
                turn_started_at is not None
                and now - turn_started_at < PLAYER_TURN_SETTLE_SECONDS
            ):
                self.sleep(0.02)
                continue

            # ------------------------------------------------------------
            # CRITICAL V13.3 FIX
            # RAID may give Fenax -> Mikage -> another ally consecutive turns
            # while owner remains PLAYER the entire time. V13.2 waited for an
            # opponent edge and therefore kept `latched=True`, skipping those
            # champions completely.
            # ------------------------------------------------------------
            if latched:
                if now >= next_actor_probe_at:
                    next_actor_probe_at = now + ACTOR_PROBE_INTERVAL

                    geometry = self.analyzer.geometry(rect)
                    current_slot, _ = self.analyzer.detect_active_ally_slot(
                        frame,
                        rect,
                        geometry,
                    )
                    previous_slot = (
                        acted_decision.get("active_slot")
                        if acted_decision
                        else None
                    )

                    slot_changed = (
                        current_slot is not None
                        and previous_slot is not None
                        and current_slot != previous_slot
                    )

                    family_now = None
                    family_score = 0.0
                    family_margin = 0.0

                    previous_family = (
                        acted_decision.get("selected_family")
                        if acted_decision
                        else None
                    )

                    # V15.13: when both physical slots are known and unchanged,
                    # another champion cannot have taken the turn.  The old code
                    # still ran a full all-team A1 scan every 120 ms here.
                    # Keep a full backup scan only when the active ring is missing.
                    if (
                        not slot_changed
                        and (current_slot is None or previous_slot is None)
                    ):
                        family_now, family_score, family_margin = (
                            self.analyzer.fast_actor_family(frame, rect)
                        )

                    # Mythical transform is the one important same-slot exception.
                    # Resolve only that champion root instead of scanning the team.
                    previous_skill_id = (
                        acted_decision.get("skill", {}).get("skill_id")
                        if acted_decision
                        else None
                    )
                    if (
                        not slot_changed
                        and current_slot is not None
                        and previous_slot == current_slot
                        and previous_family is not None
                        and previous_skill_id == "A4"
                    ):
                        (
                            family_now,
                            family_score,
                            family_margin,
                        ) = self.analyzer.fast_actor_family_for_root(
                            frame,
                            rect,
                            previous_family,
                        )

                    family_changed = (
                        family_now is not None
                        and previous_family is not None
                        and family_now != previous_family
                    )

                    if slot_changed or family_changed:
                        print(
                            "ACTOR -> NEW ALLY "
                            f"slot={previous_slot}->{current_slot} "
                            f"family={previous_family}->{family_now or '?'} "
                            f"a1={family_score:.3f}/{family_margin:.3f}; "
                            "odblokowuję nową decyzję."
                        )
                        latched = False
                        latched_status = None
                        acted_decision = None
                        action_attempts_for_actor = 0
                        stable_key, stable_hits, stable_point = None, 0, None
                        pending_decision = None
                        turn_started_at = now
                        turn_failed_skills = {}
                        turn_wait_logged = False
                        next_action_at = 0.0
                        extra_turn_active = False
                        continue

                    # V15.14 generic continued/extra-turn detector.
                    #
                    # The 2026-10-01 replay shows Tekteon A3 going on cooldown
                    # while the SAME actor still owns a fresh usable turn.  The
                    # old code re-armed only Maria, so Tekteon stayed latched and
                    # never reached the next priority branch (A2).
                    #
                    # Safety: do not infer from the portrait alone.  We require:
                    #   1) same physical ally slot,
                    #   2) same champion root's A1 visible again,
                    #   3) previous non-A1/non-transform skill visibly on cooldown.
                    # This also preserves Maria's A2-after-extra-turn rule.
                    previous_skill = (
                        acted_decision.get("skill")
                        if acted_decision is not None
                        else None
                    )
                    previous_skill_id = (
                        previous_skill.get("skill_id")
                        if previous_skill is not None
                        else None
                    )
                    same_slot = (
                        current_slot is not None
                        and previous_slot is not None
                        and current_slot == previous_slot
                    )

                    if (
                        previous_skill is not None
                        and previous_skill_id not in (None, "A1", "A4")
                        and previous_family is not None
                        and same_slot
                        and now - latched_since >= CONTINUED_TURN_REARM_DELAY
                    ):
                        (
                            same_family,
                            same_family_score,
                            same_family_margin,
                        ) = self.analyzer.fast_actor_family_for_root(
                            frame,
                            rect,
                            previous_family,
                        )
                        previous_now = self.analyzer.local_skill_state(
                            frame,
                            rect,
                            previous_skill,
                        )

                        if (
                            same_family is not None
                            and _family_root(same_family) == _family_root(previous_family)
                            and previous_now is not None
                            and previous_now.get("availability") == "unavailable"
                        ):
                            print(
                                "ACTOR -> CONTINUED TURN "
                                f"family={same_family}; "
                                f"previous={previous_skill_id} cooldown; "
                                f"a1={same_family_score:.3f}/{same_family_margin:.3f}; "
                                "odblokowuję następny skill z priority."
                            )
                            latched = False
                            latched_status = None
                            acted_decision = None
                            action_attempts_for_actor = 0
                            stable_key, stable_hits, stable_point = None, 0, None
                            pending_decision = None
                            turn_started_at = now
                            turn_wait_logged = False
                            next_action_at = 0.0
                            extra_turn_active = True
                            continue

                    # V13.5: no full-skill recovery here.
                    # _execute() already performs a target-only retry while the
                    # selected skill remains armed. Re-clicking the whole skill
                    # can deselect it and was the source of duplicate actions.

                self.sleep(0.025)
                continue

            # V13.8: after one full decision, the second confirmation frame
            # verifies only the expected A1 + chosen physical skill. This keeps
            # the two-frame safety rule while avoiding a second full decision
            # tree / ally tracker / target scan in the common case.
            fast_confirmed = False
            decision = None

            if (
                FAST_CONFIRM_ENABLED
                and CONFIRM_FRAMES == 2
                and pending_decision is not None
            ):
                fast = self.analyzer.fast_confirm_decision(
                    frame,
                    rect,
                    pending_decision,
                )
                if fast.get("ok"):
                    decision = pending_decision
                    decision["skill"] = fast["skill"]
                    fast_confirmed = True
                    pending_decision = None
                    stable_hits = CONFIRM_FRAMES
                else:
                    # V15.11 IMPORTANT:
                    # A failed cheap confirm is NOT evidence that the first full
                    # decision was wrong.  Keep its stability sample and run the
                    # full analyzer on this second frame.  If the full decision
                    # matches, it becomes the required independent confirmation.
                    #
                    # The previous reset caused an infinite 1/2-confirm loop for
                    # champions whose A1 was valid for full recognition (~0.60+)
                    # but below FAST_CONFIRM_A1_SCORE_MIN (0.72), e.g. Vestele.
                    pending_decision = None

            if decision is None:
                fallback_ready = bool(
                    DECISION_ALLOW_FALLBACK
                    and decision_wait_since is not None
                    and (now - decision_wait_since) >= float(DECISION_UNKNOWN_TIMEOUT)
                )
                decision_started = time.perf_counter()
                decision = self.analyzer.choose_decision(
                    frame,
                    rect,
                    tracker,
                    slot_family_memory,
                    allow_a1_fallback=fallback_ready,
                    combat_context={
                        "extra_turn": extra_turn_active,
                        "family_action_counts": dict(family_action_counts),
                        "turn_failed_skills": dict(turn_failed_skills),
                    },
                )
                decision["_analysis_ms"] = (
                    time.perf_counter() - decision_started
                ) * 1000.0
                if decision.get("enemy_states"):
                    last_enemy_states = [
                        dict(x) for x in (decision.get("enemy_states") or ())
                    ]

                # Track only stable uncertainty.  A changed family/reason restarts
                # the timer instead of inheriting an old wait from the same turn.
                if decision.get("skill") is None and decision.get("tree_state") == "wait":
                    wait_signature = (
                        decision.get("selected_family"),
                        decision.get("tree_reason"),
                        tuple(decision.get("tree_unknown_reasons") or ()),
                    )
                    if wait_signature != decision_wait_signature:
                        decision_wait_signature = wait_signature
                        decision_wait_since = now
                    elif decision_wait_since is None:
                        decision_wait_since = now
                else:
                    decision_wait_signature = None
                    decision_wait_since = None

            if self.consume_diagnostic is not None and self.consume_diagnostic():
                self._save_diagnostic(frame, rect, decision)

            skill = decision.get("skill")

            if skill is None:
                stable_key, stable_hits, stable_point = None, 0, None
                pending_decision = None

                elapsed = (
                    self._clock() - turn_started_at
                    if turn_started_at is not None
                    else 0.0
                )

                # V14.0: Harima (or ANY champion) in Sheep form no longer waits
                # out the turn just because its normal A1 family cannot be read.
                # We only enter this fallback after 2 seconds and only with two
                # independent Sheep signals: Sheep marker + one physical skill.
                if (
                    decision.get("selected_family") is None
                    and elapsed >= SHEEP_FALLBACK_DELAY_SECONDS
                ):
                    sheep_decision = self.analyzer.sheep_fallback_decision(
                        frame, rect, tracker
                    )
                    if sheep_decision is not None:
                        print(
                            "SHEEP FALLBACK -> "
                            f"turn_age={elapsed:.2f}s "
                            f"marker={sheep_decision['family_confidence']:.3f}; "
                            "wykonuję jedyny atak."
                        )
                        status = self._execute_sheep(
                            rect, sheep_decision, tracker
                        )
                        print(
                            f"ACTION {status.upper()} -> skill_sheep_a1"
                        )

                        acted_decision = sheep_decision
                        action_attempts_for_actor += 1
                        latched = status in ("submitted", "confirmed")
                        latched_status = status if latched else None
                        latched_since = self._clock() if latched else 0.0
                        next_action_at = self._clock() + (
                            0.0 if latched else 0.25
                        )
                        turn_wait_logged = False
                        continue

                if not turn_wait_logged:
                    print(
                        "TURN PLAYER: wykryta od "
                        f"{elapsed:.2f}s; czekam tylko na gotowy pasek/skille. "
                        f"family={decision.get('selected_family')} "
                        f"reason={decision.get('tree_reason') or decision.get('reason')}"
                    )
                    turn_wait_logged = True
                    last_wait_log = now
                elif now - last_wait_log >= max(1.0, COMBAT_NO_SKILL_LOG_SECONDS):
                    print(
                        f"COMBAT WAIT: family={decision.get('selected_family')} "
                        f"tree={decision.get('tree_reason')} "
                        f"unknown={list(decision.get('tree_unknown_reasons') or ())} "
                        f"wait_age={(now - decision_wait_since) if decision_wait_since is not None else 0.0:.2f}s "
                        f"analysis={decision.get('_analysis_ms', 0.0):.1f}ms "
                        f"top={self.analyzer.top_skill_scores(decision, 6)}"
                    )
                    last_wait_log = now

                self.sleep(0.025)
                continue

            key = self._decision_key(decision)
            point = skill["center"]

            if not fast_confirmed:
                close = (
                    stable_point is not None
                    and math.dist(point, stable_point) <= 14
                )

                stable_hits = (
                    stable_hits + 1
                    if key == stable_key and close
                    else 1
                )
                stable_key = key
                stable_point = point

                if stable_hits < CONFIRM_FRAMES:
                    # Keep the complete first-frame decision for the cheap
                    # independent confirmation on the next frame.
                    if FAST_CONFIRM_ENABLED and CONFIRM_FRAMES == 2:
                        pending_decision = decision
                    self.sleep(0.025)
                    continue

            reaction = (
                self._clock() - turn_started_at
                if turn_started_at is not None
                else 0.0
            )

            print(
                f"DECISION -> champ={decision['selected_family']} "
                f"{skill['skill_name']} "
                f"priority={decision.get('tree_priority')} "
                f"target={decision['target_slot']} "
                f"reason={decision['reason']} "
                f"utility={((decision.get('autonomy_skill_scores') or {}).get(skill.get('skill_id'), {}) or {}).get('score', 'legacy')} "
                f"turn_age={reaction:.2f}s "
                f"analysis={decision.get('_analysis_ms', 0.0):.1f}ms"
            )

            status = self._execute(
                rect,
                decision,
                tracker,
                None,
            )

            print(
                f"ACTION {status.upper()} -> "
                f"{skill['skill_name']}"
            )

            if status == "unconfirmed":
                failed_root = _family_root(decision.get("selected_family"))
                failed_sid = str(skill.get("skill_id") or "").upper()
                if failed_root and failed_sid:
                    failure_key = f"{failed_root}:{failed_sid}"
                    turn_failed_skills[failure_key] = int(turn_failed_skills.get(failure_key, 0)) + 1
                    print(
                        f"AUTONOMY RELIABILITY: {failure_key} unconfirmed x"
                        f"{turn_failed_skills[failure_key]} -> obniżam utility w tej turze."
                    )

            acted_decision = decision
            action_attempts_for_actor += 1
            if status in ("submitted", "confirmed", "unconfirmed"):
                acted_family = _family_root(decision.get("selected_family"))
                if acted_family:
                    family_action_counts[acted_family] = (
                        int(family_action_counts.get(acted_family, 0)) + 1
                    )
            extra_turn_active = False
            latched = status in (
                "submitted",
                "confirmed",
                "unconfirmed",
            )
            latched_status = status if latched else None
            latched_since = self._clock() if latched else 0.0
            next_actor_probe_at = 0.0

            stable_key, stable_hits, stable_point = None, 0, None
            pending_decision = None
            next_action_at = self._clock() + min(
                0.12,
                COMBAT_ACTION_LOCK_SECONDS,
            )

            self.sleep(0.025)

