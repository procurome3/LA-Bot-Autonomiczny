import datetime
import errorhandling
from flags import flagInstance
import json
import math
import random
import time
import pyautogui


# ============================================================
# GLOBAL PAUSE BRIDGE
# ============================================================
# Arenalive registers its pause hooks once at startup.  Other modules may keep
# using shared.py unchanged; when no hooks are registered these helpers behave
# exactly like ordinary time.sleep/clicks.
_WAIT_IF_PAUSED = None
_SLEEP_FUNC = None


def configure_pause(wait_if_paused=None, sleep_func=None):
  """Attach the Live Arena pause barrier without importing arenalive (no cycle)."""
  global _WAIT_IF_PAUSED, _SLEEP_FUNC
  _WAIT_IF_PAUSED = wait_if_paused
  _SLEEP_FUNC = sleep_func


def _pause_barrier():
  """Block while paused and return the real time spent blocked."""
  if _WAIT_IF_PAUSED is None:
    return 0.0
  started = time.monotonic()
  _WAIT_IF_PAUSED()
  return max(0.0, time.monotonic() - started)


def _sleep(seconds):
  """Pause-aware sleep. Returns extra real time caused by a pause."""
  seconds = max(0.0, float(seconds))
  if _SLEEP_FUNC is None:
    time.sleep(seconds)
    return 0.0
  started = time.monotonic()
  _SLEEP_FUNC(seconds)
  elapsed = max(0.0, time.monotonic() - started)
  return max(0.0, elapsed - seconds)


def human_click(
    target_x, target_y, offset_x=8, offset_y=8, speed_factor=1.0
):
  """Płynny klik, który nigdy nie kończy starej akcji po pauzie/wznowieniu."""
  # Jeśli wywołanie weszło tutaj już podczas pauzy, po wznowieniu odrzucamy
  # stary punkt zamiast klikać pozycję policzoną z nieaktualnej klatki.
  if _pause_barrier() >= 0.02:
    return False

  click_x = int(target_x) + random.randint(-offset_x, offset_x)
  click_y = int(target_y) + random.randint(-offset_y, offset_y)

  current_x, current_y = pyautogui.position()
  distance = math.hypot(click_x - current_x, click_y - current_y)

  base_duration = max(0.15, (distance / 1200.0) * speed_factor)
  duration = random.gauss(base_duration, base_duration * 0.2)
  duration = max(0.1, min(duration, 0.8))

  tweens = [
      pyautogui.easeOutQuad,
      pyautogui.easeInOutQuad,
      pyautogui.easeInOutCubic,
  ]
  chosen_tween = random.choice(tweens)

  pyautogui.moveTo(click_x, click_y, duration=duration, tween=chosen_tween)

  # Pauza naciśnięta podczas ruchu myszy = NIE klikamy po wznowieniu.
  if _pause_barrier() >= 0.02:
    return False
  if _sleep(random.uniform(0.04, 0.12)) >= 0.02:
    return False
  if _pause_barrier() >= 0.02:
    return False

  # Sam down/up traktujemy atomowo. Nie wolno zamrozić procesu z wciśniętym
  # przyciskiem myszy; pauza zacznie obowiązywać natychmiast po mouseUp.
  pyautogui.mouseDown()
  try:
    time.sleep(random.uniform(0.04, 0.12))
  finally:
    pyautogui.mouseUp()

  _pause_barrier()
  return True


def _safeClick(x, y):
  """Przekierowuje każde kliknięcie w bocie na płynny ruch ludzkiej myszy."""
  return human_click(x, y)


def clickWrap(filename, wait=60, confidence=0.8):
  if errorhandling.gameReset() == 'skip':
    print(f'skip clickWrap for {filename}')
    return

  current = 0
  print(f'waiting for {filename} to apepar...')
  while current < wait:
    # Czas pauzy nie zużywa kolejnej sekundy oczekiwania.
    _sleep(1)
    _pause_barrier()
    errorhandling.connectionError()
    errorhandling.logedInOnAnotherDevice()

    _pause_barrier()
    result = pyautogui.locateOnScreen(
        f'./bilder/{filename}.PNG', grayscale=True, confidence=confidence
    )
    if result:
      # Jeśli pauza weszła po locate, wynik jest już potencjalnie stary.
      if _pause_barrier() >= 0.02:
        continue
      x, y = pyautogui.center(result)
      if not _safeClick(x, y):
        # Najczęstszy powód: pauza w trakcie ruchu myszy. Następna iteracja
        # wykona świeże locate zamiast kończyć stary klik.
        continue
      print(f'clicked on {filename}. Next operation starts in 2s.')
      _sleep(2)
      return result
    else:
      current += 1
    if errorhandling.gameReset() == 'skip':
      print(f'skip clickWrap for {filename}')
      return
  print(f'Could not find-{filename}')
  errorhandling.errorManager.error_detected = True


def clickWrapWithSkip(filename, searchTime=3, confidence=0.8) -> bool:
  _pause_barrier()
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG',
      grayscale=True,
      confidence=confidence,
      minSearchTime=searchTime,
  )
  if result:
    # Nie klikaj wyniku wyszukiwania, jeśli w międzyczasie była pauza.
    if _pause_barrier() >= 0.02:
      return False
    x, y, w, h = result
    if _safeClick(x + w / 2, y + h / 2):
      print(f'clicked on {filename}')
      return True
  return False


def clickToTheRightWrapWithSkip(filename, searchTime=3, confidence=0.8) -> bool:
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG',
      grayscale=True,
      confidence=confidence,
      minSearchTime=searchTime,
  )
  if result:
    x, y, w, h = result
    _safeClick(x + w + 50, y + h / 2)
    return True
  return False


def waitWrap(waitFile, clickFile, wait=60):
  result = pyautogui.locateOnScreen(
      f'./bilder/{waitFile}.PNG',
      grayscale=True,
      confidence=0.8,
      minSearchTime=wait,
  )
  if result:
    clickWrap(clickFile)
  else:
    errorhandling.errorManager.error_detected = True


def dragDungeon():
  result = errorhandling.gameReset()
  if result == 'skip':
    print('skip clickWrap for ...')
    return
  print('dragDungeon. Waiting for Arcane keep to appear')
  result = pyautogui.locateOnScreen(
      './bilder/arcane_keep.PNG', grayscale=True, confidence=0.8, minSearchTime=200
  )
  if result:
    pyautogui.mouseDown(result)
    x, y, w, h = result
    pyautogui.moveTo(x - 500, y, 1)
    pyautogui.mouseUp()
    time.sleep(1)
    ice_golem = pyautogui.locateOnScreen(
        './bilder/ice_golem_drag.PNG', grayscale=True, confidence=0.8
    )
    x, y, w, h = ice_golem
    pyautogui.mouseDown(ice_golem)
    pyautogui.moveTo(x - 640, y, 1)
    pyautogui.mouseUp()
    return
  else:
    errorhandling.errorManager.error_detected = True


def dragDungeonMore():
  result = errorhandling.gameReset()
  if result == 'skip':
    print('skip clickWrap for ...')
    return
  print('dragDungeonMore. Waiting for Dragon to appear')
  result = pyautogui.locateOnScreen(
      './bilder/drag_more_dragon.PNG',
      grayscale=True,
      confidence=0.8,
      minSearchTime=200,
  )
  if result:
    pyautogui.mouseDown(result)
    x, y, w, h = result
    pyautogui.moveTo(x - 500, y, 1)
    pyautogui.mouseUp()
    return
  else:
    errorhandling.errorManager.error_detected = True


def dragCampain():
  result = errorhandling.gameReset()
  if result == 'skip':
    print('skip clickWrap for ...')
    return
  print('dragCampain. Waiting for Sewers of Arnoc to appear')
  result = pyautogui.locateOnScreen(
      './bilder/sewers_of_arnoc.PNG',
      grayscale=True,
      confidence=0.8,
      minSearchTime=200,
  )
  if result:
    pyautogui.mouseDown(result)
    x, y, w, h = result
    pyautogui.moveTo(x - 500, y, 1)
    pyautogui.mouseUp()
    ice_golem = pyautogui.locateOnScreen(
        './bilder/ice_golem_drag.PNG', grayscale=True, confidence=0.8
    )
    x, y, w, h = ice_golem
    pyautogui.mouseDown(ice_golem)
    pyautogui.moveTo(x - 640, y, 1)
    pyautogui.mouseUp()
  else:
    errorhandling.errorManager.error_detected = True


def dragDoomtower():
  result = errorhandling.gameReset()
  if result == 'skip':
    print('skip clickWrap for ...')
    return
  print('dragDoomtower. Waiting for Doom tower to appear')
  result = pyautogui.locateOnScreen(
      './bilder/drag_doomtower.PNG',
      grayscale=True,
      confidence=0.8,
      minSearchTime=200,
  )
  if result:
    pyautogui.mouseDown(result)
    x, y, w, h = result
    pyautogui.moveTo(x - 300, y, 1)
    pyautogui.mouseUp()
  else:
    errorhandling.errorManager.error_detected = True


def clickBelow(filename, extra_distance=0):
  result = errorhandling.gameReset()
  if result == 'skip':
    print(f'skip clickWrap for {filename}')
    return
  print(f'clickBelow. waiting for {filename} to apepar...')
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG', grayscale=True, confidence=0.8, minSearchTime=1
  )
  if result:
    x, y, w, h = result
    x2 = x + w / 2
    y2 = y + 53 + extra_distance
    _safeClick(x2, y2)
    return
  else:
    errorhandling.errorManager.error_detected = True


def clickToTheRight(filename, conf=0.8):
  if errorhandling.gameReset() == 'skip':
    print(f'skip clickWrap for {filename}')
    return
  print(f'clickToTheRight. Waiting for {filename} to appear...')
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG',
      grayscale=True,
      confidence=conf,
      minSearchTime=200,
  )
  if result:
    x, y, w, h = result
    _safeClick(x + w + 50, y + h / 2)
  else:
        errorhandling.errorManager.error_detected = True


def clickToTheLeft(filename, conf=0.8):
  result = errorhandling.gameReset()
  if result == 'skip':
    print(f'skip clickWrap for {filename}')
    return
  print(f'clickToTheLeft. Waiting for {filename} to appear...')
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG',
      grayscale=True,
      confidence=conf,
      minSearchTime=200,
  )
  if result:
    x, y, w, h = result
    _safeClick(x - 20, y + h / 2)
  else:
    errorhandling.errorManager.error_detected = True


def clickAboveAndTotheright(filename, x_correction=555, y_correction=110):
  result = errorhandling.gameReset()
  if result == 'skip':
    print(f'skip clickWrap for {filename}')
    return
  print(f'clickAboveAndTotheright. Waiting for {filename} to appear...')
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG',
      grayscale=False,
      confidence=0.8,
      minSearchTime=200,
  )
  if result:
    x, y, w, h = result
    x2 = x + w / 2 + x_correction
    y2 = y - y_correction
    _safeClick(x2, y2)
  else:
    errorhandling.errorManager.error_detected = True


def checkExist(filename, wait=60):
  result = errorhandling.gameReset()
  if result == 'skip':
    print(f'skip clickWrap for {filename}')
    return
  current = 0
  while current < wait:
    _sleep(1)
    _pause_barrier()
    result = pyautogui.locateOnScreen(
        f'./bilder/{filename}.PNG', grayscale=True, confidence=0.8
    )
    if result:
      print(filename, ' exist')
      return result
    else:
      print(f'can not see {filename}, re-check in 1 second.')
      current += 1
  print(f'Could not find-{filename}')


def isEnergyFull():
  result = errorhandling.gameReset()
  if result == 'skip':
    return
  result = pyautogui.locateOnScreen(
      './bilder/fullenergy.PNG', grayscale=False, confidence=0.8
  )
  if result:
    print('Energy is full')
    return True
  print('Energy is not full')
  return False


def readyToRun(what_to_run, whe_to_start=4):
  result = errorhandling.gameReset()
  if result == 'skip':
    print(f'skip clickWrap for {what_to_run}')
    return False

  time_now = datetime.datetime.now().replace(microsecond=0)
  time_to_run = time_now.replace(hour=whe_to_start, minute=0, second=0)

  dailyes_from_file = json.load(open(f'./textfiles/{what_to_run}.txt'))
  print(datetime.datetime.fromisoformat(dailyes_from_file['date']).date())

  if (
      datetime.datetime.fromisoformat(dailyes_from_file['date']).date()
      == time_now.date()
  ):
    print(f'{what_to_run} - allready done today')
    return False

  if (
      datetime.datetime.fromisoformat(dailyes_from_file['date']).date()
      != time_now.date()
      and time_now > time_to_run
  ):
    print(f'Starting {what_to_run}')
    saveRun(what_to_run)
    return True
  else:
    print('Too early to run')
    return False


def didRunToday(filename):
  time_now = datetime.datetime.now().replace(microsecond=0)
  dailyes_from_file = json.load(open(f'./textfiles/{filename}.txt'))
  if (
      datetime.datetime.fromisoformat(dailyes_from_file['date']).date()
      == time_now.date()
  ):
    print(f'{filename} - allready done today')
    return True


def readyToRun_NoSave(filename, whe_to_start=4):
  time_now = datetime.datetime.now().replace(microsecond=0)
  time_to_run = time_now.replace(hour=whe_to_start, minute=0, second=0)

  dailyes_from_file = json.load(open(f'./textfiles/{filename}.txt'))

  if (
      datetime.datetime.fromisoformat(dailyes_from_file['date']).date()
      == time_now.date()
  ):
    print(f'{filename} - allready done today')
    return False
  elif time_now > time_to_run:
    print('time to run')
    return True
  else:
    print('not ready to run yet, try later')
    return False


def saveRun(filename):
  time_now = datetime.datetime.now().replace(microsecond=0)
  with open(f'./textfiles/{filename}.txt', 'w') as file:
    file.write(json.dumps({'date': time_now.isoformat()}))


def grabAndDrag(filename):
  result = errorhandling.gameReset()
  if result == 'skip':
    print(f'skip clickWrap for {filename}')
    return
  result = pyautogui.locateOnScreen(
      f'./bilder/{filename}.PNG',
      grayscale=True,
      confidence=0.8,
      minSearchTime=200,
  )
  pyautogui.mouseDown(result)
  x, y, w, h = result
  pyautogui.moveTo(x - 600, y, 1)
  pyautogui.mouseUp()


def pauseScriptUntilPressP():
  while True:
    key = input("Press 'p' to continue: ").strip().lower()
    if key == 'p':
      break


def cvcIncoming(skipUntilEnd: bool) -> bool:
  cvc_ref_date: str = '2026-02-10'

  ref_date = datetime.datetime.fromisoformat(cvc_ref_date).date()
  today = datetime.date.today()
  delta_days = (today - ref_date).days

  if (
      skipUntilEnd
      and (delta_days - 2) % 28 == 14
      and datetime.datetime.now().time() < datetime.time(11, 0)
  ):
    print('Skip everything until cvc is over')
    flagInstance.no_cvc = False
    return True

  if (
      delta_days >= 0
      and delta_days % 14 == 0
      and datetime.datetime.now().time() < datetime.time(11, 0)
  ):
    print('cvc is today')
    flagInstance.no_cvc = False
    return True

  tomorrow = today + datetime.timedelta(days=1)
  delta_day_tomorrow = (tomorrow - ref_date).days
  if (
      delta_day_tomorrow >= 0
      and delta_day_tomorrow % 14 == 0
      and datetime.datetime.now().time() > datetime.time(16, 0)
  ):
    print('cvc is tomorrow')
    flagInstance.no_cvc = False
    return True

  flagInstance.no_cvc = True
  return False


if __name__ == '__main__':
  print('cvcIncming ', cvcIncoming())