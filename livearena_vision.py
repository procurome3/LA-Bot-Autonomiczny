"""Szybka warstwa vision dla Live Arena.

- MSS jako szybki backend screenshotów (fallback: pyautogui),
- preload/cache template'ów i ich skal,
- automatyczne ROI,
- lekkie statystyki wydajności.
"""
from __future__ import annotations

from collections import deque
import os
import time

import cv2
import numpy as np
import pyautogui

try:
    import mss
except Exception:
    mss = None


class VisionEngine:
    def __init__(
        self,
        reference_size=(1020, 793),
        roi_resolver=None,
        template_reference_size=(1024, 769),
    ):
        self.reference_size = reference_size
        self.roi_resolver = roi_resolver
        self.template_reference_size = template_reference_size
        self._images = {}
        self._variants = {}
        self._sct = None
        self._capture_ms = deque(maxlen=240)
        self._match_ms = deque(maxlen=1000)
        self._match_calls = 0
        self._last_perf_log = 0.0
        self._backend_announced = False

    @property
    def backend_name(self):
        return "mss" if mss is not None else "pyautogui"

    def _ensure_mss(self):
        if mss is None:
            return None
        if self._sct is None:
            self._sct = mss.mss()
        return self._sct

    def announce_backend(self):
        if self._backend_announced:
            return
        self._backend_announced = True
        if mss is None:
            print("VISION: mss nie jest zainstalowany -> fallback pyautogui screenshot.")
            print("VISION: zainstaluj 'mss', aby przyspieszyć przechwytywanie ekranu.")
        else:
            print("VISION: szybki backend screenshotów = mss")

    def capture(self, rect):
        """Zwraca BGR frame dla (left, top, width, height)."""
        if rect is None:
            return None

        left, top, width, height = map(int, rect)
        if width <= 0 or height <= 0:
            return None

        started = time.perf_counter()
        frame = None

        try:
            sct = self._ensure_mss()
            if sct is not None:
                raw = np.asarray(
                    sct.grab({
                        "left": left,
                        "top": top,
                        "width": width,
                        "height": height,
                    })
                )
                # MSS zwraca BGRA - OpenCV oczekuje BGR.
                frame = raw[:, :, :3].copy()
            else:
                shot = pyautogui.screenshot(region=(left, top, width, height))
                frame = cv2.cvtColor(np.asarray(shot), cv2.COLOR_RGB2BGR)
        except Exception:
            # Jeśli MSS chwilowo zawiedzie, nie zabijamy bota.
            try:
                shot = pyautogui.screenshot(region=(left, top, width, height))
                frame = cv2.cvtColor(np.asarray(shot), cv2.COLOR_RGB2BGR)
            except Exception:
                frame = None

        self._capture_ms.append((time.perf_counter() - started) * 1000.0)
        return frame

    def get_image(self, path):
        if not os.path.exists(path):
            return None

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None

        cached = self._images.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            return None

        self._images[path] = (mtime, image)
        # Zmiana pliku unieważnia wszystkie jego warianty.
        for key in [k for k in self._variants if k[0] == path]:
            self._variants.pop(key, None)
        return image

    def get_variants(self, path, scales, grayscale=False):
        image = self.get_image(path)
        if image is None:
            return []

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return []

        key = (path, tuple(scales), bool(grayscale))
        cached = self._variants.get(key)
        if cached and cached[0] == mtime:
            return cached[1]

        source = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if grayscale else image

        variants = []
        for scale in scales:
            # Round to the nearest pixel. At 1024x768 vs reference 1024x769,
            # scale is ~0.99935: int() shrank every icon/text by one pixel,
            # enough to reject the PICK phase and prevent clicking its filter.
            w = max(4, round(source.shape[1] * scale))
            h = max(4, round(source.shape[0] * scale))
            resized = cv2.resize(
                source,
                (w, h),
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
            )
            variants.append((scale, resized))

        self._variants[key] = (mtime, variants)
        return variants

    def preload(self, paths):
        """Wczytuje obrazy i najczęstsze skale przed pierwszą turą."""
        loaded = 0
        missing = []
        # Większość UI w RAID jest renderowana piksel-w-piksel przy tej
        # samej rozdzielczości. 5 skal dla KAŻDEGO matcha było kosztowne.
        common_scales = (1.00,)
        skill_scales = (1.00, 0.94, 1.06)
        stoneskin_scales = (
            0.30, 0.35, 0.40, 0.45, 0.50, 0.55,
            0.60, 0.65, 0.70, 0.75, 0.80, 0.90,
            1.00, 1.10, 1.20,
        )

        for path in sorted(set(paths)):
            if self.get_image(path) is None:
                missing.append(path)
                continue

            loaded += 1
            self.get_variants(path, common_scales, grayscale=False)
            self.get_variants(path, common_scales, grayscale=True)

            base = os.path.basename(path).lower()
            if base.startswith("skill_"):
                self.get_variants(path, skill_scales, grayscale=False)
            if base == "arena_live_stoneskin.png":
                self.get_variants(path, stoneskin_scales, grayscale=False)

        print(f"VISION PRELOAD: {loaded} template'ów w RAM; brakujących={len(missing)}")
        return loaded, missing

    def _roi_for_frame(self, frame_bgr, ref_roi):
        if frame_bgr is None or ref_roi is None:
            return frame_bgr, (0, 0)

        ref_w, ref_h = self.reference_size
        frame_h, frame_w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = ref_roi

        fx1 = max(0, min(frame_w, round(x1 * frame_w / ref_w)))
        fy1 = max(0, min(frame_h, round(y1 * frame_h / ref_h)))
        fx2 = max(fx1 + 1, min(frame_w, round(x2 * frame_w / ref_w)))
        fy2 = max(fy1 + 1, min(frame_h, round(y2 * frame_h / ref_h)))

        return frame_bgr[fy1:fy2, fx1:fx2], (fx1, fy1)

    def template_base_scale(self, frame_bgr):
        """Skala UI względem clienta, przy którym wycinano template PNG."""
        if frame_bgr is None:
            return 1.0

        frame_h, frame_w = frame_bgr.shape[:2]
        ref_w, ref_h = self.template_reference_size

        if ref_w <= 0 or ref_h <= 0:
            return 1.0

        sx = frame_w / float(ref_w)
        sy = frame_h / float(ref_h)

        # UI RAID skaluje się praktycznie równomiernie.
        # Średnia jest odporniejsza na różnicę kilku px od ramek.
        return max(0.35, min(2.50, (sx + sy) * 0.5))

    def adaptive_scales(self, frame_bgr, relative_scales):
        base = self.template_base_scale(frame_bgr)
        return tuple(
            max(0.10, min(3.00, base * float(scale)))
            for scale in relative_scales
        )

    def match(
        self,
        frame_bgr,
        template_path,
        confidence=0.80,
        grayscale=False,
        scales=(1.00,),
        roi=None,
        auto_roi=True,
    ):
        started = time.perf_counter()
        self._match_calls += 1

        result_empty = {
            "found": False,
            "score": 0.0,
            "box": None,
            "center": None,
            "scale": None,
        }

        if frame_bgr is None:
            return result_empty

        if roi is None and auto_roi and self.roi_resolver is not None:
            try:
                roi = self.roi_resolver(template_path)
            except Exception:
                roi = None

        effective_scales = self.adaptive_scales(frame_bgr, scales)

        search, (ox, oy) = self._roi_for_frame(frame_bgr, roi)
        if search is None or search.size == 0:
            return result_empty

        screen = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY) if grayscale else search

        best_score = 0.0
        best_box = None
        best_scale = None

        for scale, template in self.get_variants(
            template_path, effective_scales, grayscale=grayscale
        ):
            th, tw = template.shape[:2]
            if tw > screen.shape[1] or th > screen.shape[0]:
                continue

            match_result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(match_result)

            if score > best_score:
                best_score = float(score)
                x, y = loc
                best_box = (x + ox, y + oy, tw, th)
                best_scale = scale

        self._match_ms.append((time.perf_counter() - started) * 1000.0)

        if best_box is None:
            return result_empty

        x, y, w, h = best_box
        return {
            "found": best_score >= confidence,
            "score": best_score,
            "box": best_box,
            "center": (x + w // 2, y + h // 2),
            "scale": best_scale,
        }

    def best_score(
        self,
        screen_bgr,
        path,
        scales=(1.0,),
        stop_at=None,
        base_scale=1.0,
    ):
        """
        Zwraca najlepszy score. Jeśli stop_at jest ustawione, kończy natychmiast
        po znalezieniu wystarczająco dobrego dopasowania.
        """
        started = time.perf_counter()
        self._match_calls += 1
        best = 0.0

        if screen_bgr is None or screen_bgr.size == 0:
            return best

        effective_scales = tuple(
            max(0.10, min(3.00, float(base_scale) * float(s)))
            for s in scales
        )

        for _, template in self.get_variants(
            path,
            effective_scales,
            grayscale=False,
        ):
            th, tw = template.shape[:2]
            if tw > screen_bgr.shape[1] or th > screen_bgr.shape[0]:
                continue

            result = cv2.matchTemplate(
                screen_bgr,
                template,
                cv2.TM_CCOEFF_NORMED,
            )
            _, score, _, _ = cv2.minMaxLoc(result)
            best = max(best, float(score))

            if stop_at is not None and best >= stop_at:
                break

        self._match_ms.append((time.perf_counter() - started) * 1000.0)
        return best

    @staticmethod
    def crop_abs_region(frame_bgr, raid_rect, region):
        if frame_bgr is None or raid_rect is None or region is None:
            return None

        left, top, _, _ = raid_rect
        x, y, w, h = region

        x1 = max(0, int(x - left))
        y1 = max(0, int(y - top))
        x2 = min(frame_bgr.shape[1], x1 + int(w))
        y2 = min(frame_bgr.shape[0], y1 + int(h))

        if x2 <= x1 or y2 <= y1:
            return None
        return frame_bgr[y1:y2, x1:x2]

    def maybe_log_performance(self, state, interval=20.0):
        now = time.monotonic()
        if now - self._last_perf_log < interval:
            return
        self._last_perf_log = now

        cap = sum(self._capture_ms) / len(self._capture_ms) if self._capture_ms else 0.0
        match = sum(self._match_ms) / len(self._match_ms) if self._match_ms else 0.0
        print(
            f"PERF[{state}]: capture_avg={cap:.1f}ms; "
            f"match_avg={match:.2f}ms; match_calls={self._match_calls}; "
            f"backend={self.backend_name}"
        )
        self._match_calls = 0
