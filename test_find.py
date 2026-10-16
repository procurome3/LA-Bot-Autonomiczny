import pyautogui

for conf in [0.95, 0.90, 0.85, 0.80, 0.75, 0.70]:
    pos = pyautogui.locateOnScreen('./bilder/arena_live_fabian.png', confidence=conf)
    print(f"Confidence {conf}: {pos}")