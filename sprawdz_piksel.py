import time
import pyautogui

print("Najedź kursorem na zielony wskaźnik tury bohatera w grze.")
print("Naciśnij Ctrl+C, aby przerwać.\n")

try:
  while True:
    x, y = pyautogui.position()
    r, g, b = pyautogui.pixel(x, y)
    print(f"X: {x}, Y: {y} | Kolor RGB: R={r}, G={g}, B={b}", end="\r")
    time.sleep(0.2)
except KeyboardInterrupt:
  print("\nZakończono.")