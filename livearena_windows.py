"""Windows / DPI helpers dla Live Arena.

Cel:
- ctypes / GetClientRect / ClientToScreen
- MSS screenshot
- pyautogui mouse

muszą używać tego samego fizycznego układu współrzędnych.

Na Windows z DPI scalingiem proces nieświadomy DPI potrafi raportować np.
client 1024x769, mimo że fizyczne okno na screenshotcie ma inny rozmiar.
To powoduje przesunięte ROI, skille i kliknięcia.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


_DPI_INITIALIZED = False


def enable_dpi_awareness():
    """Ustaw Per-Monitor-V2 dla bieżącego procesu/wątku, jeśli Windows pozwala."""
    global _DPI_INITIALIZED

    if _DPI_INITIALIZED:
        return True

    if not hasattr(ctypes, "windll"):
        _DPI_INITIALIZED = True
        return False

    ok = False

    # Najpierw proces. -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
    try:
        user32 = ctypes.windll.user32
        fn = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if fn is not None:
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = wintypes.BOOL
            if fn(ctypes.c_void_p(-4)):
                ok = True
    except Exception:
        pass

    # Windows 8.1 fallback.
    if not ok:
        try:
            shcore = ctypes.windll.shcore
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            result = shcore.SetProcessDpiAwareness(2)
            # S_OK == 0; E_ACCESSDENIED zwykle oznacza, że awareness
            # zostało już ustawione wcześniej.
            if result in (0, -2147024891):
                ok = True
        except Exception:
            pass

    # Starszy fallback.
    if not ok:
        try:
            if ctypes.windll.user32.SetProcessDPIAware():
                ok = True
        except Exception:
            pass

    # SetThreadDpiAwarenessContext może poprawić sytuację nawet wtedy,
    # gdy awareness procesu zostało wcześniej ustawione przez inną bibliotekę.
    try:
        user32 = ctypes.windll.user32
        fn = getattr(user32, "SetThreadDpiAwarenessContext", None)
        if fn is not None:
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_void_p
            previous = fn(ctypes.c_void_p(-4))
            if previous:
                ok = True
    except Exception:
        pass

    _DPI_INITIALIZED = True
    return ok


def get_window_dpi(hwnd):
    try:
        fn = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
        if fn is not None:
            return int(fn(hwnd))
    except Exception:
        pass
    return None


# Ustawiamy DPI natychmiast przy imporcie modułu.
enable_dpi_awareness()
