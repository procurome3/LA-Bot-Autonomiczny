import ctypes
from ctypes import wintypes
import base64
import os
import time
from pathlib import Path

from livearena_windows import enable_dpi_awareness
enable_dpi_awareness()

import pyautogui
import cv2
import numpy as np

try:
    import mss
except ImportError:
    mss = None


# ============================================================
# ADS V13 — X z nagrania + obsługa opóźnionego łańcucha popupów.
# ============================================================
MAX_OFFERS = 6

# Gdy Bastion nie jest jeszcze gotowy, dajemy grze tylko krótkie okno.
# Na czystym Bastionie funkcja kończy się od razu.
INITIAL_WAIT_TIMEOUT = 1.25
POST_CLICK_TIMEOUT = 1.25
MAX_UNCHANGED_RETRIES = 1

# V13: po zamknięciu prawdziwego popupu RAID potrafi na ~0.5-0.7 s
# pokazać czysty Bastion, a dopiero potem wyrenderować kolejny popup.
# To okno działa TYLKO po realnym kliknięciu reklamy, więc szybka ścieżka
# 'brak reklamy' nadal kończy się natychmiast.
POST_CLOSE_CHAIN_TIMEOUT = 0.90
POST_CLOSE_CHAIN_POLL = 0.05

BASTION_TEMPLATE = "./bilder/forge.PNG"

# Kompletny okrągły przycisk 47x47, wycięty z klatki nagrania użytkownika.
# Środek wzorca jest środkiem X. Stary PNG zawierał fragment innego UI nad X
# i kończył się w połowie przycisku. Nie używamy również czerwonego gema.
# Wzorzec jest w pliku .py — dodatkowy PNG nie jest potrzebny.
CLOSE_TEMPLATE_NAME = "embedded_offer_x_v12"
CLOSE_CONFIDENCE = 0.88
_CLOSE_PNG_BASE64 = (
    "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"
)
_MODULE_DIR = Path(__file__).resolve().parent
_TEMPLATE_CACHE = {}
_VARIANT_CACHE = {}
_SCREEN_CAPTURE = None

# ============================================================
# PAUSE BRIDGE
# ============================================================
# closeadds może działać samodzielnie, ale gdy Live Arena poda swoje hooki
# (_wait_if_paused / _pauseable_sleep), wszystkie pętle i kliknięcia stają się
# pause-aware. Czas spędzony na pauzie nie zużywa timeoutów tego modułu.
_WAIT_IF_PAUSED = None
_SLEEP_FUNC = None
_PAUSED_TOTAL = 0.0


def configure_pause(wait_if_paused=None, sleep_func=None):
    """Podłącz globalną pauzę Live Areny bez tworzenia drugiego hotkeya."""
    global _WAIT_IF_PAUSED, _SLEEP_FUNC, _PAUSED_TOTAL
    _WAIT_IF_PAUSED = wait_if_paused
    _SLEEP_FUNC = sleep_func
    _PAUSED_TOTAL = 0.0


def _pause_barrier():
    """Zatrzymaj akcję na czas pauzy i zwróć realny czas blokady."""
    global _PAUSED_TOTAL
    if _WAIT_IF_PAUSED is None:
        return 0.0
    started = time.monotonic()
    _WAIT_IF_PAUSED()
    waited = max(0.0, time.monotonic() - started)
    # Pomijamy mikro-opóźnienia zwykłego wywołania funkcji.
    if waited >= 0.02:
        _PAUSED_TOTAL += waited
    return waited


def _clock():
    """Monotoniczny zegar aktywnej pracy; pauza nie zużywa timeoutów."""
    return time.monotonic() - _PAUSED_TOTAL


def _sleep(seconds):
    """Sleep reagujący na pauzę; zgodny także z uruchomieniem standalone."""
    global _PAUSED_TOTAL
    seconds = max(0.0, float(seconds))
    _pause_barrier()

    if _SLEEP_FUNC is not None:
        started = time.monotonic()
        _SLEEP_FUNC(seconds)
        elapsed = max(0.0, time.monotonic() - started)
        # _pauseable_sleep z arenalive blokuje się na pauzie; odejmujemy tylko
        # wyraźny nadmiar, a nie normalny jitter scheduler-a.
        extra = max(0.0, elapsed - seconds)
        if extra >= 0.03:
            _PAUSED_TOTAL += extra
        return

    if _WAIT_IF_PAUSED is None:
        time.sleep(seconds)
        return

    end = _clock() + seconds
    while _clock() < end:
        _pause_barrier()
        remaining = end - _clock()
        if remaining <= 0:
            break
        time.sleep(min(0.02, remaining))


def _find_raid_client_rect():
    """Client-area RAID; nie obejmuje paska Windows z przyciskiem zamknięcia."""
    user32 = ctypes.windll.user32
    matches = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip().lower()

        if title not in {
            "raid: shadow legends",
            "raid shadow legends",
        }:
            return True

        rect = wintypes.RECT()
        point = wintypes.POINT(0, 0)

        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            return True

        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width >= 500 and height >= 350:
            matches.append((point.x, point.y, width, height))

        return True

    user32.EnumWindows(enum_proc, 0)

    if not matches:
        return None

    return max(matches, key=lambda r: r[2] * r[3])


def _capture_frame(region):
    """Jedna klatka BGR z RAID; brak okna nigdy nie oznacza całego pulpitu."""
    global _SCREEN_CAPTURE
    if region is None:
        return None
    x, y, width, height = map(int, region)
    if width <= 0 or height <= 0:
        return None
    if mss is not None:
        try:
            if _SCREEN_CAPTURE is None:
                _SCREEN_CAPTURE = mss.mss()
            raw = _SCREEN_CAPTURE.grab({"left": x, "top": y, "width": width, "height": height})
            return np.asarray(raw)[:, :, :3].copy()
        except Exception:
            pass
    try:
        return cv2.cvtColor(np.asarray(pyautogui.screenshot(region=region)), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _load_template(path):
    if path == CLOSE_TEMPLATE_NAME:
        if path not in _TEMPLATE_CACHE:
            raw = np.frombuffer(base64.b64decode(_CLOSE_PNG_BASE64), dtype=np.uint8)
            _TEMPLATE_CACHE[path] = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        return _TEMPLATE_CACHE[path]

    # Ścieżka obok modułu działa także po uruchomieniu z innego katalogu.
    asset = Path(path)
    if not asset.is_absolute():
        asset = _MODULE_DIR / asset
    if not asset.is_file() and asset.parent.is_dir():
        asset = next((p for p in asset.parent.iterdir()
                      if p.name.lower() == asset.name.lower()), asset)
    if not asset.is_file():
        return None
    try:
        key = (str(asset), asset.stat().st_mtime_ns)
        if key not in _TEMPLATE_CACHE:
            _TEMPLATE_CACHE[key] = cv2.imdecode(np.fromfile(str(asset), dtype=np.uint8), cv2.IMREAD_COLOR)
        return _TEMPLATE_CACHE[key]
    except (OSError, cv2.error):
        return None


def _match_frame(frame, path, region, confidence=0.90, grayscale=False, popup=False):
    """OpenCV dopasowuje wszystkie skale do TEJ SAMEJ klatki."""
    if frame is None or not frame.size or region is None:
        return None
    template = _load_template(path)
    if template is None:
        return None
    sx, sy = region[2] / 1024.0, region[3] / 768.0
    scale = min(sx, sy)
    if abs(scale - 1.0) < 0.01:
        scale = 1.0
    factors = (1.0, 0.94, 1.06, 0.88, 1.12) if popup else (1.0,)

    # Prawy górny obszar klienta zawiera X ofert; pomijamy dolny pasek
    # Bastionu i lewą część ekranu. Pasek tytułu Windows jest poza klatką.
    ox, oy = (int(frame.shape[1] * 0.50), int(frame.shape[0] * 0.02)) if popup else (0, 0)
    bottom = int(frame.shape[0] * 0.65) if popup else frame.shape[0]
    search = frame[oy:bottom, ox:]
    if grayscale:
        search = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)

    best_score, best_box = -1.0, None
    for factor in factors:
        width = max(4, round(template.shape[1] * scale * factor))
        height = max(4, round(template.shape[0] * scale * factor))
        if width > search.shape[1] or height > search.shape[0]:
            continue
        key = (id(template), width, height, bool(grayscale))
        if key not in _VARIANT_CACHE:
            resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA
                                 if width < template.shape[1] else cv2.INTER_CUBIC)
            _VARIANT_CACHE[key] = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if grayscale else resized
        response = cv2.matchTemplate(search, _VARIANT_CACHE[key], cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(response)
        if np.isfinite(score) and score > best_score:
            best_score = float(score)
            best_box = (region[0] + ox + point[0], region[1] + oy + point[1], width, height)
        if best_score >= 0.985:
            break
    return best_box if best_score >= confidence else None


def _locate(path, confidence=0.90, grayscale=False, region=None, frame=None):
    if region is None:
        return None
    if frame is None:
        frame = _capture_frame(region)
    return _match_frame(frame, path, region, confidence, grayscale)


def _center(box):
    if not box:
        return None

    try:
        p = pyautogui.center(box)
        return int(p.x), int(p.y)
    except Exception:
        return None


def _same_place(first, second, tolerance=10):
    a = _center(first)
    b = _center(second)

    if a is None or b is None:
        return False

    return (
        abs(a[0] - b[0]) <= tolerance
        and abs(a[1] - b[1]) <= tolerance
    )


def _bastion_visible(region, frame=None):
    return bool(
        _locate(
            BASTION_TEMPLATE,
            confidence=0.90,
            grayscale=False,
            region=region,
            frame=frame,
        )
    )


def _find_close_once(region, frame=None):
    if frame is None:
        frame = _capture_frame(region)
    result = _match_frame(frame, CLOSE_TEMPLATE_NAME, region,
                          confidence=CLOSE_CONFIDENCE, popup=True)
    return (result, CLOSE_TEMPLATE_NAME) if result else (None, None)


def _stable_close_button(region):
    """
    Dwa zgodne odczyty tylko wtedy, gdy pierwszy odczyt faktycznie znalazł X.
    Na czystym Bastionie kosztuje to tylko jeden search.
    """
    _pause_barrier()
    first, path1 = _find_close_once(region)

    if not first:
        return None, None

    _sleep(0.05)

    if _find_raid_client_rect() != region:
        return None, None

    second, path2 = _find_close_once(region)

    if not second:
        return None, None

    if not _same_place(first, second, tolerance=10):
        return None, None

    return second, path2 or path1


def _human_click(box, region=None):
    # Jeżeli użytkownik wstrzymał bota przed kliknięciem, po wznowieniu nie
    # ufamy staremu boxowi bez ponownej walidacji.
    _pause_barrier()
    point = _center(box)
    if point is None:
        return False

    x, y = point

    if region is None or _find_raid_client_rect() != region:
        return False
    left, top, width, height = region
    if not (left + 2 <= x < left + width - 2 and top + 2 <= y < top + height - 2):
        return False

    # Krótka ochrona przed ręcznym ruchem myszy, ale bez zbędnego czekania.
    last = pyautogui.position()
    stable_since = _clock()
    deadline = _clock() + 0.18

    while _clock() < deadline:
        current = pyautogui.position()

        if abs(current.x - last.x) > 2 or abs(current.y - last.y) > 2:
            stable_since = _clock()
            last = current
        elif _clock() - stable_since >= 0.05:
            break

        _sleep(0.01)

    if _clock() - stable_since < 0.05:
        return False

    # Po oczekiwaniu potwierdzamy X i geometrię jeszcze raz. Sam dawny
    # wynik locate nie uprawnia do kliknięcia po zamknięciu/przesunięciu okna.
    if _find_raid_client_rect() != region:
        return False
    fresh, _ = _find_close_once(region)
    if not fresh or not _same_place(box, fresh, tolerance=6):
        return False
    x, y = _center(fresh)
    pyautogui.moveTo(
        x,
        y,
        duration=0.10,
        tween=pyautogui.easeInOutQuad,
    )
    # Pauza może zostać włączona także podczas ruchu kursora. Nigdy nie klikamy
    # od razu po wznowieniu na podstawie starej klatki.
    _pause_barrier()
    if _find_raid_client_rect() != region:
        return False
    fresh, _ = _find_close_once(region)
    fresh_point = _center(fresh)
    if fresh_point is None or abs(fresh_point[0] - x) > 8 or abs(fresh_point[1] - y) > 8:
        return False
    x, y = fresh_point
    pyautogui.click(x=x, y=y)
    return True


def attention(region=None, timeout=0.45):
    """
    Attention sprawdzamy tylko PO realnym kliknięciu reklamy.
    Nie bierze udziału w szybkim przebiegu "brak reklamy".
    """
    if region is None:
        region = _find_raid_client_rect()
    if region is None:
        return False
    end = _clock() + timeout

    while _clock() < end:
        _pause_barrier()
        result = _locate(
            "./bilder/attention.PNG",
            confidence=0.88,
            grayscale=True,
            region=region,
        )

        if result:
            close_box = _locate("./bilder/close.PNG", confidence=0.88, region=region)
            point = _center(close_box)
            if point and _find_raid_client_rect() == region:
                _pause_barrier()
                close_box = _locate("./bilder/close.PNG", confidence=0.88, region=region)
                point = _center(close_box)
                if point:
                    x, y = point
                    if region[0] <= x < region[0] + region[2] and region[1] <= y < region[1] + region[3]:
                        pyautogui.click(x=x, y=y)
                        print("closeAdds: closing attention")
                        return True
            return False

        _sleep(0.05)

    return False


def _offer_content_changed(previous, current, close_box, region):
    """Kolejna oferta może mieć X dokładnie w tym samym miejscu."""
    if previous is None or current is None or previous.shape != current.shape:
        return False
    point = _center(close_box)
    if point is None:
        return False
    height, width = current.shape[:2]
    x1, x2 = round(width * 0.06), min(width, point[0] - region[0] - round(width * 0.04))
    y1, y2 = max(0, point[1] - region[1] + round(height * 0.10)), round(height * 0.86)
    if x2 <= x1 or y2 <= y1:
        return False
    a = cv2.resize(previous[y1:y2, x1:x2], (48, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(current[y1:y2, x1:x2], (48, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    delta = np.mean(np.abs(a - b), axis=2)
    # Drobna animacja, licznik lub kursor nie wystarczają.
    return float(np.mean(delta)) >= 20.0 and float(np.mean(delta >= 30.0)) >= 0.35


def _wait_after_click(previous_close, region, timeout=POST_CLICK_TIMEOUT, previous_frame=None):
    """
    Po realnym kliknięciu:
    - nowy X w innym miejscu -> następna reklama,
    - Forge/Bastion -> koniec,
    - brak X -> popup zniknął.
    """
    started = _clock()
    end = started + timeout

    while _clock() < end:
        _pause_barrier()
        if _find_raid_client_rect() != region:
            return "window_changed", None, None
        frame = _capture_frame(region)
        current, path = _find_close_once(region, frame=frame)

        if current:
            if not _same_place(previous_close, current, tolerance=12):
                return "next_offer", current, path
            if (_clock() - started >= 0.18
                    and _offer_content_changed(previous_frame, frame, current, region)):
                return "next_offer", current, path

            # Ten sam X może jeszcze znikać podczas animacji.
            _sleep(0.06)
            continue

        if _bastion_visible(region, frame=frame):
            return "bastion", None, None

        # Nie ma już X. Daj UI jedną krótką chwilę na następną reklamę.
        _sleep(0.08)

        current, path = _find_close_once(region)
        if current:
            return "next_offer", current, path

        return "closed", None, None

    return "timeout", None, None


def _wait_for_chained_offer(region, timeout=POST_CLOSE_CHAIN_TIMEOUT):
    """
    V13: łapie popup, który pojawia się chwilę PO przejściowym Bastionie.

    Z nagrania 2026-09-30: pierwszy popup znika, Bastion jest widoczny przez
    około 0.6 s, a następna oferta pojawia się dopiero potem. V12 kończył
    pracę na pierwszej klatce Bastionu i zostawiał drugi popup otwarty.

    Nie klikamy tutaj niczego. Zwracamy wyłącznie świeżo wykryty X; właściwe
    kliknięcie nadal przechodzi przez _human_click(), który ponownie sprawdza
    pozycję X i geometrię okna.
    """
    end = _clock() + max(0.0, timeout)

    while _clock() < end:
        _pause_barrier()
        if _find_raid_client_rect() != region:
            return "window_changed", None, None

        frame = _capture_frame(region)
        current, path = _find_close_once(region, frame=frame)
        if current:
            return "next_offer", current, path

        _sleep(POST_CLOSE_CHAIN_POLL)

    return "clean", None, None


def closeAdds(wait_if_paused=None, sleep_func=None):
    # Backward-compatible: stare wywołanie closeAdds() nadal działa.
    # Arenalive powinien przekazać swoje hooki, aby pauza obejmowała reklamy.
    if wait_if_paused is not None or sleep_func is not None:
        configure_pause(wait_if_paused, sleep_func)
    _pause_barrier()
    started = _clock()
    print("closeAdds V13: verified popup X + delayed-chain guard.")

    region = _find_raid_client_rect()
    if region is None:
        print("closeAdds: RAID window not found -> no click.")
        return

    # --------------------------------------------------------
    # FAST PATH:
    # najpierw prawdziwy X. Jeżeli go nie ma i widać Forge,
    # kończymy NATYCHMIAST. Nie czekamy 7 s i nie używamy gem fallbacku.
    # --------------------------------------------------------
    candidate, candidate_template = _stable_close_button(region)

    if not candidate and _bastion_visible(region):
        print(
            "closeAdds: clean Bastion -> no ad "
            f"({_clock() - started:.2f}s)."
        )
        return

    # Jeśli ekran dopiero się ładuje, krótko czekamy na X albo Bastion.
    if not candidate:
        end = started + INITIAL_WAIT_TIMEOUT

        while _clock() < end:
            current_region = _find_raid_client_rect()
            if current_region is None:
                return
            region = current_region
            candidate, candidate_template = _stable_close_button(region)

            if candidate:
                break

            if _bastion_visible(region):
                print(
                    "closeAdds: clean Bastion -> no ad "
                    f"({_clock() - started:.2f}s)."
                )
                return

            _sleep(0.06)

    if not candidate:
        print(
            "closeAdds: no real popup X detected -> continue "
            f"({_clock() - started:.2f}s)."
        )
        return

    # --------------------------------------------------------
    # REAL POPUP PATH
    # --------------------------------------------------------
    unchanged_retries = 0
    for attempt in range(MAX_OFFERS):
        current_region = _find_raid_client_rect()
        if current_region is None:
            return
        if current_region != region:
            region = current_region
            candidate, candidate_template = _stable_close_button(region)
        close_btn = candidate
        close_template = candidate_template
        candidate = None
        candidate_template = None

        if not close_btn:
            close_btn, close_template = _stable_close_button(region)

        if not close_btn:
            print(
                "closeAdds: popup X disappeared -> finished "
                f"({_clock() - started:.2f}s)."
            )
            return

        print(
            f"closeAdds: REAL offer detected -> closing "
            f"({attempt + 1}/{MAX_OFFERS}) "
            f"[{os.path.basename(close_template)}]"
        )

        previous_frame = _capture_frame(region)
        if not _human_click(close_btn, region=region):
            print("closeAdds: could not click close button.")
            return

        attention(region=region, timeout=0.45)

        state, candidate, candidate_template = _wait_after_click(
            close_btn,
            region,
            timeout=POST_CLICK_TIMEOUT,
            previous_frame=previous_frame,
        )

        if state in {"bastion", "closed"}:
            # V13: Bastion/blank po kliknięciu nie oznacza jeszcze końca serii.
            # RAID może po ~0.6 s doładować kolejny popup. Czekamy krótko TYLKO
            # po realnym kliknięciu; no-ad fast path wyżej pozostaje bez zwłoki.
            chain_state, chain_candidate, chain_template = _wait_for_chained_offer(
                region,
                timeout=POST_CLOSE_CHAIN_TIMEOUT,
            )

            if chain_state == "next_offer":
                print(
                    "closeAdds: delayed chained offer detected -> continue "
                    f"({_clock() - started:.2f}s)."
                )
                candidate = chain_candidate
                candidate_template = chain_template
                unchanged_retries = 0
                continue

            if chain_state == "window_changed":
                region = _find_raid_client_rect()
                if region is None:
                    return
                candidate, candidate_template = _stable_close_button(region)
                continue

            if state == "bastion":
                print(
                    "closeAdds: Bastion stable; no chained popup "
                    f"({_clock() - started:.2f}s)."
                )
            else:
                print(
                    "closeAdds: popup closed; no chained popup "
                    f"({_clock() - started:.2f}s)."
                )
            return

        if state == "next_offer":
            unchanged_retries = 0
            continue

        if state == "window_changed":
            region = _find_raid_client_rect()
            if region is None:
                return
            continue

        # Timeout: jeszcze jedno bezpieczne sprawdzenie prawdziwego X.
        if unchanged_retries >= MAX_UNCHANGED_RETRIES:
            print("closeAdds: same popup still visible after retry -> stopping.")
            return
        unchanged_retries += 1
        candidate, candidate_template = _stable_close_button(region)

        if not candidate:
            print(
                "closeAdds: timeout without real X -> stop safely "
                f"({_clock() - started:.2f}s)."
            )
            return

    print(
        "closeAdds: MAX_OFFERS reached; stopping for safety "
        f"({_clock() - started:.2f}s)."
    )


if __name__ == "__main__":
    closeAdds()
