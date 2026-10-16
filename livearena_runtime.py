"""Runtime helpers: bezpieczny ludzki kursor + watchdog stanów."""
from __future__ import annotations

import os
import random
import time
import ctypes
from datetime import datetime

import cv2
import pyautogui


class HumanMouse:
    def __init__(self, edge_margin=2):
        self.edge_margin = edge_margin

    @staticmethod
    def _point(target):
        if target is None:
            return None
        try:
            p = pyautogui.center(target)
            return int(p.x), int(p.y)
        except Exception:
            pass
        try:
            return int(target[0]), int(target[1])
        except Exception:
            return None

    def inside(self, point, window_rect):
        if point is None or window_rect is None:
            return False
        x, y = point
        left, top, width, height = window_rect
        m = self.edge_margin
        return (
            left + m <= x < left + width - m
            and top + m <= y < top + height - m
        )

    @staticmethod
    def _mouse_button_down():
        """True gdy użytkownik fizycznie trzyma przycisk myszy."""
        try:
            user32 = ctypes.windll.user32
            # LMB, RMB, MMB, XBUTTON1, XBUTTON2
            for vk in (0x01, 0x02, 0x04, 0x05, 0x06):
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _distance(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def _wait_for_manual_mouse_idle(
        self,
        max_wait=0.35,
        idle_for=0.09,
        tolerance=2.0,
        wait_if_paused=None,
    ):
        """
        Krótko czeka, jeśli użytkownik akurat porusza myszką lub trzyma przycisk.
        Nie blokuje sterowania systemowego i nigdy nie czeka dłużej niż max_wait.
        """
        started = time.monotonic()
        last = pyautogui.position()
        stable_since = time.monotonic()

        while time.monotonic() - started < max_wait:
            if wait_if_paused is not None:
                wait_if_paused()

            current = pyautogui.position()
            moved = self._distance((current.x, current.y), (last.x, last.y)) > tolerance
            button_down = self._mouse_button_down()

            if moved or button_down:
                stable_since = time.monotonic()
                last = current
            elif time.monotonic() - stable_since >= idle_for:
                return True

            time.sleep(0.015)

        # Po limicie pozwalamy botowi spróbować, ale właściwy click-guard
        # nadal nie kliknie poza celem.
        return False

    def click(
        self,
        target,
        window_rect,
        min_duration=0.20,
        max_duration=0.55,
        wait_if_paused=None,
        post_pause=(0.005, 0.015),
        settle_tolerance=5.0,
        max_corrections=3,
    ):
        """
        Płynny ruch odporny na lekkie ruszanie myszką przez użytkownika.

        Najważniejsza różnica względem poprzedniej wersji:
        poprzednio bot docierał do celu, czekał 20-70 ms i wywoływał
        pyautogui.click() w AKTUALNEJ pozycji kursora. Wystarczył drobny ruch
        użytkownika w tym oknie czasowym, żeby klik trafił obok.

        Teraz bot:
          1) krótko czeka na uspokojenie ręcznego ruchu,
          2) wykonuje płynny ruch,
          3) tuż przed kliknięciem sprawdza odchylenie kursora,
          4) koryguje pozycję maksymalnie kilka razy,
          5) klika dokładnie w zaplanowany punkt.
        """
        point = self._point(target)
        if point is None:
            return False

        if window_rect is not None and not self.inside(point, window_rect):
            print(f"CLICK GUARD: odrzucono punkt poza oknem RAID: {point}")
            return False

        if wait_if_paused is not None:
            wait_if_paused()

        # Jeśli użytkownik właśnie rusza myszką, dajemy mu krótkie okno na puszczenie.
        mouse_idle = self._wait_for_manual_mouse_idle(
            max_wait=0.35,
            idle_for=0.09,
            tolerance=2.0,
            wait_if_paused=wait_if_paused,
        )
        if not mouse_idle:
            print("MOUSE GUARD: użytkownik nadal porusza myszką -> bot oddaje sterowanie i ponowi akcję.")
            return False

        x, y = point
        start = pyautogui.position()
        start_x, start_y = int(start.x), int(start.y)
        total_duration = random.uniform(min_duration, max_duration)

        dx = x - start_x
        dy = y - start_y
        distance = max(1.0, (dx * dx + dy * dy) ** 0.5)
        curve = min(10, max(2, int(distance * 0.025)))

        mid_x = start_x + dx * random.uniform(0.45, 0.62) + random.randint(-curve, curve)
        mid_y = start_y + dy * random.uniform(0.45, 0.62) + random.randint(-curve, curve)

        pyautogui.moveTo(
            mid_x,
            mid_y,
            duration=max(0.035, total_duration * 0.45),
            tween=pyautogui.easeOutQuad,
        )
        pyautogui.moveTo(
            x,
            y,
            duration=max(0.045, total_duration * 0.55),
            tween=pyautogui.easeInOutQuad,
        )

        if wait_if_paused is not None:
            wait_if_paused()

        time.sleep(random.uniform(*post_pause))

        # Użytkownik mógł lekko ruszyć kursorem dokładnie podczas ruchu bota.
        # Nie klikamy wtedy w złym miejscu — najpierw korygujemy.
        corrected = False
        for attempt in range(max_corrections + 1):
            current = pyautogui.position()
            current_point = (int(current.x), int(current.y))
            if self._distance(current_point, (x, y)) <= settle_tolerance:
                break

            corrected = True
            if attempt >= max_corrections:
                print(
                    f"MOUSE GUARD: kursora nie udało się ustabilizować przy {point}; "
                    "klik anulowany."
                )
                return False

            # Krótka korekta, a nie teleport przez całą drogę.
            pyautogui.moveTo(
                x,
                y,
                duration=random.uniform(0.035, 0.075),
                tween=pyautogui.easeOutQuad,
            )
            time.sleep(0.005)

        if corrected:
            print("MOUSE GUARD: wykryto ręczny ruch kursora -> pozycja skorygowana.")

        if self._mouse_button_down():
            # Użytkownik akurat trzyma przycisk; nie dokładamy własnego kliknięcia.
            print("MOUSE GUARD: przycisk myszy jest wciśnięty -> klik odłożony.")
            return False

        # Finalny guard: klikamy w konkretny punkt, nie w przypadkową aktualną pozycję.
        # Ruch do celu jest już wykonany płynnie; to tylko zabezpieczenie współrzędnych.
        pyautogui.click(x=x, y=y)
        return True


class StateWatchdog:
    def __init__(self, thresholds, debug_dir="./debug"):
        self.thresholds = dict(thresholds)
        self.debug_dir = debug_dir
        self.state = None
        self.activity_key = None
        self.changed_at = time.monotonic()
        self.alerted = False

    def reset(self, state=None, activity_key=None):
        self.state = state
        self.activity_key = activity_key
        self.changed_at = time.monotonic()
        self.alerted = False

    def observe(self, state, activity_key, frame_bgr=None):
        now = time.monotonic()

        if state != self.state or activity_key != self.activity_key:
            self.state = state
            self.activity_key = activity_key
            self.changed_at = now
            self.alerted = False
            return False

        timeout = self.thresholds.get(state)
        if not timeout or self.alerted or now - self.changed_at < timeout:
            return False

        self.alerted = True
        elapsed = now - self.changed_at
        print(f"WATCHDOG: {state} bez postępu przez {elapsed:.1f}s.")

        if frame_bgr is not None:
            try:
                os.makedirs(self.debug_dir, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                path = os.path.join(self.debug_dir, f"watchdog_{state}_{stamp}.png")
                cv2.imwrite(path, frame_bgr)
                print(f"WATCHDOG screenshot: {path}")
            except Exception:
                pass

        return True
