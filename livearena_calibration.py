"""Kalibracja współrzędnych Live Arena względem client-area okna RAID.

Wszystkie punkty zapisane są w układzie referencyjnym 1024x769.
Dzięki temu przesunięcie lub zmiana rozmiaru okna nie zmienia logiki kliknięć:
punkty są przeliczane na aktualny client rect przed każdą akcją.
"""

REFERENCE_CLIENT = (1024, 769)

# Phase 3: Pick Leader.
LEADER_SLOT_CENTERS = [
    (98, 286),   # slot 1 - górny lewy
    (190, 286),  # slot 2 - górny środkowy
    (282, 286),  # slot 3 - górny prawy
    (145, 404),  # slot 4 - dolny lewy
    (238, 404),  # slot 5 - dolny prawy
]

LEADER_CARD_SIZE = (90, 120)
LEADER_CONFIRM_CENTER = (895, 716)

# Combat
# -------
# Od V8 bot NIE przypisuje A1/A2/A3/A4 do stałych współrzędnych.
# Liczba i położenie aktywnych skilli zależy od championa, a ostatnia ikona
# może być pasywką "P", której nie da się kliknąć.
#
# Normalna akcja:
#   template konkretnego skilla -> dokładny środek znalezionej ikony -> klik.
#
# Ten szeroki region służy do wyszukiwania template'ów oraz awaryjnego
# wykrywania okrągłych przycisków.
SKILL_BAR_BOUNDS = (390, 615, 1024, 769)

# Zachowane wyłącznie dla zgodności ze starszym kodem/testami.
# Nie są używane do normalnego klikania umiejętności.
SKILL_BUTTON_CENTERS = {}
SKILL_BUTTON_HALF_SIZE = {}


def point(rect, ref_point):
    """Punkt z referencji 1024x769 -> aktualny ekran."""
    left, top, width, height = rect
    ref_w, ref_h = REFERENCE_CLIENT
    x, y = ref_point
    return (
        left + round(x * width / ref_w),
        top + round(y * height / ref_h),
    )


def region_from_center(rect, ref_center, ref_half_size):
    """Region (x,y,w,h) wokół punktu referencyjnego."""
    left, top, width, height = rect
    ref_w, ref_h = REFERENCE_CLIENT
    cx, cy = ref_center
    hx, hy = ref_half_size

    x1 = left + round((cx - hx) * width / ref_w)
    y1 = top + round((cy - hy) * height / ref_h)
    x2 = left + round((cx + hx) * width / ref_w)
    y2 = top + round((cy + hy) * height / ref_h)

    return (
        x1,
        y1,
        max(1, x2 - x1),
        max(1, y2 - y1),
    )


def region_from_bounds(rect, bounds):
    """Bounds referencyjne (x1,y1,x2,y2) -> region ekranowy."""
    x1, y1, x2, y2 = bounds
    left, top, width, height = rect
    ref_w, ref_h = REFERENCE_CLIENT

    sx1 = left + round(x1 * width / ref_w)
    sy1 = top + round(y1 * height / ref_h)
    sx2 = left + round(x2 * width / ref_w)
    sy2 = top + round(y2 * height / ref_h)

    return (
        sx1,
        sy1,
        max(1, sx2 - sx1),
        max(1, sy2 - sy1),
    )


def leader_slot_point(rect, slot_index):
    if slot_index < 0 or slot_index >= len(LEADER_SLOT_CENTERS):
        return None
    return point(rect, LEADER_SLOT_CENTERS[slot_index])


def leader_card_region(rect, slot_index):
    if slot_index < 0 or slot_index >= len(LEADER_SLOT_CENTERS):
        return None
    half = (LEADER_CARD_SIZE[0] // 2, LEADER_CARD_SIZE[1] // 2)
    return region_from_center(rect, LEADER_SLOT_CENTERS[slot_index], half)


def skill_button_point(rect, button_name):
    center = SKILL_BUTTON_CENTERS.get(button_name)
    if center is None:
        return None
    return point(rect, center)


def skill_button_region(rect, button_name):
    center = SKILL_BUTTON_CENTERS.get(button_name)
    half = SKILL_BUTTON_HALF_SIZE.get(button_name)
    if center is None or half is None:
        return None
    return region_from_center(rect, center, half)


def skill_bar_region(rect):
    return region_from_bounds(rect, SKILL_BAR_BOUNDS)


def leader_confirm_point(rect):
    return point(rect, LEADER_CONFIRM_CENTER)
