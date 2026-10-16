import time
import pyautogui

print("Najedź myszką na ikonę umiejętności. Wyjście: Ctrl+C")
try:
    while True:
        x, y = pyautogui.position()
        print(f"X: {x}, Y: {y}", end="\r")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nZatrzymano.")
