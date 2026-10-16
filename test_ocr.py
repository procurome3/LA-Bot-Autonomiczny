import cv2
import numpy as np
import pyautogui
import pytesseract

# Ścieżka do Tesseract OCR
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# === DOSTOSUJ TE WARTOŚCI (left, top, width, height) ===
# Domyślny prostokąt testowy na środku góry ekranu
NAME_REGION = (850, 50, 220, 50)

print("--- URUCHOMIONO TEST OCR ---")
print("Upewnij się, że gra jest uruchomiona i widać nazwę postaci.")
print("Naciśnij Ctrl+C w terminalu, aby zakończyć test.\n")

while True:
  try:
    # 1. Zrób zrzut ekranu wybranego obszaru
    screenshot = pyautogui.screenshot(region=NAME_REGION)

    # 2. Konwersja do skali szarości i wyostrzenie kontrastu pod OCR
    gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    _, processed_img = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)

    # 3. Odczytaj tekst
    text = pytesseract.image_to_string(processed_img, config="--psm 7").strip()

    print(f"Odczytano tekst: '{text}' (obszar: {NAME_REGION})")

  except KeyboardInterrupt:
    print("\nZatrzymano test.")
    break
  except Exception as e:
    print(f"Błąd: {e}")

  # Pauza 2 sekundy przed kolejnym odczytem
  import time

  time.sleep(2.0)