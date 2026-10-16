"""Live Arena — poprawka wyboru lidera: centralny symbol bana + kontrola przed kliknięciem."""

from datetime import datetime, timedelta
import ctypes
from ctypes import wintypes
import os
import random
import itertools
import time
import sys
import re
from pathlib import Path

# MUSI być przed closeadds/pyautogui, aby wszystkie biblioteki używały
# tego samego fizycznego układu współrzędnych Windows.
from livearena_windows import enable_dpi_awareness
enable_dpi_awareness()

import closeadds
import errorhandling
from errorhandling import errorManager
from flags import flagInstance

# Live Arena ma działać niezależnie od CvC; nie zmienia to flagi globalnej
# używanej przez pozostałe moduły bota.
LIVEARENA_IGNORE_CVC_GATE = True
import pyautogui
import cv2
import numpy as np
import keyboard
import shared

from livearena_config import (
  MY_CHAMPIONS, LEAD_CHAMPIONS, LEADER_PRIORITY, OWN_TEAM_SLOT_POINTS,
  BAN_CHAMPIONS, SKILL_PLAN, GLOBAL_SKILL_PLAN, SKILL_RULES_BY_FAMILY,
  ALLY_SLOT_POINTS, ALLY_HP_REGIONS, ALLY_DEAD_CONFIRM_FRAMES,
  STATE_IDLE, STATE_MATCHMAKING, STATE_PICK, STATE_BAN, STATE_LEADER,
  STATE_LOADING, STATE_COMBAT, STATE_RESULT, STATE_DONE, STATE_CONFIRM_FRAMES,
  STATE_TICK_SECONDS, DRAFT_URGENT_AFTER, COMBAT_ACTION_BUDGET_SECONDS,
  PERF_LOG_INTERVAL_SECONDS, REFERENCE_SIZE,
  TEMPLATE_REFERENCE_SIZE, ROI_CHAMPION_ROSTER, ROI_ENEMY_TEAM,
  ARENA_CLOSED_RECHECK_SECONDS, ARENA_READY_TIMEOUT_SECONDS,
  MATCHMAKING_CLICK_VERIFY_SECONDS,
  AUTONOMY_ENABLED, AUTONOMY_DRAFT_ENABLED,
  AUTONOMY_DRAFT_SCAN_BATCH, AUTONOMY_DRAFT_FULL_SCAN_STATES,
  ACTIVE_DRAFT_PROFILE, DRAFT_PROFILES_DIR, DRAFT_PROFILE_ENV,
  LEADER_SELECTED_BORDER_RATIO_MIN,
  LEADER_SELECTED_BORDER_MARGIN,
  LEADER_TEMPLATE_CONFIDENCE,
  template_roi_for,
)
from livearena_vision import VisionEngine
from livearena_runtime import HumanMouse
from livearena_combat import CombatEngine, detect_combat_turn_owner, combat_turn_debug
from draft_engine import (
  load_profile, profile_name_from_argv, normalize_champion,
)
from livearena_calibration import (
  LEADER_SLOT_CENTERS,
  leader_slot_point as calibrated_leader_slot_point,
  leader_card_region as calibrated_leader_card_region,
  leader_confirm_point as calibrated_leader_confirm_point,
)

_draft_profile_name = profile_name_from_argv(
  sys.argv,
  default_name=ACTIVE_DRAFT_PROFILE,
  env_name=DRAFT_PROFILE_ENV,
)

# Explicit profile selection must never silently turn into another draft
# strategy.  CLI or environment profile requests are treated as intentional.
_draft_profile_explicit = (
  "--draft-profile" in sys.argv
  or bool(os.environ.get(DRAFT_PROFILE_ENV))
)

DRAFT_PROFILE = load_profile(
  _draft_profile_name,
  profiles_dir=DRAFT_PROFILES_DIR,
  fallback_pick=MY_CHAMPIONS,
  fallback_ban=BAN_CHAMPIONS,
  fallback_leader=LEADER_PRIORITY,
)

# Legacy globals remain for compatibility with diagnostics/preload. Their values
# now come from the active JSON profile rather than being hard-coded per user.
my_champions = [DRAFT_PROFILE.pick_template_stem(x) for x in DRAFT_PROFILE.pick_priority]
if not my_champions:
  my_champions = list(MY_CHAMPIONS)
lead_champions = list(LEAD_CHAMPIONS)
ban_champions = [f"arena_live_ban_{normalize_champion(x)}" for x in DRAFT_PROFILE.ban_priority]
if not ban_champions:
  ban_champions = list(BAN_CHAMPIONS)
speed_champions = []
_draft_profile_logged = False


# Maksymalny koszt automatycznie kupowanego Live Arena Refill.
# Obecny bilder ma wzorce 10 i 20 gemów. Jeśli później dodasz wzorzec 25,
# kod obsłuży go automatycznie. Każda inna/nieznana cena jest odrzucana.
MAX_GEM_REFILL_COST = 25
PAID_REFILL_ALLOWED_COSTS = (10, 20, 25)


# Console colours (24-bit ANSI / TrueColor).
# Only log presentation changes; combat/draft timing and analysis are untouched.
COLOR_STATE = (128, 128, 128)  # #808080
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
      kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
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


HELLO_WORLD_COLOR = (190, 80, 255)  # purple


def _console_rgb_italic(text, rgb):
  """Purple/colour + ANSI italic for the startup greeting."""
  if not getattr(sys.stdout, "isatty", lambda: False)():
    return text
  _init_virtual_terminal_once()
  r, g, b = rgb
  return f"\x1b[3;38;2;{r};{g};{b}m{text}{_ANSI_RESET}"


def _print_startup_greeting():
  """Shown once on every arenalive.py start, independent of draft profile."""
  print(_console_rgb_italic("HELLO WORLD!", HELLO_WORLD_COLOR))



_bot_paused = False
_pause_started_real = None
_paused_total = 0.0
_hotkeys_installed = False
_templates_preloaded = False

# Okno RAID / logowanie geometrii.
_last_raid_rect_logged = None
_last_raid_missing_log_at = 0.0

# State machine runtime.
_current_live_state = "START"
_state_entered_at = time.monotonic()
_diagnostic_requested = False
_arena_closed_until = 0.0
_last_arena_closed_log_at = 0.0

# V15.17: po Return RAID potrafi przez kilka sekund pokazywać
# "Processing Results..." zanim ponownie udostępni Find Opponent.
# W tym znanym stanie przejściowym brak przycisku NIE oznacza zamkniętej Areny.
POST_BATTLE_RESULTS_TIMEOUT_SECONDS = 30.0

# Moduły wydajności / bezpieczeństwa.
VISION = VisionEngine(
  reference_size=REFERENCE_SIZE,
  roi_resolver=template_roi_for,
  template_reference_size=TEMPLATE_REFERENCE_SIZE,
)
MOUSE = HumanMouse(edge_margin=2)


def _toggle_bot_pause():
  """Klawisz ` przełącza PAUZA / AKTYWNY i zamraża zegar decyzji."""
  global _bot_paused, _pause_started_real, _paused_total
  now = time.monotonic()

  if not _bot_paused:
    _bot_paused = True
    _pause_started_real = now
    print("\n========== BOT WSTRZYMANY (`) ==========\n")
    return

  # Resume: doliczamy pełny czas pauzy. _active_time() dzięki temu nie
  # przeskakuje do przodu i żaden draft/confirm timeout nie wygasa na pauzie.
  paused_for = max(0.0, now - (_pause_started_real or now))
  _paused_total += paused_for
  _pause_started_real = None
  _bot_paused = False
  print(
    "\n========== BOT AKTYWNY (`) ========== "
    f"[pauza {paused_for:.2f}s]\n"
  )


def _request_diagnostic_snapshot():
  """TAB zleca snapshot diagnostyczny; ciężka praca odbywa się w głównej pętli."""
  global _diagnostic_requested
  _diagnostic_requested = True


def _install_pause_hotkey():
  """
  Globalne hotkeye instalowane TYLKO RAZ na proces raid.py:
    `   = pauza / wznowienie
    TAB = jednorazowy snapshot diagnostyczny
  """
  global _hotkeys_installed
  if _hotkeys_installed:
    return

  try:
    keyboard.add_hotkey("`", _toggle_bot_pause, suppress=False)
    print("Hotkey aktywny: ` = pauza / wznowienie bota")
  except Exception as exc:
    print("Nie udało się zarejestrować hotkey `:", exc)

  try:
    keyboard.add_hotkey("tab", _request_diagnostic_snapshot, suppress=True)
    print("Hotkey aktywny: TAB = snapshot diagnostyczny")
  except Exception as exc:
    print("Nie udało się zarejestrować hotkey TAB:", exc)

  _hotkeys_installed = True


def _active_time():
  """Monotoniczny czas AKTYWNEJ pracy; podczas pauzy stoi w miejscu."""
  now = time.monotonic()
  paused = _paused_total
  if _bot_paused and _pause_started_real is not None:
    paused += max(0.0, now - _pause_started_real)
  return now - paused


def _wait_if_paused():
  """Blokuje akcje do resume i zwraca realny czas spędzony na barierze."""
  started = time.monotonic()
  while _bot_paused:
    time.sleep(0.03)
  return max(0.0, time.monotonic() - started)


def _pauseable_sleep(seconds):
  """Sleep liczony w czasie aktywnym — pauza nie zużywa opóźnienia."""
  end_time = _active_time() + max(0.0, seconds)
  while _active_time() < end_time:
    _wait_if_paused()
    remaining = end_time - _active_time()
    if remaining <= 0:
      break
    time.sleep(min(0.03, remaining))


class _PauseResumeAbort(RuntimeError):
  pass


def _human_click(target, min_duration=0.20, max_duration=0.55):
  """Click Guard: po pauzie stary punkt jest odrzucany i skanowany od nowa."""
  # Jeśli weszliśmy do funkcji już na pauzie, nie kończymy tego starego kliknięcia.
  if _wait_if_paused() >= 0.02:
    return False

  rect = _last_raid_rect_logged
  if rect is None:
    rect = _find_raid_client_rect()

  def pause_guard():
    # HumanMouse wywołuje guard podczas sekwencji wejścia. Jeśli pauza nastąpiła
    # po wybraniu punktu/klatki, przerwij zamiast kliknąć po resume.
    if _wait_if_paused() >= 0.02:
      raise _PauseResumeAbort()

  try:
    return MOUSE.click(
      target,
      window_rect=rect,
      min_duration=min_duration,
      max_duration=max_duration,
      wait_if_paused=pause_guard,
    )
  except _PauseResumeAbort:
    print("CLICK GUARD: pauza zmieniła stan UI -> anuluję stary klik.")
    return False


def _state_log_line(old_state, new_state):
  return f"========== STATE: {old_state} -> {new_state} =========="


def _set_live_state(new_state):
  """Zmienia stan tylko raz i loguje wyłącznie realne przejścia."""
  global _current_live_state, _state_entered_at

  if new_state == _current_live_state:
    return

  old_state = _current_live_state
  _current_live_state = new_state
  _state_entered_at = _active_time()

  # Każda zmiana STATE ma dokładnie ten sam format.
  print(_console_rgb(_state_log_line(old_state, new_state), COLOR_STATE))


def _capture_raid_frame(rect=None):
  """Szybki capture clienta RAID przez MSS (fallback pyautogui)."""
  if rect is None:
    rect = _find_raid_client_rect()
  if rect is None:
    return None, None
  return rect, VISION.capture(rect)


def _crop_abs_region(frame_bgr, raid_rect, region):
  return VISION.crop_abs_region(frame_bgr, raid_rect, region)


def _frame_match(
  frame_bgr,
  template_path,
  confidence=0.80,
  grayscale=False,
  scales=(1.00,),
  roi=None,
  auto_roi=True,
):
  """Match z cache; profil draftu może podać jawne ROI bez pełnego ekranu."""
  return VISION.match(
    frame_bgr,
    template_path,
    confidence=confidence,
    grayscale=grayscale,
    scales=scales,
    roi=roi,
    auto_roi=auto_roi if roi is None else False,
  )


def _frame_screen_point(raid_rect, match):
  if raid_rect is None or not match or not match.get("center"):
    return None
  left, top, _, _ = raid_rect
  cx, cy = match["center"]
  return (left + int(cx), top + int(cy))


def _return_to_arena_after_opponent_left(timeout=6.0):
  """
  V15.24: opponent may leave during PICK/BAN/LEADER, before CombatEngine starts.

  In that path the old code clicked the middle of the "Opponent left" banner and
  returned from _conductBattle immediately.  The outer loop then waited for
  Find Opponent while RAID was still showing the result screen and the real
  RETURN TO ARENA button.

  Keep this recovery local to the draft-disconnect path: find the existing
  arena_live_return template, click it, and do not report success until the
  button has actually disappeared.  No draft/combat/target logic is changed.
  """
  deadline = _active_time() + max(0.5, float(timeout))
  return_template = "./bilder/arena_live_return.png"

  while _active_time() < deadline:
    _wait_if_paused()
    raid_rect, frame_bgr = _capture_raid_frame()
    if raid_rect is None or frame_bgr is None:
      _pauseable_sleep(0.12)
      continue

    match = _frame_match(
      frame_bgr,
      return_template,
      confidence=0.74,
      grayscale=True,
      scales=(0.94, 1.00, 1.06),
    )
    if not match.get("found"):
      # The result overlay can settle for a short moment before the button is
      # drawable.  Keep polling instead of falling through to POST-BATTLE.
      _pauseable_sleep(0.12)
      continue

    point = _frame_screen_point(raid_rect, match)
    if point is None:
      _pauseable_sleep(0.12)
      continue

    print(
      "OPPONENT LEFT: wykryto RETURN TO ARENA "
      f"(score={float(match.get('score') or 0.0):.3f}) -> klik."
    )
    if not _human_click(point, 0.12, 0.24):
      print("OPPONENT LEFT: klik anulowany przez guard -> ponawiam.")
      _pauseable_sleep(0.15)
      continue

    # Verify consumption.  A single click can be ignored while the result
    # overlay is animating, so only leave _conductBattle after the button is gone.
    verify_until = _active_time() + 1.50
    while _active_time() < verify_until:
      _pauseable_sleep(0.08)
      verify_rect, verify_frame = _capture_raid_frame()
      if verify_rect is None or verify_frame is None:
        continue

      verify = _frame_match(
        verify_frame,
        return_template,
        confidence=0.74,
        grayscale=True,
        scales=(0.94, 1.00, 1.06),
      )
      if not verify.get("found"):
        print("OPPONENT LEFT: RETURN TO ARENA potwierdzone; przycisk zniknął.")
        return True

    print(
      "OPPONENT LEFT: RETURN TO ARENA nadal widoczne po kliknięciu -> "
      "ponawiam, nie przechodzę jeszcze do POST-BATTLE."
    )
    _pauseable_sleep(0.18)

  print("OPPONENT LEFT: nie udało się potwierdzić RETURN TO ARENA; pozostaję w obsłudze wyniku.")
  return False


def _empty_match():
  return {
    "found": False,
    "score": 0.0,
    "box": None,
    "center": None,
    "scale": None,
  }


def _phase_matches(frame_bgr, current_state=None):
  """
  State-aware phase detection.

  Stara wersja na KAŻDYM ticku sprawdzała jednocześnie:
  Your Turn + Pick + Ban + Leader, każdy po kilku skalach.
  Na filmie dało to match_avg ~205 ms.

  Teraz:
    PICK   -> YourTurn + Pick + Ban
    BAN    -> YourTurn + Ban + Leader
    LEADER -> YourTurn + Leader
  Diagnostyka (current_state=None) nadal skanuje wszystkie fazy.
  """
  result = {
    "your_turn": _frame_match(
      frame_bgr,
      "./bilder/arena_live_your_turn.PNG",
      confidence=0.76,
      grayscale=False,
      scales=(1.00,),
    ),
    STATE_PICK: _empty_match(),
    STATE_BAN: _empty_match(),
    STATE_LEADER: _empty_match(),
  }

  scan_pick = current_state in (None, STATE_PICK)
  scan_ban = current_state in (None, STATE_PICK, STATE_BAN)
  scan_leader = current_state in (None, STATE_BAN, STATE_LEADER)

  if scan_pick:
    result[STATE_PICK] = _frame_match(
      frame_bgr,
      "./bilder/arena_live_pick_your_champions.PNG",
      confidence=0.80,
      grayscale=True,
      scales=(1.00,),
    )

  if scan_ban:
    result[STATE_BAN] = _frame_match(
      frame_bgr,
      "./bilder/live_arena_ban_champions.PNG",
      confidence=0.80,
      grayscale=False,
      scales=(1.00,),
    )

  if scan_leader:
    result[STATE_LEADER] = _frame_match(
      frame_bgr,
      "./bilder/live_arena_pick_leader.PNG",
      confidence=0.80,
      grayscale=False,
      # 1024x768 i referencja 1024x769 różnią się o piksel; dodatkowa
      # skala zapobiega obcięciu wysokości napisu przez matcher.
      scales=(1.00, 1.01),
    )

  return result


def _observed_phase(matches):
  # Późniejsze fazy mają pierwszeństwo, jeśli stary tekst chwilę jeszcze znika.
  if matches[STATE_LEADER]["found"]:
    return STATE_LEADER
  if matches[STATE_BAN]["found"]:
    return STATE_BAN
  if matches[STATE_PICK]["found"]:
    return STATE_PICK
  return None


def _stable_phase_transition(ctx, observed):
  """Wymaga dwóch kolejnych klatek tej samej NOWEJ fazy."""
  current = ctx["state"]

  if observed is None or observed == current:
    ctx["phase_candidate"] = None
    ctx["phase_candidate_hits"] = 0
    return None

  if observed == ctx.get("phase_candidate"):
    ctx["phase_candidate_hits"] += 1
  else:
    ctx["phase_candidate"] = observed
    ctx["phase_candidate_hits"] = 1

  if ctx["phase_candidate_hits"] >= STATE_CONFIRM_FRAMES:
    ctx["phase_candidate"] = None
    ctx["phase_candidate_hits"] = 0
    return observed

  return None


def _update_turn_clock(ctx, your_turn):
  now = _active_time()
  was_turn = ctx.get("your_turn_active", False)

  if your_turn and not was_turn:
    ctx["turn_started_at"] = now
  elif not your_turn:
    ctx["turn_started_at"] = None

  ctx["your_turn_active"] = your_turn


def _turn_elapsed(ctx):
  started = ctx.get("turn_started_at")
  if started is None:
    return 0.0
  return max(0.0, _active_time() - started)


def _draft_delay(ctx, minimum=1.5, maximum=3.0):
  """
  Zachowuje ludzkie 1.5-3.0 s, ale jeżeli bot późno zauważył turę,
  skraca opóźnienie, żeby nie oddać ruchu przez timeout.
  """
  if _turn_elapsed(ctx) >= DRAFT_URGENT_AFTER:
    return random.uniform(0.15, 0.45)
  return random.uniform(minimum, maximum)



# Nazwy spotykane w starszych profilach / assetach.  Resolver naprawia je
# centralnie zamiast wymagać wielu kopii tego samego PNG w ./bilder.
_TEMPLATE_CHAMPION_ALIASES = {
  "shu-zhen": ("shu_zhen", "shuzhen", "shu-zhen"),
  "shuzhen": ("shu_zhen", "shuzhen", "shu-zhen"),
  "shu_zhen": ("shu_zhen", "shuzhen", "shu-zhen"),
  # Literówki znalezione w aktywnym profilu Symbiont / logu preloadu.
  "tekreon": ("tekteon", "tekreon"),
  "solonaar": ("solonar", "solonaar"),
}


def _draft_template_path(stem):
  """
  Resolve a bilder template case-insensitively, with safe aliases/fallbacks.

  Poza różnicą .PNG/.png obsługuje historyczne warianty nazw championa oraz
  równoważne portrety przeciwnika:
    ban_* <-> enemy_* <-> opponent_* -> arena_live_*
    lead_* -> arena_live_*

  Dzięki temu profil nie przestaje działać tylko dlatego, że asset na dysku ma
  np. shu_zhen zamiast shu-zhen albo enemy_fabian zamiast ban_fabian.
  """
  if not stem:
    return None

  raw = str(stem).strip()
  if not raw:
    return None

  # 1) Najpierw dokładna ścieżka podana przez wywołującego.
  direct = Path(raw)
  if direct.is_file():
    return str(direct)

  root = Path("./bilder")
  if not root.is_dir():
    return None

  # Jedna mapa nazw na wywołanie; katalog ma <1000 plików, więc jest to tanie,
  # a usuwa wielokrotne iterowanie po nim dla każdego aliasu.
  try:
    by_lower = {
      item.name.lower(): str(item)
      for item in root.iterdir()
      if item.is_file()
    }
  except Exception:
    return None

  # 2) Dokładna nazwa pliku w ./bilder, niezależnie od wielkości liter.
  raw_name = direct.name
  if not direct.suffix:
    raw_name += ".PNG"
  hit = by_lower.get(raw_name.lower())
  if hit:
    return hit

  # 3) Zbuduj bezpieczne warianty semantyczne dla dynamicznych template'ów.
  base = direct.stem if direct.suffix else direct.name
  base_lower = base.lower()

  role_prefixes = (
    "arena_live_opponent_",
    "arena_live_enemy_",
    "arena_live_ban_",
    "arena_live_lead_",
    "arena_live_",
  )

  prefix = None
  champion = None
  for candidate_prefix in role_prefixes:
    if base_lower.startswith(candidate_prefix):
      prefix = candidate_prefix
      champion = base_lower[len(candidate_prefix):]
      break

  if prefix is None or not champion:
    return None

  aliases = _TEMPLATE_CHAMPION_ALIASES.get(champion, (champion,))

  if prefix == "arena_live_ban_":
    role_order = (
      "arena_live_ban_",
      "arena_live_enemy_",
      "arena_live_opponent_",
      "arena_live_",
    )
  elif prefix == "arena_live_enemy_":
    role_order = (
      "arena_live_enemy_",
      "arena_live_opponent_",
      "arena_live_ban_",
      "arena_live_",
    )
  elif prefix == "arena_live_opponent_":
    role_order = (
      "arena_live_opponent_",
      "arena_live_enemy_",
      "arena_live_ban_",
      "arena_live_",
    )
  elif prefix == "arena_live_lead_":
    role_order = ("arena_live_lead_", "arena_live_")
  else:
    # Dla naszych picków nie mieszamy portretu rosteru z kartą przeciwnika.
    role_order = ("arena_live_",)

  seen = set()
  for alias in aliases:
    for role in role_order:
      filename = f"{role}{alias}.png".lower()
      if filename in seen:
        continue
      seen.add(filename)
      hit = by_lower.get(filename)
      if hit:
        return hit

  return None


def _combat_condition_opponent_names():
  """Enemy names referenced by combat-only opening conditions."""
  names = set()
  for family_rules in SKILL_RULES_BY_FAMILY.values():
    if not isinstance(family_rules, dict):
      continue
    for rule in family_rules.values():
      if not isinstance(rule, dict):
        continue
      for name in rule.get("opening_skip_if_enemy_any", ()):
        key = normalize_champion(name)
        if key:
          names.add(key)
  return names


def _opponent_detection_stems(champion):
  """Profile stems + safe spelling aliases used by combat conditions."""
  champion_key = normalize_champion(champion)
  stems = list(DRAFT_PROFILE.enemy_template_stems(champion_key))

  aliases = {
    # User assets historically use both spellings.
    "gliseah": ("gliseah", "glicea"),
  }.get(champion_key, (champion_key,))

  for alias in aliases:
    for stem in (
      f"arena_live_enemy_{alias}",
      f"arena_live_opponent_{alias}",
      f"arena_live_{alias}",
    ):
      if stem not in stems:
        stems.append(stem)
  return stems


def _detect_opponent_champions(frame_bgr, ctx, confidence=0.73):
  """Recognise opponent draft cards and keep a monotonic draft history.

  V16.1 changes two important things:
    * autonomy may see every opponent portrait that actually exists in ./bilder,
      not only a top-threat subset;
    * resolved template paths are deduplicated, so aliases do not repeatedly run
      the same expensive match.

  During PICK we rotate a bounded batch.  BAN/LEADER are stable, decisive phases,
  so we force a complete pass across every still-unknown portrait.  The latest
  visual center is cached for the ban click as a safety fallback.
  """
  ordered_needed = []
  for champion in list(DRAFT_PROFILE.opponent_names_needed()) + list(_combat_condition_opponent_names()):
    key = normalize_champion(champion)
    if key and key not in ordered_needed:
      ordered_needed.append(key)

  if not ordered_needed:
    ctx["opponent_champions"] = set()
    return set()

  found_names = {
    normalize_champion(name)
    for name in ctx.get("opponent_champions", set())
    if normalize_champion(name)
  }

  scan_names = [x for x in ordered_needed if x not in found_names]
  current_state = ctx.get("state")
  force_full = (
    AUTONOMY_ENABLED
    and AUTONOMY_DRAFT_ENABLED
    and current_state in tuple(AUTONOMY_DRAFT_FULL_SCAN_STATES or ())
  )

  if (
    AUTONOMY_ENABLED
    and AUTONOMY_DRAFT_ENABLED
    and not force_full
    and len(scan_names) > max(1, int(AUTONOMY_DRAFT_SCAN_BATCH))
  ):
    always = {normalize_champion(x) for x in _combat_condition_opponent_names()}
    priority = [x for x in scan_names if x in always]
    rest = [x for x in scan_names if x not in always]
    cursor = int(ctx.get("autonomy_opponent_scan_cursor", 0))
    batch_size = max(1, int(AUTONOMY_DRAFT_SCAN_BATCH))
    if rest:
      cursor %= len(rest)
      rotated = rest[cursor:] + rest[:cursor]
      batch = rotated[:batch_size]
      ctx["autonomy_opponent_scan_cursor"] = (cursor + batch_size) % len(rest)
    else:
      batch = []
    scan_names = list(dict.fromkeys(priority + batch))

  match_cache = ctx.setdefault("opponent_last_matches", {})
  for champion in scan_names:
    champion_key = normalize_champion(champion)

    best_near = 0.0
    best_stem = None
    best_hit = None
    had_template = False
    resolved_paths = []
    seen_paths = set()

    # Many aliases resolve to the exact same file.  Matching that PNG three times
    # was a major reason the rotating scan failed to see the full team in time.
    for stem in _opponent_detection_stems(champion):
      path = _draft_template_path(stem)
      if path is None:
        continue
      norm_path = os.path.normcase(os.path.abspath(path))
      if norm_path in seen_paths:
        continue
      seen_paths.add(norm_path)
      resolved_paths.append((stem, path))

    for stem, path in resolved_paths:
      had_template = True
      hit = _frame_match(
        frame_bgr,
        path,
        confidence=confidence,
        grayscale=False,
        scales=(1.00,),
        roi=ROI_ENEMY_TEAM,
      )

      score = float(hit.get("score", 0.0))
      if score > best_near:
        best_near = score
        best_stem = stem
        best_hit = hit

      if hit["found"]:
        found_names.add(champion_key)
        match_cache[champion_key] = {
          "center": tuple(hit.get("center") or ()),
          "box": tuple(hit.get("box") or ()),
          "score": score,
          "at": _active_time(),
        }
        break
    else:
      # Existing user crops sometimes sit below the hard found threshold while
      # still being isolated from unrelated portraits.  Keep the old conservative
      # rescue and also cache its visual center for the current phase.
      if best_near >= 0.64 and best_hit is not None:
        found_names.add(champion_key)
        match_cache[champion_key] = {
          "center": tuple(best_hit.get("center") or ()),
          "box": tuple(best_hit.get("box") or ()),
          "score": best_near,
          "at": _active_time(),
        }
        print(
          f"DRAFT OPPONENT RESCUE: {champion_key} "
          f"score={best_near:.3f} template={best_stem}"
        )
      elif not had_template:
        missing_logged = ctx.setdefault("missing_opponent_templates_logged", set())
        if champion_key not in missing_logged:
          missing_logged.add(champion_key)
          print(
            f"DRAFT TEMPLATE MISSING: opponent={champion_key}; "
            "autonomia nie może ocenić tej karty po obrazie."
          )

  signature = tuple(sorted(found_names))
  if signature != ctx.get("opponent_profile_signature"):
    ctx["opponent_profile_signature"] = signature
    if signature:
      print("DRAFT OPPONENTS: " + ", ".join(signature))
      if AUTONOMY_ENABLED and AUTONOMY_DRAFT_ENABLED:
        print(
          f"AUTONOMY DRAFT STATE: widzę {len(signature)}/5 przeciwników -> "
          + ", ".join(signature)
        )
  ctx["opponent_champions"] = found_names
  return found_names


def _detect_final_combat_opponents(frame_bgr, ctx, confidence=0.73):
  """Fresh, non-monotonic scan of the final post-ban enemy team.

  Legacy mode scans only names used by combat opening rules. V16 autonomy scans
  the bounded opponent knowledge/template set as well so the combat opponent
  model receives the actual final team.  No permissive rescue is used here: a
  false negative is safer than carrying a banned/stale champion into combat.
  """
  now = _active_time()
  last_scan = float(ctx.get("final_opponent_scan_at", 0.0) or 0.0)
  if last_scan and now - last_scan < 0.60:
    return set(ctx.get("final_opponent_champions") or ())
  ctx["final_opponent_scan_at"] = now

  found = set()
  # V16.1: this fresh scan is ONLY for combat opening exceptions.  The full
  # autonomous opponent model uses the monotonic draft roster minus our ban.
  # Keeping these concerns separate makes Fabian-vs-Gliseah conservative without
  # starving the AI of the other enemy identities.
  final_scan_names = set(_combat_condition_opponent_names())

  for champion in sorted(final_scan_names):
    key = normalize_champion(champion)
    best = 0.0
    for stem in _opponent_detection_stems(key):
      path = _draft_template_path(stem)
      if path is None:
        continue
      hit = _frame_match(
        frame_bgr,
        path,
        confidence=confidence,
        grayscale=False,
        roi=ROI_ENEMY_TEAM,
      )
      best = max(best, float(hit.get("score", 0.0)))
      if hit.get("found"):
        found.add(key)
        break

    # No permissive 0.64 rescue here. This set controls a combat exception,
    # therefore a false negative is safer than falsely suppressing Fabian A3.
    scores = ctx.setdefault("final_opponent_condition_scores", {})
    scores[key] = best

  our_ban = normalize_champion(ctx.get("ban_name"))
  if our_ban and our_ban != "slot_1":
    found.discard(our_ban)

  previous_final = set(ctx.get("final_opponent_champions") or ())
  if found != previous_final:
    ctx["final_opponent_champions"] = set(found)
    print(
      "FINAL OPPONENT CONDITIONS: "
      + (", ".join(sorted(found)) if found else "none")
    )
  return found


# V15.4 draft portrait recognition.
#
# The 2026-10-01 replay proved that a hard 0.84 / single-scale gate was the
# direct cause of the wrong Symbiont order:
#   Fabian  ~0.79 -> skipped although he was the #1 base pick
#   Gliseah ~0.84 -> missed the Fabian counter by a tiny margin
#   Tekteon ~0.74 -> skipped later in the base order
# Some older roster crops (notably Predator/Mavara) were captured at a different
# UI scale, so a cheap exact-scale pass is followed by a multi-scale rescue only
# when the exact pass is insufficient.
DRAFT_PICK_EXACT_CONFIDENCE = 0.72
DRAFT_PICK_RESCUE_CONFIDENCE = 0.78
DRAFT_PICK_RESCUE_SCALES = (0.55, 0.70, 0.85, 1.15)


def _profile_pick_match(frame_bgr, path):
  """Match one roster portrait with a fast exact pass + bounded scale rescue."""
  exact = _frame_match(
    frame_bgr,
    path,
    confidence=DRAFT_PICK_EXACT_CONFIDENCE,
    grayscale=True,
    scales=(1.00,),
    roi=ROI_CHAMPION_ROSTER,
  )
  if exact["found"]:
    exact["draft_match_mode"] = "exact"
    return exact

  rescue = _frame_match(
    frame_bgr,
    path,
    confidence=DRAFT_PICK_RESCUE_CONFIDENCE,
    grayscale=True,
    scales=DRAFT_PICK_RESCUE_SCALES,
    roi=ROI_CHAMPION_ROSTER,
  )
  rescue["draft_match_mode"] = "scale-rescue"
  return rescue


def _profile_pick_candidates(ctx, frame_bgr):
  opponents = _detect_opponent_champions(frame_bgr, ctx)
  counter_order = DRAFT_PROFILE.counter_order(opponents)
  ctx["active_counter_candidates"] = set(counter_order)
  return DRAFT_PROFILE.pick_order(
    opponents,
    ctx.get("picked_champions", []),
  )


def _profile_ban_candidates(ctx, frame_bgr):
  opponents = _detect_opponent_champions(frame_bgr, ctx)
  return DRAFT_PROFILE.ban_order(opponents)


def _diagnostic_snapshot(
  frame_bgr,
  raid_rect,
  state=None,
  combat_data=None,
):
  """TAB: zapis screena + krótki raport bez wykonywania akcji."""
  global _diagnostic_requested

  if not _diagnostic_requested:
    return

  _diagnostic_requested = False

  if state is None:
    state = _current_live_state

  os.makedirs("./debug", exist_ok=True)
  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  out_path = f"./debug/live_diag_{timestamp}.png"

  if frame_bgr is not None:
    try:
      cv2.imwrite(out_path, frame_bgr)
    except Exception:
      out_path = "(nie udało się zapisać)"

  print("\n========== TAB DIAGNOSTYKA ==========")
  print(f"CURRENT PHASE: {state}")
  print(f"RAID RECT: {raid_rect}")
  print(f"SCREEN: {out_path}")

  if frame_bgr is not None:
    matches = _phase_matches(frame_bgr)
    print(
      "PHASE SCORES:",
      f"YourTurn={matches['your_turn']['score']:.3f}",
      f"Pick={matches[STATE_PICK]['score']:.3f}",
      f"Ban={matches[STATE_BAN]['score']:.3f}",
      f"Leader={matches[STATE_LEADER]['score']:.3f}",
    )

  print("=====================================\n")


def _offline_template_match(screen_bgr, template_path, threshold=0.78, grayscale=False):
  """Dopasowanie wzorca na zapisanym screenie. NICZEGO nie klika."""
  if not os.path.exists(template_path):
    return {"found": False, "score": 0.0, "center": None, "box": None, "reason": "missing_template"}

  template = cv2.imread(template_path, cv2.IMREAD_COLOR)
  if template is None or screen_bgr is None:
    return {"found": False, "score": 0.0, "center": None, "box": None, "reason": "read_error"}

  if grayscale:
    screen_work = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    template_base = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
  else:
    screen_work = screen_bgr
    template_base = template

  best_score = -1.0
  best_box = None
  best_scale = None
  scales = (0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35)

  for scale in scales:
    tw = max(3, int(template_base.shape[1] * scale))
    th = max(3, int(template_base.shape[0] * scale))
    if tw > screen_work.shape[1] or th > screen_work.shape[0]:
      continue
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(template_base, (tw, th), interpolation=interpolation)
    result = cv2.matchTemplate(screen_work, resized, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    if score > best_score:
      best_score = float(score)
      x, y = loc
      best_box = (x, y, tw, th)
      best_scale = scale

  if best_box is None:
    return {"found": False, "score": 0.0, "center": None, "box": None, "reason": "no_valid_scale"}

  x, y, w, h = best_box
  return {
    "found": best_score >= threshold,
    "score": best_score,
    "center": (x + w // 2, y + h // 2),
    "box": best_box,
    "scale": best_scale,
    "reason": None,
  }


def _offline_check(screen_bgr, filename, confidence=0.78, grayscale=False):
  path = f"./bilder/{filename}.PNG"
  result = _offline_template_match(screen_bgr, path, threshold=confidence, grayscale=grayscale)
  state = "TAK" if result["found"] else "NIE"
  if result.get("reason") == "missing_template":
    print(f"  {filename}: BRAK PLIKU {path}")
  else:
    print(f"  {filename}: {state} (score={result['score']:.3f})")
  return result


def run_offline_ui_test(image_path):
  """Bezpieczny test draftu na zapisanym screenie. ZERO kliknięć."""
  print("\n" + "=" * 66)
  print("OFFLINE UI TEST - ZERO KLIKNIĘĆ")
  print("Screen:", image_path)
  print("Wzorce są czytane wyłącznie z ./bilder/")
  print("=" * 66)

  if not os.path.exists(image_path):
    print("BŁĄD: screen nie istnieje:", image_path)
    return False

  screen = cv2.imread(image_path, cv2.IMREAD_COLOR)
  if screen is None:
    print("BŁĄD: nie udało się odczytać screena.")
    return False

  print("\n[DETEKCJA FAZY]")
  your_turn = _offline_check(screen, "arena_live_your_turn", 0.78, False)
  pick_phase = _offline_check(screen, "arena_live_pick_your_champions", 0.78, True)
  ban_phase = _offline_check(screen, "live_arena_ban_champions", 0.82, False)
  lead_phase = _offline_check(screen, "live_arena_pick_leader", 0.82, False)

  print("\n[DECYZJA BOTA]")
  if not your_turn["found"]:
    if pick_phase["found"] or ban_phase["found"] or lead_phase["found"]:
      print("TURA PRZECIWNIKA / brak YOUR TURN -> ZERO KLIKNIĘĆ.")
    else:
      print("Nie wykryto aktywnej własnej fazy draftu -> ZERO KLIKNIĘĆ.")
    return True

  if ban_phase["found"]:
    print("Wykryto: YOUR TURN + BAN CHAMPIONS")
    chosen = None
    for ban_name in ban_champions:
      r = _offline_check(screen, ban_name, 0.76, False)
      if r["found"]:
        chosen = ban_name
        break
    if chosen:
      print(f"TEST: zbanowałbym priorytet -> {chosen}")
    else:
      print("TEST: brak priorytetowego celu -> zbanowałbym SLOT 1 przeciwnika.")
    confirm = _offline_check(screen, "arena_live_confirm_pick", 0.78, False)
    if confirm["found"]:
      print("TEST: po wyborze celu zatwierdziłbym Confirm.")
    else:
      print("TEST: Confirm nie jest jeszcze widoczny -> bot powinien poczekać.")
    return True

  if lead_phase["found"]:
    print("Wykryto: YOUR TURN + PICK LEADER")
    chosen = None
    for lead_name in lead_champions:
      r = _offline_check(screen, lead_name, 0.76, False)
      if r["found"]:
        chosen = lead_name
        break
    if chosen:
      print(f"TEST: wybrałbym lidera -> {chosen}")
    else:
      print("TEST: Fabian/Ankora/Harima/Mikage niedostępni -> losowy slot awaryjny.")
    confirm = _offline_check(screen, "arena_live_confirm_pick", 0.78, False)
    if confirm["found"]:
      print("TEST: następnie zatwierdziłbym Confirm.")
    else:
      print("TEST: Confirm nie jest jeszcze widoczny -> bot powinien poczekać.")
    return True

  if pick_phase["found"]:
    print("Wykryto: YOUR TURN + PICK CHAMPIONS")
    live_filter = _offline_check(screen, "arena_live_filter", 0.76, False)
    if live_filter["found"]:
      print("TEST: kliknąłbym Live Arena Tag (skrzyżowane miecze).")
    else:
      print("TEST: nie widzę arena_live_filter.PNG -> NIE wybierałbym jeszcze postaci.")
      return True
    chosen = None
    for champ_name in my_champions:
      r = _offline_check(screen, champ_name, 0.82, True)
      if r["found"]:
        chosen = champ_name
        break
    if chosen:
      print(f"TEST: pierwsza dostępna postać z priorytetu -> {chosen}")
    else:
      print("TEST: nie wykryto żadnej postaci z my_champions na tym screenie.")
    confirm = _offline_check(screen, "arena_live_confirm_pick", 0.78, False)
    if confirm["found"]:
      print("TEST: po wyborze postaci zatwierdziłbym Confirm.")
    else:
      print("TEST: Confirm niewidoczny -> bot nie kliknąłby go.")
    return True

  print("YOUR TURN jest widoczne, ale nie rozpoznano Pick/Ban/Leader -> ZERO KLIKNIĘĆ.")
  return True


def _run_test_mode_from_argv(argv):
  """Obsługa: py arenalive.py --test-ui screen1.png [screen2.png ...]"""
  if "--test-ui" not in argv:
    return False
  idx = argv.index("--test-ui")
  image_paths = []
  for arg in argv[idx + 1:]:
    if arg.startswith("--"):
      break
    image_paths.append(arg)
  if not image_paths:
    print("Użycie: py arenalive.py --test-ui \"ścieżka_do_screena.png\"")
    print("Tryb testowy niczego nie klika.")
    return True
  for image_path in image_paths:
    run_offline_ui_test(image_path)
  return True

def _consume_diagnostic_request():
  global _diagnostic_requested
  if not _diagnostic_requested:
    return False
  _diagnostic_requested = False
  return True


def _arena_sleep_remaining():
  return max(0.0, _arena_closed_until - time.monotonic())


def _mark_arena_closed(reason):
  global _arena_closed_until
  _arena_closed_until = time.monotonic() + ARENA_CLOSED_RECHECK_SECONDS
  print(
    f"LIVE ARENA CLOSED/UNAVAILABLE: {reason}. "
    f"Ponowna próba najwcześniej za "
    f"{ARENA_CLOSED_RECHECK_SECONDS / 60:.0f} min."
  )


def _clear_arena_closed_gate():
  global _arena_closed_until
  _arena_closed_until = 0.0


def _find_opponent_button(timeout=ARENA_READY_TIMEOUT_SECONDS):
  """Zwraca AKTYWNY Find Opponent albo None. Nie wykonuje blind click."""
  end = _active_time() + max(0.0, timeout)

  while _active_time() < end:
    _wait_if_paused()
    result = _safe_locate(
      "./bilder/arena_live_find_opponent.PNG",
      grayscale=False,
      confidence=0.82,
    )
    if result:
      return result
    _pauseable_sleep(0.15)

  return None


def _collect_preload_templates():
  """Zbiera wszystkie obrazy używane przez bieżący kod i priorytety."""
  paths = set()

  # Statyczne literalne ścieżki z arenalive.py.
  try:
    source = Path(__file__).read_text(encoding="utf-8")
    for rel in re.findall(r'[\"\'](\\?\./bilder/[^\"\']+?\\.PNG)[\"\']', source):
      paths.add(rel.replace("\\./", "./"))
  except Exception:
    pass

  # Dynamiczne nazwy generowane przez f-stringi.  Najpierw rozwiązujemy alias
  # do REALNIE istniejącego pliku.  W przeciwnym razie VISION.preload zgłaszał
  # fałszywe BRAK mimo że równoważny template był już w ./bilder.
  for name in my_champions:
    resolved = _draft_template_path(name)
    paths.add(resolved or f"./bilder/{name}.PNG")
  for name in lead_champions:
    resolved = _draft_template_path(name)
    paths.add(resolved or f"./bilder/{name}.PNG")
  for name in ban_champions:
    resolved = _draft_template_path(name)
    paths.add(resolved or f"./bilder/{name}.PNG")
  for stem in DRAFT_PROFILE.preload_template_stems():
    resolved = _draft_template_path(stem)
    # Jeśli nie ma żadnego bezpiecznego odpowiednika, nadal pokazujemy BRAK.
    paths.add(resolved or f"./bilder/{stem}.PNG")
  for skill_name, _, _, _ in SKILL_PLAN:
    paths.add(f"./bilder/{skill_name}.PNG")
  for skill_name, _, _, _ in GLOBAL_SKILL_PLAN:
    paths.add(f"./bilder/{skill_name}.PNG")

  paths.update({
    "./bilder/arena_live_veil.PNG",
    "./bilder/arena_live_perfect_veil.PNG",
    "./bilder/arena_live_stoneskin.PNG",
    "./bilder/arena_live_10gem_refyll.PNG",
    "./bilder/arena_live_20gem_refyll.PNG",
  })
  return paths


def _preload_templates_once():
  global _templates_preloaded
  if _templates_preloaded:
    return

  VISION.announce_backend()
  loaded, missing = VISION.preload(_collect_preload_templates())
  if missing:
    print("VISION PRELOAD - brakujące template'y:")
    for path in missing:
      print(f"  BRAK: {path}")
  _templates_preloaded = True


def main():
  global _last_arena_closed_log_at, _draft_profile_logged

  if not _draft_profile_logged:
    source = DRAFT_PROFILE.source_path or "legacy-config fallback"
    print(
      f"DRAFT PROFILE: {DRAFT_PROFILE.name} | source={source} | "
      f"pick={len(DRAFT_PROFILE.pick_priority)} "
      f"ban={len(DRAFT_PROFILE.ban_priority)} "
      f"counter_rules={len(DRAFT_PROFILE.counter_pick) + len(DRAFT_PROFILE.counter_pick_rules)}"
    )
    load_notice = getattr(DRAFT_PROFILE, "load_notice", None)
    if load_notice:
      print(load_notice)

    load_error = getattr(DRAFT_PROFILE, "load_error", None)
    if load_error:
      print(f"DRAFT PROFILE WARNING: {load_error}")

    if DRAFT_PROFILE.counter_pick:
      counter_text = " | ".join(
        f"{enemy}->{'>'.join(priority)}"
        for enemy, priority in DRAFT_PROFILE.counter_pick.items()
      )
      print("DRAFT COUNTERS: " + counter_text)

    print(
      "AUTONOMY V16.1: "
      + ("ON (dynamic draft/combat scoring)" if (AUTONOMY_ENABLED and AUTONOMY_DRAFT_ENABLED) else "OFF / legacy policy")
    )
    _draft_profile_logged = True

  # V15.9: explicit bad profile = fail closed.
  # The replay from 2026-10-01 contained "symbiontS".  The old code silently
  # fell back to the legacy 8-pick config, which produced a wrong draft and then
  # repeated "żaden kandydat...".  A unique typo is now autocorrected; anything
  # ambiguous/unknown stops BEFORE clicks instead of using the wrong strategy.
  if (
    _draft_profile_explicit
    and not bool(getattr(DRAFT_PROFILE, "profile_valid", DRAFT_PROFILE.source_path))
  ):
    requested = getattr(DRAFT_PROFILE, "requested_name", _draft_profile_name)
    print(
      f"DRAFT PROFILE ERROR: profil '{requested}' nie istnieje i nie ma "
      f"jednoznacznej korekty. Bot NIE rozpocznie draftu."
    )
    return

  _install_pause_hotkey()

  # Jedna globalna pauza dla nawigacji shared.py, reklam i combat engine.
  if hasattr(shared, "configure_pause"):
    shared.configure_pause(_wait_if_paused, _pauseable_sleep)
  if hasattr(closeadds, "configure_pause"):
    closeadds.configure_pause(_wait_if_paused, _pauseable_sleep)

  _preload_templates_once()
  _set_live_state(STATE_IDLE)

  remaining = _arena_sleep_remaining()
  if remaining > 0:
    now = _active_time()
    if now - _last_arena_closed_log_at >= 60.0:
      print(
        f"Live Arena sleep gate: zamknięta/niedostępna; "
        f"pozostało ~{remaining / 60:.1f} min."
      )
      _last_arena_closed_log_at = now
    return

  if flagInstance.no_cvc or LIVEARENA_IGNORE_CVC_GATE:
    if not flagInstance.no_cvc:
      print("LIVE ARENA: CvC aktywne -> pomijam tylko lokalny gate CvC i kontynuuję Live Arena.")
    if __ready_to_run_livearena():
      if errorhandling.gameReset() == "skip":
        return

      if _arenaIsActive():
        _set_live_state(STATE_IDLE)
        _initArenaLive()
        _collectRefylls()
        _claimChest()

        # Najważniejszy warunek V10:
        # NIE wolno wejść do MATCHMAKING/PICK bez aktywnego Find Opponent.
        ready_button = _find_opponent_button()
        if not ready_button:
          _mark_arena_closed("brak aktywnego przycisku Find Opponent")
          _exitArena()
          _set_live_state(STATE_IDLE)
          return

        _clear_arena_closed_gate()

        post_battle_pending = False

        for i in range(16):
          _wait_if_paused()

          # V15.18: do not claim MATCHMAKING while RAID still shows
          # "Processing Results...".  RESULT is now a real state.
          if post_battle_pending:
            _set_live_state(STATE_RESULT)
          else:
            _set_live_state(STATE_MATCHMAKING)

          if _haveBattlesLeft(post_battle=post_battle_pending):
            _wait_if_paused()
            post_battle_pending = False
            _conductBattle()

            # CombatEngine returns after the result/Return path.  The next loop
            # must first wait for the Live Arena screen to become ready again.
            post_battle_pending = True
          else:
            break

        _exitArena()
        _set_live_state(STATE_IDLE)
      else:
        print("aborting livearena")


def _pick_state_tick(ctx, raid_rect, frame_bgr, matches):
  your_turn = matches["your_turn"]["found"]
  _update_turn_clock(ctx, your_turn)

  if not (your_turn and matches[STATE_PICK]["found"]):
    # V15.22: w turze z dwoma pickami RAID potrafi natychmiast oddać turę
    # przeciwnikowi po poprawnym kliknięciu pierwszej postaci. Stara logika
    # zerowała pick_selected_at/pick_clicked_name zanim lokalny timer 0.35 s
    # zdążył wykonać PICK TRACK. Następna nasza tura uważała więc championa
    # za niewybranego i klikała go ponownie ("This Champion has already been picked").
    # Sama utrata naszej tury / zniknięcie fazy PICK po wysłanym kliknięciu jest
    # wystarczającym dowodem, że oczekujący pick trzeba zapisać przed resetem.
    if ctx.get("pick_selected_at") is not None and ctx.get("pick_clicked_name"):
      if _record_picked_champion(ctx, ctx.get("pick_clicked_name")):
        ctx["champion_order"] += 1
        print(
          "PICK TRACK RECOVERY: zapisuję ostatni klik przed zmianą tury -> "
          f"{ctx.get('pick_clicked_name')}."
        )
      ctx["pick_clicked_name"] = None

    ctx["pick_pending"] = None
    ctx["pick_confirm_due"] = None
    ctx["pick_selected_at"] = None
    if not ctx.get("pick_wait_logged"):
      print("PICK: czekam na własną turę.")
      ctx["pick_wait_logged"] = True
    return None

  ctx["pick_wait_logged"] = False

  # Filter Live Arena tylko raz.
  if not ctx["filter_applied"]:
    filter_match = _frame_match(
      frame_bgr,
      "./bilder/arena_live_filter.PNG",
      confidence=0.76,
      grayscale=False,
    )

    if filter_match["found"]:
      print("PICK: Live Arena tag -> klik.")
      clicked = _human_click(_frame_screen_point(raid_rect, filter_match), 0.14, 0.30)
      if not clicked:
        print("PICK: ruch myszy zakłócony -> ponawiam tag w następnym ticku.")
        return None
      ctx["filter_applied"] = True
      _pauseable_sleep(0.10)
    return None

  # Po kliknięciu championa czekamy krótko, czy Confirm się uaktywni.
  if ctx.get("pick_selected_at") is not None:
    confirm = _frame_match(
      frame_bgr,
      "./bilder/arena_live_confirm_pick.PNG",
      confidence=0.82,
      grayscale=False,
    )

    if confirm["found"]:
      if ctx.get("pick_confirm_due") is None:
        delay = _draft_delay(ctx)
        ctx["pick_confirm_due"] = _active_time() + delay
        print(f"PICK: Confirm za {delay:.2f}s.")
        return None

      if _active_time() >= ctx["pick_confirm_due"]:
        print("PICK: zatwierdzam.")
        clicked = _human_click(_frame_screen_point(raid_rect, confirm), 0.16, 0.34)
        if not clicked:
          print("PICK: Confirm anulowany przez Mouse Guard -> ponawiam.")
          ctx["pick_confirm_due"] = None
          return None
        _record_picked_champion(ctx, ctx.get("pick_clicked_name"))
        ctx["pick_clicked_name"] = None
        ctx["champion_order"] += 1
        ctx["pick_selected_at"] = None
        ctx["pick_confirm_due"] = None
        _pauseable_sleep(0.10)
      return None

    # W turze z dwoma pickami Confirm bywa nieaktywny po pierwszej postaci.
    if _active_time() - ctx["pick_selected_at"] >= 0.35:
      _record_picked_champion(ctx, ctx.get("pick_clicked_name"))
      ctx["pick_clicked_name"] = None
      ctx["champion_order"] += 1
      ctx["pick_selected_at"] = None
      ctx["pick_confirm_due"] = None
    return None

  # V15.2: profile-driven candidate order. Counter-picks are prepended when
  # their opponent condition is recognised; otherwise the base pick_priority is used.
  candidates = _profile_pick_candidates(ctx, frame_bgr)

  pending = ctx.get("pick_pending")
  if pending:
    pending_champion = normalize_champion(pending.get("champion"))
    current_order = [normalize_champion(x) for x in candidates]
    current_candidates = set(current_order)

    if pending_champion not in current_candidates:
      ctx["pick_pending"] = None
      return None

    # V15.11: a newly recognised counter must be allowed to supersede a base
    # pick that was already waiting on its humanised delay. Previously we only
    # checked whether the pending champion was still somewhere in the list,
    # so Vestele/Tekteon could still be clicked even after Telena appeared and
    # Gliseah moved ahead of them in profile priority.
    pending_index = current_order.index(pending_champion)
    for higher in current_order[:pending_index]:
      higher_stem = DRAFT_PROFILE.pick_template_stem(higher)
      higher_path = _draft_template_path(higher_stem)
      if higher_path is None:
        continue
      higher_match = _profile_pick_match(frame_bgr, higher_path)
      if higher_match["found"]:
        print(
          f"PICK RECHECK: nowy wyższy priorytet {higher} "
          f"(score={float(higher_match.get('score', 0.0)):.3f}) "
          f"zastępuje oczekujący {pending_champion}."
        )
        ctx["pick_pending"] = None
        return None

    if _active_time() < pending["due"]:
      return None

    stem = pending.get("stem") or DRAFT_PROFILE.pick_template_stem(pending_champion)
    path = _draft_template_path(stem)
    if path is None:
      ctx["pick_pending"] = None
      return None

    champ = _profile_pick_match(frame_bgr, path)
    if not champ["found"]:
      # Opponent may have taken the champion between observations; recalculate.
      ctx["pick_pending"] = None
      return None

    print(f"PICK PROFILE: wybieram {pending_champion}.")
    clicked = _human_click(_frame_screen_point(raid_rect, champ), 0.18, 0.40)
    if clicked:
      ctx["pick_clicked_name"] = stem
    ctx["pick_pending"] = None
    ctx["pick_selected_at"] = _active_time()
    _pauseable_sleep(0.08)
    return None

  # Find the first profile candidate that is actually available in our roster.
  for champion in candidates:
    stem = DRAFT_PROFILE.pick_template_stem(champion)
    path = _draft_template_path(stem)
    if path is None:
      continue

    champ = _profile_pick_match(frame_bgr, path)
    if not champ["found"]:
      continue

    delay = _draft_delay(ctx)
    ctx["pick_pending"] = {
      "champion": normalize_champion(champion),
      "stem": stem,
      "due": _active_time() + delay,
    }
    champion_key = normalize_champion(champion)
    active_counters = set(ctx.get("active_counter_candidates", set()))
    source = "COUNTER" if champion_key in active_counters else "BASE"
    print(
      f"PICK PROFILE: {champion_key} za {delay:.2f}s "
      f"[{source}; score={float(champ.get('score', 0.0)):.3f}; "
      f"mode={champ.get('draft_match_mode', 'n/a')}]."
    )
    return None

  now = _active_time()
  if now - ctx.get("pick_no_candidate_logged_at", float("-inf")) >= 1.5:
    print("PICK PROFILE: żaden kandydat z aktywnego profilu nie jest teraz dostępny.")
    ctx["pick_no_candidate_logged_at"] = now

  return None


def _ban_state_tick(ctx, raid_rect, frame_bgr, matches):
  your_turn = matches["your_turn"]["found"]
  _update_turn_clock(ctx, your_turn)

  if matches[STATE_LEADER]["found"]:
    return STATE_LEADER

  # Po wysłaniu Confirm NIE zakładamy sukcesu. Czekamy aż Ban Champions zniknie
  # i pojawi się Pick Leader. Jeśli ekran bana nadal trwa, Confirm jest ponawiany.
  if ctx.get("ban_confirm_sent_at") is not None:
    now = _active_time()

    if matches[STATE_LEADER]["found"]:
      return STATE_LEADER

    if matches[STATE_BAN]["found"]:
      if now - ctx["ban_confirm_sent_at"] > 0.85:
        confirm = _frame_match(
          frame_bgr,
          "./bilder/arena_live_confirm_pick.PNG",
          confidence=0.76,
          grayscale=False,
        )
        if confirm["found"] and ctx.get("ban_confirm_retries", 0) < 2:
          ctx["ban_confirm_retries"] = ctx.get("ban_confirm_retries", 0) + 1
          print(f"BAN: Confirm nadal aktywny -> retry {ctx['ban_confirm_retries']}.")
          clicked = _human_click(_frame_screen_point(raid_rect, confirm), 0.08, 0.18)
          if clicked:
            ctx["ban_confirm_sent_at"] = now
        elif now - ctx["ban_confirm_sent_at"] > 1.5:
          ctx["ban_clicked"] = False
          ctx["ban_target_due"] = None
          ctx["ban_confirm_due"] = None
          ctx["ban_confirm_sent_at"] = None
      return None

    # Ban zniknął; state machine poczeka na realne Pick Leader.
    return None

  if not (your_turn and matches[STATE_BAN]["found"]):
    if not ctx.get("ban_wait_logged"):
      print("BAN: czekam na Ban Champions + Your Turn.")
      ctx["ban_wait_logged"] = True
    return None

  ctx["ban_wait_logged"] = False

  if not ctx.get("ban_clicked"):
    # Losowe opóźnienie 2.0-3.3 s przed wyborem celu do bana.
    # To jest timer stanowy, nie blokujący sleep, więc bot nadal obserwuje UI.
    if ctx.get("ban_target_due") is None:
      ban_delay = random.uniform(2.0, 3.3)
      ctx["ban_target_due"] = _active_time() + ban_delay
      print(f"BAN: wybór celu za {ban_delay:.2f}s.")
      return None

    if _active_time() < ctx["ban_target_due"]:
      return None

    target_match = None
    target_name = None

    ban_order = _profile_ban_candidates(ctx, frame_bgr)
    if AUTONOMY_ENABLED and AUTONOMY_DRAFT_ENABLED and ban_order:
      print("AUTONOMY BAN ORDER: " + " > ".join(ban_order[:5]))

    for champion in ban_order:
      seen_paths = set()
      for stem in DRAFT_PROFILE.ban_template_stems(champion):
        ban_file = _draft_template_path(stem)
        if ban_file is None:
          continue
        norm_path = os.path.normcase(os.path.abspath(ban_file))
        if norm_path in seen_paths:
          continue
        seen_paths.add(norm_path)

        found = _frame_match(
          frame_bgr,
          ban_file,
          confidence=0.70,
          grayscale=False,
          scales=(1.00,),
          roi=ROI_ENEMY_TEAM,
        )
        if found["found"] or float(found.get("score", 0.0) or 0.0) >= 0.64:
          target_match = found
          target_name = normalize_champion(champion)
          break
      if target_match is not None:
        break

    if target_match is not None:
      target_point = _frame_screen_point(raid_rect, target_match)
      print(
        f"BAN AUTONOMY: wybieram {target_name} "
        f"(score={float(target_match.get('score', 0.0) or 0.0):.3f})."
      )
    else:
      # If the current match pass is temporarily obscured by the ban overlay,
      # use only a very recent center captured by the opponent detector on the
      # same stable BAN screen.  This is still identity-driven, never a stale
      # blind point from an earlier phase.
      cache = ctx.get("opponent_last_matches", {})
      now = _active_time()
      cached = None
      for champion in ban_order:
        key = normalize_champion(champion)
        info = cache.get(key) or {}
        center = tuple(info.get("center") or ())
        age = now - float(info.get("at", 0.0) or 0.0)
        if len(center) == 2 and age <= 1.8:
          cached = (key, center, float(info.get("score", 0.0) or 0.0), age)
          break

      if cached is not None:
        target_name, center, cached_score, age = cached
        target_point = (
          raid_rect[0] + int(center[0]),
          raid_rect[1] + int(center[1]),
        )
        print(
          f"BAN AUTONOMY: używam świeżego położenia {target_name} "
          f"(score={cached_score:.3f}, age={age:.2f}s)."
        )
      else:
        target_point = _rel_point(raid_rect, 740, 300)
        target_name = "slot_1"
        print(
          "BAN AUTONOMY: nie mam pewnej identyfikacji żadnej karty -> "
          "awaryjnie slot 1."
        )

    clicked = _human_click(target_point, 0.12, 0.26)
    if not clicked:
      print("BAN: Mouse Guard anulował klik -> losuję nowe opóźnienie.")
      ctx["ban_target_due"] = None
      return None

    ctx["ban_target_due"] = None
    ctx["ban_clicked"] = True
    ctx["ban_name"] = target_name
    ctx["ban_clicked_at"] = _active_time()
    return None

  confirm = _frame_match(
    frame_bgr,
    "./bilder/arena_live_confirm_pick.PNG",
    confidence=0.76,
    grayscale=False,
  )

  if confirm["found"]:
    if ctx.get("ban_confirm_due") is None:
      ctx["ban_confirm_due"] = _active_time() + random.uniform(0.08, 0.22)
      return None

    if _active_time() >= ctx["ban_confirm_due"]:
      print(f"BAN: zatwierdzam {ctx.get('ban_name')} i czekam na zmianę fazy.")
      clicked = _human_click(_frame_screen_point(raid_rect, confirm), 0.10, 0.22)
      if not clicked:
        print("BAN: Confirm zakłócony -> ponawiam.")
        ctx["ban_confirm_due"] = None
        return None
      ctx["ban_confirm_sent_at"] = _active_time()
      ctx["ban_confirm_due"] = None
      ctx["ban_confirm_retries"] = 0
      return None

  if _active_time() - ctx.get("ban_clicked_at", 0.0) > 1.5:
    ctx["ban_clicked"] = False
    ctx["ban_target_due"] = None
    ctx["ban_confirm_due"] = None

  return None


def _record_picked_champion(ctx, champion_name):
  """Zapamiętuje kolejność REALNIE wybranych championów do Pick Leader.

  Zwraca True tylko przy nowym wpisie. Porównanie jest po kanonicznej nazwie,
  więc alias/template stem (np. arena_live_gliseah) nie może wejść drugi raz.
  """
  if not champion_name:
    return False

  champion_key = normalize_champion(champion_name)
  if not champion_key:
    return False

  picked = ctx.setdefault("picked_champions", [])
  if any(normalize_champion(existing) == champion_key for existing in picked):
    return False

  if len(picked) >= 5:
    return False

  picked.append(champion_name)
  print(f"PICK TRACK: slot {len(picked)} = {champion_name}")
  return True


def _leader_slot_point(raid_rect, slot_index):
  """Kalibrowany punkt slotu lidera względem aktualnego okna RAID."""
  return calibrated_leader_slot_point(raid_rect, slot_index)


def _leader_slot_selection_score(frame_bgr, raid_rect, slot_index):
  """
  Ile zielonej obwódki ma konkretny slot lidera.

  Zwracamy RATIO, nie surową liczbę pikseli, więc działa również po resize/DPI.
  """
  region = calibrated_leader_card_region(raid_rect, slot_index)
  if region is None or frame_bgr is None:
    return 0.0

  crop = _crop_abs_region(frame_bgr, raid_rect, region)
  if crop is None or crop.size == 0:
    return 0.0

  hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
  green = cv2.inRange(
    hsv,
    np.array([35, 120, 140], dtype=np.uint8),
    np.array([90, 255, 255], dtype=np.uint8),
  )

  h, w = green.shape[:2]
  border = max(4, min(8, min(h, w) // 10))

  ring = np.zeros_like(green)
  ring[:border, :] = 255
  ring[-border:, :] = 255
  ring[:, :border] = 255
  ring[:, -border:] = 255

  ring_pixels = max(1, int(np.count_nonzero(ring)))
  green_border = int(
    np.count_nonzero(
      cv2.bitwise_and(green, ring)
    )
  )

  return green_border / float(ring_pixels)


def _leader_selected_slot(frame_bgr, raid_rect):
  """
  Zwraca JEDEN jednoznacznie podświetlony slot.

  Wcześniej każdy slot był oceniany osobno stałym progiem, więc zielone
  elementy portretu/affinity mogły fałszywie dać "LEADER VERIFIED".
  Teraz oczekiwany slot musi:
    - mieć wystarczająco dużo zielonej ramki,
    - być najlepszy ze wszystkich 5 slotów,
    - wygrywać nad drugim wynikiem o bezpieczny margines.
  """
  scores = [
    _leader_slot_selection_score(
      frame_bgr,
      raid_rect,
      idx,
    )
    for idx in range(len(LEADER_SLOT_CENTERS))
  ]

  if not scores:
    return None, scores

  ordered = sorted(
    enumerate(scores),
    key=lambda pair: pair[1],
    reverse=True,
  )

  best_idx, best = ordered[0]
  second = ordered[1][1] if len(ordered) > 1 else 0.0

  if best < LEADER_SELECTED_BORDER_RATIO_MIN:
    return None, scores

  if best - second < LEADER_SELECTED_BORDER_MARGIN:
    return None, scores

  return best_idx, scores


def _leader_slot_is_selected(frame_bgr, raid_rect, slot_index):
  selected_idx, _ = _leader_selected_slot(frame_bgr, raid_rect)
  return selected_idx == slot_index



def _nearest_leader_slot_index(raid_rect, screen_point):
  if screen_point is None:
    return None

  px, py = screen_point
  candidates = []
  for idx in range(len(LEADER_SLOT_CENTERS)):
    p = _leader_slot_point(raid_rect, idx)
    if p is None:
      continue
    dx = px - p[0]
    dy = py - p[1]
    candidates.append((dx * dx + dy * dy, idx))

  if not candidates:
    return None
  return min(candidates)[1]



def _leader_slot_is_banned(frame_bgr, raid_rect, slot_index):
  """Czerwone przekreślone kółko jest na ŚRODKU portretu, nie pod nim.

  Badamy spójny znak w małym, znormalizowanym obszarze. Gwiazdki u góry
  i czerwona czaszka affinity na dole nie są dowodem bana. Normalizacja
  zachowuje te same progi również po zmianie rozmiaru okna / DPI.
  """
  point = _leader_slot_point(raid_rect, slot_index)
  if point is None or frame_bgr is None:
    return False

  x, y = point
  sx, sy = raid_rect[2] / 1024.0, raid_rect[3] / 769.0
  half_w, half_h = max(1, round(22 * sx)), max(1, round(22 * sy))
  crop = _crop_abs_region(
    frame_bgr,
    raid_rect,
    (
      x - half_w,
      y - half_h,
      half_w * 2,
      half_h * 2,
    ),
  )

  if crop is None or crop.size == 0:
    return False

  crop = cv2.resize(crop, (44, 44), interpolation=cv2.INTER_LINEAR)
  hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

  red_low = cv2.inRange(
    hsv,
    np.array([0, 150, 100], dtype=np.uint8),
    np.array([12, 255, 255], dtype=np.uint8),
  )
  red_high = cv2.inRange(
    hsv,
    np.array([168, 150, 100], dtype=np.uint8),
    np.array([179, 255, 255], dtype=np.uint8),
  )

  red = cv2.bitwise_or(red_low, red_high)
  _, _, components, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
  for bx, by, bw, bh, area in components[1:]:
    # Symbol ma ok. 16x16 px. Wymagamy fragmentu o rozmiarze i położeniu
    # symbolu, zamiast sumować wszystkie czerwone elementy portretu.
    if not (28 <= area and 10 <= bw <= 25 and 10 <= bh <= 25):
      continue
    if not (0.60 <= bw / float(bh) <= 1.65):
      continue
    if abs(bx + bw / 2.0 - 22) <= 9 and abs(by + bh / 2.0 - 22) <= 9:
      return True
  return False


def _leader_remember_bans(ctx, frame_bgr, raid_rect):
  """Ban jest stały w tej fazie; kursor nie może chwilowo go odwołać."""
  banned = ctx.setdefault("leader_banned_slots", set())
  for index in range(len(LEADER_SLOT_CENTERS)):
    if _leader_slot_is_banned(frame_bgr, raid_rect, index):
      banned.add(index)
  return banned


def _leader_champion_template_path(base_name):
  """
  Zwraca zwykły template championa z draftu, np.
  arena_live_fabian.png.

  Na Windows wielkość liter nie ma znaczenia, ale ten resolver działa również
  w środowiskach case-sensitive.
  """
  root = Path("./bilder")
  wanted = f"{base_name}.png".lower()

  if root.is_dir():
    try:
      for path in root.iterdir():
        if path.is_file() and path.name.lower() == wanted:
          return str(path)
    except Exception:
      pass

  # Standardowa ścieżka dla Windows.
  return f"./bilder/{base_name}.PNG"


def _leader_slot_champion_score(frame_bgr, raid_rect, slot_index, champion_name):
  """
  Score konkretnego championa TYLKO w konkretnym slocie Pick Leader.

  Nie szukamy po całym ekranie. Dzięki temu inventory na dole i podobne portrety
  nie mogą zostać pomylone z kartą lidera.
  """
  champion_name = _leader_base_from_template_name(champion_name)
  region = calibrated_leader_card_region(raid_rect, slot_index)
  if region is None:
    return 0.0

  crop = _crop_abs_region(frame_bgr, raid_rect, region)
  if crop is None or crop.size == 0:
    return 0.0

  # Oba rodzaje PNG prowadzą do tej SAMEJ nazwy bohatera i tej samej
  # rewalidacji. Wcześniej fallback lead_* zmieniał nazwę i skalę wzorca.
  sources = (
    (champion_name, (1.60, 1.70, 1.80, 1.90, 2.00)),
    (champion_name.replace("arena_live_", "arena_live_lead_", 1),
     (0.94, 1.00, 1.06)),
  )
  base_scale = min(raid_rect[2] / 1024.0, raid_rect[3] / 769.0)
  # Referencyjne klatki mają zarówno 768, jak i 769 px wysokości.
  # Różnica 1 px nie powinna zmniejszać każdego template'u przez int().
  if abs(base_scale - 1.0) < 0.01:
    base_scale = 1.0
  scores = [0.0]
  for source_name, scales in sources:
    path = _leader_champion_template_path(source_name)
    if os.path.isfile(path):
      scores.append(VISION.best_score(crop, path, scales=scales, base_scale=base_scale))
  return max(scores)


def _leader_visual_priority(frame_bgr, raid_rect, picked=None, banned_slots=None, ctx=None):
  """
  Główna metoda wyboru lidera.

  Priorytet pochodzi z aktywnego profilu draftu i jest filtrowany
  do postaci realnie wybranych przez nas w tej walce.

  Każdy kandydat jest lokalizowany po zwykłym PNG championa w 5 konkretnych
  slotach. Kolejność PICK TRACK NIE jest używana jako pozycja na ekranie,
  bo nagranie pokazało, że gra przestawia championów przed Phase 3.
  """
  picked_order = list(picked or [])
  picked_set = set(picked_order)
  banned_slots = set(banned_slots or [])
  slot_count = len(LEADER_SLOT_CENTERS)

  # V15.2: leader priority comes from the active draft profile.  The engine
  # still falls back to the REAL picked order, so a user profile cannot stall
  # Phase 3 just because its preferred leader was not drafted.
  leader_keys = DRAFT_PROFILE.leader_order(picked_order)
  if ctx is not None:
    sig = tuple(leader_keys)
    if sig != ctx.get("leader_profile_order_signature"):
      ctx["leader_profile_order_signature"] = sig
      print("LEADER PROFILE ORDER: " + " > ".join(leader_keys))
  candidates = [DRAFT_PROFILE.pick_template_stem(name) for name in leader_keys]
  candidates = list(dict.fromkeys(candidates))

  diagnostics = {}

  for wanted in candidates:
    scores = [
      _leader_slot_champion_score(
        frame_bgr,
        raid_rect,
        slot_index,
        wanted,
      )
      for slot_index in range(slot_count)
    ]

    ordered = sorted(
      enumerate(scores),
      key=lambda pair: pair[1],
      reverse=True,
    )

    best_slot, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    margin = best_score - second_score

    diagnostics[wanted] = {
      "slot": best_slot,
      "score": best_score,
      "margin": margin,
      "banned": best_slot in banned_slots or _leader_slot_is_banned(
        frame_bgr,
        raid_rect,
        best_slot,
      ),
    }

  # V15.16: unique champion <-> leader-slot assignment.
  #
  # Previously every champion independently chose its best slot, so two names
  # could both map to S5 while the actually banned card (whose portrait is
  # covered by the red BAN symbol) remained unnamed.  Five cards means at most
  # 5! = 120 assignments, so exhaustive one-to-one assignment is effectively
  # free compared with template matching.
  mapping_keys = list(dict.fromkeys(list(leader_keys) + list(picked_order)))
  mapping_candidates = [
    DRAFT_PROFILE.pick_template_stem(name)
    for name in mapping_keys
  ]
  mapping_candidates = list(dict.fromkeys(mapping_candidates))[:slot_count]

  score_matrix = {}
  for wanted in mapping_candidates:
    if wanted in diagnostics:
      # Recompute the full vector; diagnostics only kept its best score.
      score_matrix[wanted] = [
        _leader_slot_champion_score(
          frame_bgr,
          raid_rect,
          slot_index,
          wanted,
        )
        for slot_index in range(slot_count)
      ]
    else:
      score_matrix[wanted] = [
        _leader_slot_champion_score(
          frame_bgr,
          raid_rect,
          slot_index,
          wanted,
        )
        for slot_index in range(slot_count)
      ]

  unique_assignment = {}
  unique_total = float("-inf")
  unique_second_total = float("-inf")

  if mapping_candidates and len(mapping_candidates) <= slot_count:
    for perm in itertools.permutations(
      range(slot_count),
      len(mapping_candidates),
    ):
      total = sum(
        score_matrix[name][slot]
        for name, slot in zip(mapping_candidates, perm)
      )
      if total > unique_total:
        unique_second_total = unique_total
        unique_total = total
        unique_assignment = dict(zip(mapping_candidates, perm))
      elif total > unique_second_total:
        unique_second_total = total

  if unique_assignment:
    assignment_gap = (
      unique_total - unique_second_total
      if unique_second_total != float("-inf")
      else unique_total
    )

    if ctx is not None:
      sig = tuple(
        (name, unique_assignment[name], round(score_matrix[name][unique_assignment[name]], 3))
        for name in mapping_candidates
      )
      if sig != ctx.get("leader_unique_map_signature"):
        ctx["leader_unique_map_signature"] = sig
        print(
          "LEADER UNIQUE MAP: "
          + " | ".join(
            f"{name.replace('arena_live_', '')}=S{unique_assignment[name] + 1}:"
            f"{score_matrix[name][unique_assignment[name]]:.3f}"
            for name in mapping_candidates
          )
          + f" | gap={assignment_gap:.3f}"
        )

    # Identify the banned champion from the UNIQUE map.
    if ctx is not None and banned_slots:
      banned_names = ctx.setdefault("leader_banned_champions", set())
      strong_assigned = {
        name
        for name, slot in unique_assignment.items()
        if score_matrix[name][slot] >= 0.62
      }

      for wanted, slot in unique_assignment.items():
        if slot not in banned_slots:
          continue

        score = float(score_matrix[wanted][slot])
        others = [name for name in unique_assignment if name != wanted]
        forced_by_elimination = (
          len(unique_assignment) == slot_count
          and len(banned_slots) == 1
          and all(name in strong_assigned for name in others)
        )

        if score >= 0.62 or forced_by_elimination:
          normalized = normalize_champion(wanted)
          banned_names.add(normalized)
          if forced_by_elimination and score < 0.62:
            forced_key = (normalized, slot)
            logged = ctx.setdefault("leader_forced_ban_logged", set())
            if forced_key not in logged:
              logged.add(forced_key)
              print(
                "LEADER BAN INFERRED -> "
                f"{normalized} / slot {slot + 1}; "
                "pozostałe 4 karty mają pewne unikalne przypisanie."
              )

  # V15.12: turn the visual banned slot back into a champion name.
  # The previous combat hint list still contained the champion banned by the
  # opponent (Arbiter in the 2026-10-01 replay), adding a false A1 candidate.
  # Only store a name when champion->slot mapping itself is confident.
  if ctx is not None:
    banned_names = ctx.setdefault("leader_banned_champions", set())
    for wanted, item in diagnostics.items():
      if (
        item.get("banned")
        and item.get("score", 0.0) >= 0.62
        and item.get("margin", 0.0) >= 0.12
      ):
        banned_names.add(normalize_champion(wanted))

  # Jeden czytelny log mapy zamiast mylącego PICK TRACK -> slot.
  signature = tuple((name, item["slot"], item["banned"],
                     item["score"] >= 0.62 and item["margin"] >= 0.12)
                    for name, item in diagnostics.items())
  log_map = ctx is None or signature != ctx.get("leader_map_signature")
  if ctx is not None:
    ctx["leader_map_signature"] = signature
  if diagnostics and log_map:
    parts = []
    for name in candidates:
      item = diagnostics.get(name)
      if item is None:
        continue
      short = name.replace("arena_live_", "")
      suffix = ",BAN" if item["banned"] else ""
      parts.append(
        f"{short}=S{item['slot'] + 1}:{item['score']:.3f}"
        f"/m{item['margin']:.3f}{suffix}"
      )
    print("LEADER MAP: " + " | ".join(parts))

  # Dopiero teraz stosujemy dokładny priorytet.
  for wanted in candidates:
    item = diagnostics.get(wanted)
    if item is None:
      continue

    # Z testu nagrania prawidłowe dopasowania:
    # Ankora .768, Mikage .823, Fabian .788, Harima .823.
    # Błędne dopasowania są < .46.
    if item["score"] < 0.62:
      continue

    if item["margin"] < 0.12:
      continue

    if item["banned"]:
      if log_map:
        print(
          f"LEADER: {wanted} rozpoznany w slocie {item['slot'] + 1}, "
          "ale jest zbanowany -> następny priorytet."
        )
      continue

    point = _leader_slot_point(
      raid_rect,
      item["slot"],
    )

    if point is not None:
      if log_map:
        print(
          f"LEADER PRIORITY: {wanted} -> slot {item['slot'] + 1}; "
          f"score={item['score']:.3f}; margin={item['margin']:.3f}"
        )
      return wanted, point, item["slot"]

  return None, None, None

def _leader_base_from_template_name(template_name):
  prefix = "arena_live_lead_"
  if template_name.startswith(prefix):
    return "arena_live_" + template_name[len(prefix):]
  return template_name


def _leader_from_tracked_slots(ctx, frame_bgr, raid_rect):
  """
  Historia picków służy WYŁĄCZNIE do informacji, kto został wybrany.

  Nie mapujemy już:
    picked[0] -> leader slot 1
    picked[1] -> leader slot 2
    ...

  Nagranie 2026-09-29 pokazało, że to założenie jest fałszywe.
  """
  return _leader_visual_priority(
    frame_bgr,
    raid_rect,
    picked=ctx.get("picked_champions", []),
    banned_slots=_leader_remember_bans(ctx, frame_bgr, raid_rect),
    ctx=ctx,
  )



def _leader_reset_selection(ctx):
  """Ponowny wybór zachowuje potwierdzone bany i historię tej fazy."""
  ctx["leader_pending"] = None
  ctx["leader_clicked"] = False
  ctx["leader_name"] = None
  ctx["leader_expected_slot"] = None
  ctx["leader_select_retries"] = 0
  ctx["leader_confirm_due"] = None
  ctx["leader_confirm_sent_at"] = None
  ctx["leader_confirm_retries"] = 0

  # Anti-spam / debounce dla Phase 3.
  # Te flagi resetujemy dopiero przy REALNYM ponownym wyborze lidera,
  # a nie przy pojedynczym frame, w którym matcher Confirm mrugnie.
  ctx["leader_verified_logged"] = False
  ctx["leader_confirm_scheduled_logged"] = False
  ctx["leader_confirm_missing_since"] = None


def _leader_state_tick(ctx, raid_rect, frame_bgr, matches):
  your_turn = matches["your_turn"]["found"]
  leader_visible = matches[STATE_LEADER]["found"]
  _update_turn_clock(ctx, your_turn)

  # Gdy ekran Pick Leader zniknie stabilnie, przechodzimy do COMBAT.
  if leader_visible:
    ctx["leader_phase_seen"] = True
    ctx["leader_missing_hits"] = 0
    _detect_final_combat_opponents(frame_bgr, ctx)
  elif ctx.get("leader_phase_seen"):
    ctx["leader_missing_hits"] = ctx.get("leader_missing_hits", 0) + 1

    if ctx["leader_missing_hits"] >= 5:
      print(
        "LEADER: ekran Pick Leader zniknął -> czekam na faktyczny start walki."
      )
      return STATE_LOADING

  if not (your_turn and leader_visible):
    if not ctx.get("leader_wait_logged"):
      print("LEADER: czekam na Pick Leader + Your Turn.")
      ctx["leader_wait_logged"] = True
    return None

  ctx["leader_wait_logged"] = False
  if not ctx.get("leader_fix_logged"):
    print("LEADER FIX v15.2: profile priority + safe picked-team fallback.")
    ctx["leader_fix_logged"] = True
  banned_slots = _leader_remember_bans(ctx, frame_bgr, raid_rect)
  expected_slot = ctx.get("leader_expected_slot")
  if expected_slot in banned_slots:
    print(f"LEADER: slot {expected_slot + 1} ma BAN -> anuluję kliknięcia i wybieram ponownie.")
    _leader_reset_selection(ctx)
    return None

  # Po wysłaniu Confirm sprawdzamy nadal tę samą postać i jej zieloną ramkę.
  if ctx.get("leader_confirm_sent_at") is not None:
    now = _active_time()

    if leader_visible and now - ctx["leader_confirm_sent_at"] > 0.85:
      confirm = _frame_match(
        frame_bgr,
        "./bilder/arena_live_confirm_pick.PNG",
        confidence=0.76,
        grayscale=False,
      )

      selected, _ = _leader_selected_slot(frame_bgr, raid_rect)
      identity_score = (_leader_slot_champion_score(
        frame_bgr, raid_rect, expected_slot, ctx["leader_name"]
      ) if expected_slot is not None and ctx.get("leader_name") else 0.0)
      if (confirm["found"] and selected == expected_slot and identity_score >= 0.62
          and ctx.get("leader_confirm_retries", 0) < 2):
        ctx["leader_confirm_retries"] = ctx.get("leader_confirm_retries", 0) + 1
        print(
          f"LEADER: Confirm nadal aktywny -> retry "
          f"{ctx['leader_confirm_retries']}."
        )
        clicked = _human_click(
          calibrated_leader_confirm_point(raid_rect),
          0.10,
          0.22,
        )
        if clicked:
          ctx["leader_confirm_sent_at"] = now

    return None

  # ----------------------------------------------------------
  # Lider został kliknięty. ZANIM dopuścimy Confirm, sprawdzamy
  # zieloną obwódkę dokładnie na oczekiwanym slocie.
  # ----------------------------------------------------------
  if ctx.get("leader_clicked"):
    expected_slot = ctx.get("leader_expected_slot")
    identity_score = (_leader_slot_champion_score(
      frame_bgr, raid_rect, expected_slot, ctx["leader_name"]
    ) if expected_slot is not None and ctx.get("leader_name") else 0.0)
    if identity_score < 0.62:
      print("LEADER VERIFY: portret nie potwierdza wybranej postaci -> ponowny odczyt.")
      _leader_reset_selection(ctx)
      return None
    selected_slot, selection_scores = _leader_selected_slot(
      frame_bgr,
      raid_rect,
    )
    selected_ok = (
      expected_slot is not None
      and selected_slot == expected_slot
    )

    if not selected_ok:
      ctx["leader_confirm_due"] = None
      elapsed = _active_time() - ctx.get("leader_clicked_at", 0.0)

      if elapsed < 0.30:
        return None

      retries = ctx.get("leader_select_retries", 0)
      if retries < 2 and expected_slot is not None:
        point = _leader_slot_point(raid_rect, expected_slot)
        print(
          f"LEADER VERIFY: {ctx.get('leader_name')} nie jest podświetlony "
          f"-> ponawiam slot {expected_slot + 1}."
        )
        clicked = _human_click(point, 0.12, 0.26)
        if clicked:
          ctx["leader_select_retries"] = retries + 1
          ctx["leader_clicked_at"] = _active_time()
        return None

      print(
        f"LEADER VERIFY: nie udało się potwierdzić wyboru "
        f"{ctx.get('leader_name')} -> wybieram ponownie."
      )
      _leader_reset_selection(ctx)
      return None

    # Lider i zielona obwódka są już potwierdzone.
    #
    # V3 anti-spam:
    # - "LEADER VERIFIED" drukujemy tylko RAZ dla danego wyboru;
    # - pojedynczy frame, w którym matcher Confirm nie znajdzie przycisku,
    #   NIE zeruje leader_confirm_due;
    # - dzięki temu migotanie template'u Confirm nie uzbraja timera od nowa
    #   i nie produkuje kilkunastu identycznych logów.
    if not ctx.get("leader_verified_logged"):
      print(
        f"LEADER VERIFIED: {ctx.get('leader_name')} / "
        f"slot {expected_slot + 1}; "
        f"border={[round(v, 3) for v in selection_scores]}."
      )
      ctx["leader_verified_logged"] = True

    confirm = _frame_match(
      frame_bgr,
      "./bilder/arena_live_confirm_pick.PNG",
      confidence=0.76,
      grayscale=False,
    )

    now = _active_time()

    if confirm["found"]:
      ctx["leader_confirm_missing_since"] = None

      if ctx.get("leader_confirm_due") is None:
        delay = _draft_delay(ctx)
        ctx["leader_confirm_due"] = now + delay

        if not ctx.get("leader_confirm_scheduled_logged"):
          print(f"LEADER: Confirm za {delay:.2f}s.")
          ctx["leader_confirm_scheduled_logged"] = True

        return None

      if now >= ctx["leader_confirm_due"]:
        print(f"LEADER: zatwierdzam {ctx.get('leader_name')}.")
        clicked = _human_click(
          calibrated_leader_confirm_point(raid_rect),
          0.12,
          0.28,
        )
        if not clicked:
          print("LEADER: Confirm zakłócony -> ponawiam.")
          # Zachowujemy LEADER VERIFIED jako zalogowane.
          # Losujemy nowy timer dopiero dla realnie nieudanego kliknięcia.
          ctx["leader_confirm_due"] = None
          ctx["leader_confirm_scheduled_logged"] = False
          return None

        ctx["leader_confirm_due"] = None
        ctx["leader_confirm_sent_at"] = now
        ctx["leader_confirm_retries"] = 0
        return None

      return None

    # Confirm nie został znaleziony w TEJ jednej klatce.
    # Nie resetujemy timera. W nagraniu matcher migotał między kolejnymi tickami,
    # co było bezpośrednią przyczyną spamu "LEADER VERIFIED".
    if ctx.get("leader_confirm_missing_since") is None:
      ctx["leader_confirm_missing_since"] = now

    return None

  # ----------------------------------------------------------
  # Zaplanowane kliknięcie lidera.
  # ----------------------------------------------------------
  pending = ctx.get("leader_pending")
  if pending:
    if _active_time() < pending["due"]:
      return None

    # Rewalidacja PRIORYTETU i bana, nie tylko samej podobizny.
    # Punkt liczymy ponownie, ponieważ okno mogło zostać przesunięte.
    current_name, current_point, current_slot = _leader_from_tracked_slots(
      ctx, frame_bgr, raid_rect
    )
    if (current_name, current_slot) != (pending["name"], pending["slot_index"]):
      print("LEADER RECHECK: priorytet / ban zmienił się -> ponowny wybór.")
      ctx["leader_pending"] = None
      return None

    verify_score = _leader_slot_champion_score(
      frame_bgr,
      raid_rect,
      pending["slot_index"],
      pending["name"],
    )
    verify_banned = pending["slot_index"] in banned_slots

    if verify_score < 0.62 or verify_banned:
      print(
        f"LEADER RECHECK: {pending['name']} / slot "
        f"{pending['slot_index'] + 1} niepewny "
        f"(score={verify_score:.3f}, banned={verify_banned}) "
        "-> skanuję priorytet ponownie."
      )
      ctx["leader_pending"] = None
      return None

    print(
      f"LEADER: wybieram {pending['name']} "
      f"(slot {pending['slot_index'] + 1}, "
      f"score={verify_score:.3f})."
    )
    clicked = _human_click(current_point, 0.16, 0.34)

    if clicked:
      ctx["leader_name"] = pending["name"]
      ctx["leader_clicked"] = True
      ctx["leader_clicked_at"] = _active_time()
      ctx["leader_expected_slot"] = pending["slot_index"]
      ctx["leader_select_retries"] = 0

    ctx["leader_pending"] = None
    return None

  # ----------------------------------------------------------
  # 1) GŁÓWNE ŹRÓDŁO: wizualna mapa 5 slotów + historia picków jako filtr.
  #
  # NIE zakładamy już, że kolejność PICK TRACK == układ kart w Phase 3.
  # Priorytet pochodzi z aktywnego profilu; zbanowany kandydat jest
  # pomijany, a bot przechodzi do następnego lidera z profilu.
  # ----------------------------------------------------------
  leader_name, leader_point, slot_index = _leader_from_tracked_slots(
    ctx,
    frame_bgr,
    raid_rect,
  )

  if leader_point is not None:
    delay = _draft_delay(ctx)
    ctx["leader_pending"] = {
      "name": leader_name,
      "slot_index": slot_index,
      "due": _active_time() + delay,
    }
    print(
      f"LEADER READY: {leader_name} / slot {slot_index + 1} "
      f"za {delay:.2f}s."
    )
    return None

  # Oba rodzaje PNG są już oceniane we wspólnym matcherze. Nie zapisujemy
  # losowy_slot_* jako nazwy bohatera — takiego template'u nie da się potem
  # zweryfikować i stary fallback zapętlał się w LEADER RECHECK.
  now = _active_time()
  if now - ctx.get("leader_no_candidate_logged_at", float("-inf")) >= 2.0:
    print("LEADER: brak pewnego, niezbanowanego lidera z priorytetu -> ponawiam odczyt.")
    ctx["leader_no_candidate_logged_at"] = now
  return None


def _conductBattle():
  """
  Jeden jawny state machine:
    PICK -> BAN -> LEADER -> COMBAT -> RESULT/DONE

  Wszystkie detekcje draftu w jednym ticku pracują na jednym screenshotcie.
  """
  if errorhandling.gameReset() == "skip":
    return

  raid_rect = _find_raid_client_rect()
  if raid_rect is None:
    errorManager.error_detected = True
    return

  ctx = {
    "state": STATE_PICK,
    "phase_candidate": None,
    "phase_candidate_hits": 0,
    "your_turn_active": False,
    "turn_started_at": None,

    "filter_applied": False,
    "champion_order": 0,
    "picked_champions": [],
    "opponent_champions": set(),
    "opponent_profile_signature": None,
    "final_opponent_champions": set(),
    "final_opponent_condition_scores": {},
    "pick_no_candidate_logged_at": float("-inf"),
    "pick_clicked_name": None,
    "pick_pending": None,
    "pick_selected_at": None,
    "pick_confirm_due": None,
    "pick_wait_logged": False,

    "ban_clicked": False,
    "ban_target_due": None,
    "ban_name": None,
    "ban_clicked_at": None,
    "ban_confirm_due": None,
    "ban_confirm_sent_at": None,
    "ban_confirm_retries": 0,
    "ban_wait_logged": False,

    "leader_pending": None,
    "leader_clicked": False,
    "leader_name": None,
    "leader_expected_slot": None,
    "leader_select_retries": 0,
    "leader_clicked_at": None,
    "leader_confirm_due": None,
    "leader_confirm_sent_at": None,
    "leader_confirm_retries": 0,

    # Phase 3 console anti-spam / Confirm debounce.
    "leader_verified_logged": False,
    "leader_confirm_scheduled_logged": False,
    "leader_confirm_missing_since": None,

    "leader_gone_hits": 0,
    "leader_phase_seen": False,
    "leader_missing_hits": 0,
    "leader_wait_logged": False,
    "leader_banned_slots": set(),
    # V15.12: names confidently mapped to the red banned leader slot.
    # These champions must NOT be passed to combat identity as active-team hints.
    "leader_banned_champions": set(),

    "battle_ready_owner": None,
    "battle_ready_hits": 0,
    "loading_wait_logged": False,

    "last_aux_check": 0.0,
  }

  _set_live_state(STATE_PICK)

  # Long opponent/draft waits are valid; progress is driven only by
  # fresh UI evidence and the explicit state machine.

  while ctx["state"] not in (STATE_DONE,):
    _wait_if_paused()

    # LOADING: po Pick Leader NIE uruchamiamy jeszcze combat engine.
    # Czekamy aż gra faktycznie narysuje pole walki i zieloną ramkę
    # jednego z dwóch portretów graczy.
    if ctx["state"] == STATE_LOADING:
      current_rect = _find_raid_client_rect()
      if current_rect is not None:
        raid_rect = current_rect

      raid_rect, frame_bgr = _capture_raid_frame(raid_rect)
      if frame_bgr is None:
        _pauseable_sleep(STATE_TICK_SECONDS)
        continue

      owner = detect_combat_turn_owner(frame_bgr)

      if owner is None:
        ctx["battle_ready_owner"] = None
        ctx["battle_ready_hits"] = 0

        if not ctx.get("loading_wait_logged"):
          print("LOADING: oczekuję na faktyczny start pola walki.")
          ctx["loading_wait_logged"] = True

        _pauseable_sleep(0.08)
        continue

      ctx["loading_wait_logged"] = False

      if owner == ctx.get("battle_ready_owner"):
        ctx["battle_ready_hits"] += 1
      else:
        ctx["battle_ready_owner"] = owner
        ctx["battle_ready_hits"] = 1

      if ctx["battle_ready_hits"] >= 2:
        print(
          f"LOADING: walka gotowa; pierwsza wykryta tura={owner}."
        )
        ctx["state"] = STATE_COMBAT
        _set_live_state(STATE_COMBAT)
      else:
        _pauseable_sleep(0.06)

      continue

    # COMBAT ma własny szybki loop dopiero po potwierdzonym battle-ready.
    if ctx["state"] == STATE_COMBAT:
      _set_live_state(STATE_COMBAT)

      picked = list(ctx.get("picked_champions", []))
      banned = {
        normalize_champion(x)
        for x in ctx.get("leader_banned_champions", set())
        if normalize_champion(x)
      }
      active_team = [
        name
        for name in picked
        if normalize_champion(name) not in banned
      ]

      # Safety fallback: a Live Arena battle normally has 4 champions.
      # If visual ban mapping was incomplete, keep the original list rather than
      # accidentally throwing away multiple candidates.
      if not active_team or len(active_team) < max(1, len(picked) - 1):
        active_team = picked

      print(
        f"COMBAT ACTIVE TEAM HINTS: {active_team} "
        f"(banned={sorted(banned)})"
      )
      # V16.1: autonomy needs the FULL opponent draft history, while special
      # champion opener rules (e.g. Fabian vs Gliseah) need the conservative
      # fresh post-ban scan.  V16 accidentally used the fresh condition set for
      # both, which produced COMBAT OPPONENT HINTS: [] in the first test battle.
      opponent_team = {
        normalize_champion(name)
        for name in ctx.get("opponent_champions", set())
        if normalize_champion(name)
      }
      condition_team = {
        normalize_champion(name)
        for name in (ctx.get("final_opponent_champions") or set())
        if normalize_champion(name)
      }

      our_ban = normalize_champion(ctx.get("ban_name"))
      if our_ban and our_ban != "slot_1":
        opponent_team.discard(our_ban)
        condition_team.discard(our_ban)

      print(
        f"COMBAT OPPONENT HINTS: {sorted(opponent_team)} "
        f"(conditions={sorted(condition_team)}, our_ban={our_ban or 'unknown'})"
      )
      _executeManualCombat(
        active_team,
        opponent_team,
        condition_team,
      )
      ctx["state"] = STATE_DONE
      _set_live_state(STATE_DONE)
      break

    current_rect = _find_raid_client_rect()
    if current_rect is not None:
      raid_rect = current_rect

    raid_rect, frame_bgr = _capture_raid_frame(raid_rect)
    if frame_bgr is None:
      _pauseable_sleep(STATE_TICK_SECONDS)
      continue

    _diagnostic_snapshot(
      frame_bgr,
      raid_rect,
      state=ctx["state"],
    )

    matches = _phase_matches(frame_bgr, ctx["state"])
    observed = _observed_phase(matches)
    stable_transition = _stable_phase_transition(ctx, observed)

    if stable_transition is not None:
      # Nie cofamy się w fazach draftu.
      order = {
        STATE_PICK: 1,
        STATE_BAN: 2,
        STATE_LEADER: 3,
      }
      if order.get(stable_transition, 0) > order.get(ctx["state"], 0):
        ctx["state"] = stable_transition
        _set_live_state(stable_transition)
        # Nowa faza = nowy zegar tury.
        ctx["your_turn_active"] = False
        ctx["turn_started_at"] = None

    next_state = None

    if ctx["state"] == STATE_PICK:
      next_state = _pick_state_tick(ctx, raid_rect, frame_bgr, matches)

    elif ctx["state"] == STATE_BAN:
      next_state = _ban_state_tick(ctx, raid_rect, frame_bgr, matches)

    elif ctx["state"] == STATE_LEADER:
      next_state = _leader_state_tick(ctx, raid_rect, frame_bgr, matches)

    if next_state is not None and next_state != ctx["state"]:
      ctx["state"] = next_state
      _set_live_state(next_state)
      ctx["your_turn_active"] = False
      ctx["turn_started_at"] = None

    # Rzadkie kontrole awaryjne również korzystają z tej samej klatki.
    now = _active_time()
    if now - ctx["last_aux_check"] >= 0.50:
      ctx["last_aux_check"] = now

      opponent_left = _frame_match(
        frame_bgr,
        "./bilder/arena_live_opponent_left.PNG",
        confidence=0.88,
        grayscale=True,
      )
      if opponent_left["found"]:
        print("Przeciwnik opuścił Live Arenę.")
        # Opponent-left can happen before CombatEngine starts (PICK/BAN/LEADER).
        # In that case click the actual RETURN TO ARENA button and verify that
        # RAID consumed the click before leaving _conductBattle.
        if _return_to_arena_after_opponent_left():
          return
        # Do not fall through to POST-BATTLE with the result screen still open.
        # Keep the draft loop alive so the next auxiliary tick can retry.
        ctx["last_aux_check"] = _active_time() - 0.50
        _pauseable_sleep(0.12)
        continue

      cant_find = _frame_match(
        frame_bgr,
        "./bilder/arena_live_cant_find_opponent.PNG",
        confidence=0.88,
        grayscale=True,
      )
      if cant_find["found"]:
        print("Nie znaleziono przeciwnika -> Refind.")
        shared.clickWrap("arena_live_refind")


    # V11.5:
    # podczas PICK nie wypisujemy cyklicznych PERF[...] do konsoli.
    # W tej fazie ważniejsze są czytelne logi wyboru championów/state.
    if ctx["state"] != STATE_PICK:
      VISION.maybe_log_performance(
        ctx["state"],
        PERF_LOG_INTERVAL_SECONDS,
      )

    _pauseable_sleep(STATE_TICK_SECONDS)


def _find_raid_client_rect():
  """
  Zwraca client rect właściwego okna Raid: Shadow Legends.
  Loguje WYŁĄCZNIE pierwsze wykrycie albo realną zmianę pozycji/rozmiaru.
  """
  global _last_raid_rect_logged, _last_raid_missing_log_at

  user32 = ctypes.windll.user32
  candidates = []

  @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
  def enum_proc(hwnd, lparam):
    if not user32.IsWindowVisible(hwnd):
      return True

    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
      return True

    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    title = buf.value.strip()
    normalized = title.lower().strip()

    if normalized not in {
      "raid: shadow legends",
      "raid shadow legends",
    }:
      return True

    rect = wintypes.RECT()
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
      w = rect.right - rect.left
      h = rect.bottom - rect.top
      if w >= 700 and h >= 500:
        candidates.append((hwnd, title, w, h))

    return True

  user32.EnumWindows(enum_proc, 0)

  if not candidates:
    now = _active_time()
    if now - _last_raid_missing_log_at >= 5.0:
      print("Nie znaleziono aktywnego okna Raid: Shadow Legends.")
      _last_raid_missing_log_at = now
    return None

  hwnd, title, w, h = max(candidates, key=lambda v: v[2] * v[3])

  p = wintypes.POINT(0, 0)
  if not user32.ClientToScreen(hwnd, ctypes.byref(p)):
    return None

  result = (p.x, p.y, w, h)

  # Koniec spamu: zapis/print tylko gdy okno faktycznie się zmieniło.
  if result != _last_raid_rect_logged:
    if _last_raid_rect_logged is None:
      print(f"OKNO RAID wykryte: client={result}")
    else:
      print(f"OKNO RAID zmienione: {_last_raid_rect_logged} -> {result}")

    _last_raid_rect_logged = result

    try:
      os.makedirs("./textfiles", exist_ok=True)
      with open("./textfiles/raid_window_rect.txt", "w", encoding="utf-8") as f:
        f.write(
          f"{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
          f"title={title}\n"
          f"left={p.x}\ntop={p.y}\nwidth={w}\nheight={h}\n"
        )
    except Exception:
      pass

  return result



def _rel_point(rect, x, y):
  """Punkt z referencji 1020x793 -> aktualne okno RAID."""
  left, top, w, h = rect
  return (
    left + round(x * w / 1020.0),
    top + round(y * h / 793.0),
  )


def _rel_region(rect, x1, y1, x2, y2):
  """Prostokąt z referencji 1020x793 -> region pyautogui."""
  left, top, w, h = rect
  x = left + round(x1 * w / 1020.0)
  y = top + round(y1 * h / 793.0)
  x_end = left + round(x2 * w / 1020.0)
  y_end = top + round(y2 * h / 793.0)
  return (x, y, max(1, x_end-x), max(1, y_end-y))


def _safe_locate(path, region=None, grayscale=False, confidence=0.82):
  if not os.path.exists(path):
    return None

  search_rect = region
  auto_roi = False

  if search_rect is None:
    search_rect = _last_raid_rect_logged or _find_raid_client_rect()
    auto_roi = True

  if search_rect is None:
    return None

  frame = VISION.capture(search_rect)
  if frame is None:
    return None

  match = VISION.match(
    frame,
    path,
    confidence=confidence,
    grayscale=grayscale,
    auto_roi=auto_roi,
  )
  if not match["found"]:
    return None

  x, y, w, h = match["box"]
  left, top, _, _ = search_rect
  return (left + x, top + y, w, h)


def _executeManualCombat(
  picked_champions=None,
  opponent_champions=None,
  combat_condition_champions=None,
):
  """Deleguje walkę z own-team, pełnym enemy model i osobnym condition set."""
  engine = CombatEngine(
    vision=VISION,
    mouse=MOUSE,
    find_raid_rect=_find_raid_client_rect,
    wait_if_paused=_wait_if_paused,
    sleep_func=_pauseable_sleep,
    set_state=_set_live_state,
    consume_diagnostic=_consume_diagnostic_request,
    debug_dir="./debug",
    active_families=tuple(picked_champions or ()),
    opponent_families=tuple(opponent_champions or ()),
    combat_condition_families=tuple(combat_condition_champions or ()),
  )
  engine.run()


def _initArenaLive():
  if errorhandling.gameReset() == "skip":
    return
  _wait_if_paused()
  shared.clickWrap("battle")
  _wait_if_paused()
  shared.clickWrap("arena")
  _wait_if_paused()
  shared.clickWrap("arena_live")


def _dismiss_refill_modal():
  """Zamyka modal refilla bez klikania przycisku zakupu.

  ESC jest bezpieczniejszy niż zgadywanie pozycji X i nie może kupić refilla.
  Po wznowieniu z pauzy zawsze najpierw sprawdzamy świeży stan UI.
  """
  _wait_if_paused()
  try:
    pyautogui.press("esc")
  except Exception:
    return False

  _pauseable_sleep(0.12)
  still_modal = _safe_locate(
    "./bilder/live_arena_refyll_modal.PNG",
    grayscale=True,
    confidence=0.76,
  )
  return not bool(still_modal)


def _detect_paid_refill():
  """Zwraca (cost, box, template_path) dla ceny <= limitu.

  Dla bezpieczeństwa sprawdzamy tylko jawnie dozwolone ceny 10/20/25.
  Jeśli na modalu jest droższa cena (np. 40) albo wzorca brak, wynik jest
  nieznany i bot NICZEGO nie kliknie.
  """
  found = []
  for cost in PAID_REFILL_ALLOWED_COSTS:
    if cost > MAX_GEM_REFILL_COST:
      continue
    for spelling in ("refyll", "refill"):
      path = f"./bilder/arena_live_{cost}gem_{spelling}.PNG"
      if not os.path.exists(path):
        continue
      match = _safe_locate(
        path,
        grayscale=True,
        confidence=0.82,
      )
      if match:
        found.append((int(cost), match, path))
        break

  if len(found) != 1:
    return None, None, None
  return found[0]


def _wait_for_refill_return(timeout=3.0):
  """Po zakupie czeka aż modal zniknie i wróci aktywny Find Opponent.

  Sam zakup refilla NIE uruchamia matchmakingu. Dopiero po świeżym wykryciu
  Find Opponent wracamy do _haveBattlesLeft() i klikamy go ponownie.
  """
  end = _active_time() + max(0.0, timeout)
  modal_was_seen = False

  while _active_time() < end:
    _wait_if_paused()

    modal = _safe_locate(
      "./bilder/live_arena_refyll_modal.PNG",
      grayscale=True,
      confidence=0.76,
    )
    if modal:
      modal_was_seen = True
      _pauseable_sleep(0.10)
      continue

    find_again = _safe_locate(
      "./bilder/arena_live_find_opponent.PNG",
      grayscale=False,
      confidence=0.82,
    )
    if find_again:
      return True

    # Toast "You received Live Arena Refill" może przez chwilę zasłaniać UI.
    _pauseable_sleep(0.10)

  if modal_was_seen:
    print("REFILL: modal zniknął, ale Find Opponent nie wrócił w terminie.")
  else:
    print("REFILL: brak potwierdzenia powrotu do głównego ekranu Live Arena.")
  return False


def _wait_for_matchmaking_after_click(clicked_at, max_ticks=28):
  """Obserwuje UI po kliknięciu Find Opponent.

  Zwraca jeden z: draft, searching, refill, click_not_accepted, timeout.
  Nie wykonuje żadnego zakupu ani kolejnego kliknięcia Find Opponent.
  """
  for _ in range(max_ticks):
    _wait_if_paused()

    # Najpierw modal refilla. To ważne: zniknięcie Find Opponent pod modalem
    # NIE może być potraktowane jako rozpoczęty matchmaking.
    refill_modal = _safe_locate(
      "./bilder/live_arena_refyll_modal.PNG",
      grayscale=True,
      confidence=0.78,
    )
    refill_confirm = _safe_locate(
      "./bilder/arena_live_confirm_refyll.PNG",
      grayscale=False,
      confidence=0.75,
    )
    if refill_modal or refill_confirm:
      return "refill", refill_modal, refill_confirm

    pick_screen = _safe_locate(
      "./bilder/arena_live_pick_your_champions.PNG",
      grayscale=True,
      confidence=0.88,
    )
    if pick_screen:
      return "draft", None, None

    cant_find = _safe_locate(
      "./bilder/arena_live_cant_find_opponent.PNG",
      grayscale=True,
      confidence=0.86,
    )
    if cant_find:
      return "searching", None, None

    if _active_time() - clicked_at >= MATCHMAKING_CLICK_VERIFY_SECONDS:
      still_find = _safe_locate(
        "./bilder/arena_live_find_opponent.PNG",
        grayscale=False,
        confidence=0.82,
      )
      if still_find:
        return "click_not_accepted", None, None

    rect, frame = _capture_raid_frame()
    if frame is not None:
      _diagnostic_snapshot(frame, rect, state=STATE_MATCHMAKING)

    _pauseable_sleep(0.20)

  # Ostatnia kontrola po wyjściu z pętli. Brak Find Opponent oznacza
  # matchmaking tylko wtedy, gdy nie ma modala refilla.
  refill_modal = _safe_locate(
    "./bilder/live_arena_refyll_modal.PNG",
    grayscale=True,
    confidence=0.78,
  )
  if refill_modal:
    return "refill", refill_modal, None

  find_after = _safe_locate(
    "./bilder/arena_live_find_opponent.PNG",
    grayscale=False,
    confidence=0.82,
  )
  if not find_after:
    return "searching", None, None

  return "timeout", None, None


def _haveBattlesLeft(post_battle=False):
  if errorhandling.gameReset() == "skip":
    return False

  _wait_if_paused()

  # Jeden refill (darmowy lub płatny) przywraca walki, ale NIE rozpoczyna
  # matchmakingu. Po zakupie/odebraniu refilla zawsze wracamy do głównego
  # ekranu, świeżo wykrywamy Find Opponent i klikamy go jeszcze raz.
  refill_used = False

  for matchmaking_attempt in range(2):
    # V15.17:
    # Po zakończonej walce CombatEngine wraca już na ekran Live Arena, ale
    # serwer może nadal przetwarzać wynik. Na nagraniu 2026-10-01 przycisk
    # Find Opponent pojawił się dopiero kilka sekund po "Processing Results...".
    #
    # Pierwsze wejście do Live Arena zachowuje krótki 2 s gate. Po realnej
    # walce dajemy UI do 20 s na powrót. Co ważne: timeout post-battle NIE
    # ustawia 15-minutowego ARENA_CLOSED_RECHECK_SECONDS.
    find_timeout = (
      POST_BATTLE_RESULTS_TIMEOUT_SECONDS
      if post_battle and matchmaking_attempt == 0
      else 2.0
    )
    if post_battle and matchmaking_attempt == 0:
      print(
        "POST-BATTLE: czekam aż Processing Results zakończy się "
        "i wróci Find Opponent."
      )

    find_button = _find_opponent_button(timeout=find_timeout)
    if not find_button:
      if post_battle:
        print(
          "POST-BATTLE: Find Opponent nadal niewidoczny po "
          f"{find_timeout:.0f}s -> nadal traktuję to jako stan przejściowy; kończę cykl BEZ 15-minutowego "
          "Live Arena closed gate."
        )
        return False

      _mark_arena_closed("Find Opponent nie jest dostępny")
      return False

    if post_battle and matchmaking_attempt == 0:
      print("POST-BATTLE: wyniki przetworzone; Find Opponent jest gotowy.")
      _set_live_state(STATE_MATCHMAKING)

    print(
      "MATCHMAKING: aktywny Find Opponent wykryty -> klik"
      + (" po refillu." if refill_used else ".")
    )
    if not _human_click(find_button, 0.14, 0.30):
      print("MATCHMAKING: Mouse Guard anulował Find Opponent.")
      return False

    clicked_at = _active_time()
    status, refill_modal, refill_confirm = _wait_for_matchmaking_after_click(
      clicked_at,
      max_ticks=28,
    )

    if status == "draft":
      print("MATCHMAKING: draft potwierdzony.")
      _clear_arena_closed_gate()
      return True

    if status == "searching":
      print("MATCHMAKING: wyszukiwanie przeciwnika potwierdzone.")
      _clear_arena_closed_gate()
      return True

    if status == "click_not_accepted":
      if matchmaking_attempt == 0:
        print(
          "MATCHMAKING: Find Opponent nadal aktywny po kliknięciu -> "
          "ponawiam jeden raz; Arena jest otwarta."
        )
        _pauseable_sleep(0.35)
        continue

      print(
        "MATCHMAKING: drugi klik Find Opponent nie został przyjęty -> "
        "kończę ten cykl BEZ 15-minutowego closed gate."
      )
      return False

    if status == "refill":
      print("REFILL WYKRYTY.")

      if refill_used:
        print("REFILL: drugi modal po refillu -> stop bez kolejnego zakupu.")
        _dismiss_refill_modal()
        return False

      # 1) Najpierw darmowy Confirm, jeśli naprawdę jest widoczny.
      if refill_confirm:
        print("REFILL: klikam potwierdzony darmowy refill.")
        if not _human_click(refill_confirm, 0.14, 0.30):
          print("REFILL: Mouse Guard anulował darmowy Confirm.")
          return False
        refill_used = True

      else:
        # 2) Płatny refill: rozpoznaj cenę PRZED kliknięciem.
        cost, paid_button, paid_template = _detect_paid_refill()

        if cost is None or paid_button is None:
          print(
            "REFILL: płatny modal, ale cena nie została jednoznacznie "
            "rozpoznana -> NIE KLIKAM."
          )
          _dismiss_refill_modal()
          return False

        if cost > MAX_GEM_REFILL_COST:
          print(
            f"REFILL: koszt {cost} gemów > limit {MAX_GEM_REFILL_COST} "
            "-> NIE KUPUJĘ."
          )
          _dismiss_refill_modal()
          return False

        print(
          f"REFILL: kupuję refill za {cost} gemów "
          f"(limit={MAX_GEM_REFILL_COST})."
        )
        if not _human_click(paid_button, 0.14, 0.30):
          print("REFILL: Mouse Guard anulował zakup.")
          return False
        refill_used = True

      # KLUCZOWA POPRAWKA Z NAGRANIA 20:51:
      # zakup/odbiór tylko zamyka modal i przywraca liczbę walk. Nie wolno
      # zwrócić True ani przejść MATCHMAKING -> PICK. Najpierw czekamy na
      # powrót Find Opponent, a następnie zaczynamy DRUGĄ próbę matchmakingu.
      if not _wait_for_refill_return(timeout=3.0):
        print("REFILL: nie udało się wrócić do aktywnego Find Opponent.")
        return False

      print("REFILL: Find Opponent wrócił -> ponawiam start matchmakingu.")
      continue

    if matchmaking_attempt == 0:
      print(
        "MATCHMAKING: brak jednoznacznego potwierdzenia po kliknięciu -> "
        "ponawiam raz bez ustawiania closed gate."
      )
      _pauseable_sleep(0.35)
      continue

    print(
      "MATCHMAKING: brak potwierdzenia po drugiej próbie -> "
      "kończę cykl BEZ 15-minutowego closed gate."
    )
    return False

  print("MATCHMAKING: nie udało się rozpocząć walki po refillu.")
  return False


def _claimChest():
  if errorhandling.gameReset() == "skip":
    return
  print("_claimChest")
  claim_chest = pyautogui.locateOnScreen(
      "./bilder/arena_live_claim_chest.PNG",
      grayscale=True,
      confidence=0.97,
      minSearchTime=3,
  )
  if claim_chest:
    shared.clickWrap("arena_live_claim_chest")
    shared.clickWrap("arena_live_claim_chest2")
  else:
    print("no chest to collect")


def _exitArena():
  if errorhandling.gameReset() == "skip":
    return
  print("_exitArena")
  shared.clickWrap("close_arena")
  shared.clickWrap("bastion")
  try:
    closeadds.closeAdds(
      wait_if_paused=_wait_if_paused,
      sleep_func=_pauseable_sleep,
    )
  except TypeError:
    # Zgodność ze starszym closeadds.py; najnowszy moduł obsługuje hooki.
    closeadds.closeAdds()


def _arenaIsActive():
  if errorhandling.gameReset() == "skip":
    return

  # Standard Live Arena availability marker.
  result = pyautogui.locateOnScreen(
      "./bilder/battle_arenalive.PNG",
      grayscale=True,
      confidence=0.95,
      minSearchTime=1,
  )
  if result:
    print("arena live is open")
    return True

  # Win Streak can replace/hide the normal Live Arena marker in Bastion.
  # Treat it as an independent proof that Live Arena is currently available.
  win_streak_template = "./bilder/arena_live_win_streak.png"
  if os.path.exists(win_streak_template):
    win_streak = pyautogui.locateOnScreen(
        win_streak_template,
        grayscale=False,
        confidence=0.82,
        minSearchTime=1,
    )
    if win_streak:
      print("arena live is open (LA Win Streak detected)")
      return True
  else:
    print("LIVE ARENA: brak ./bilder/arena_live_win_streak.png; pomijam detekcję Win Streak.")

  print("arena live is not active")
  return False


def _collectRefylls():
  if errorhandling.gameReset() == "skip":
    return
  print("_collectRefylls")
  result = pyautogui.locateOnScreen(
      "./bilder/live_arena_battles55.PNG",
      grayscale=False,
      confidence=0.99,
      minSearchTime=4,
  )
  if result:
    print("collecting refylls")
    shared.clickWrap("arena_live_collect_refyll")
  else:
    print("no refylls to collect")


def __ready_to_run_livearena():
  try:
    with open("./textfiles/arenalive.txt", "r") as file:
      execution_datetime_str = file.read().strip()
      executed_last_time = datetime.strptime(
          execution_datetime_str, "%d.%m.%Y %H:%M:%S"
      )
      current_datetime = datetime.now()

      if executed_last_time.date() == current_datetime.date():
        print("Allready did run today")
        return False
      else:
        print("Ready to run")
        return True
  except FileNotFoundError:
    return True


if __name__ == "__main__":
  _print_startup_greeting()

  # Offline: py arenalive.py --test-ui "screen.png"
  # W tym trybie bot NIE klika i NIE uruchamia Live Areny.
  if not _run_test_mode_from_argv(sys.argv):
    flagInstance.no_cvc = True
    main()
