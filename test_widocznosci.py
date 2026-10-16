import os
import sys
import time
import pyautogui

# Sprawdzenie dostępności OpenCV
try:
  import cv2

  print("[INFO] OpenCV jest zainstalowane prawidłowo.")
except ImportError:
  print(
      "[BŁĄD] Brak biblioteki OpenCV! Zainstaluj ją komendą: pip install"
      " opencv-python"
  )

IMG_DIR = os.path.join(
    os.path.dirname(__file__), "bilder", "hydra", "champions"
)
TURNS = {
    "Trunda": os.path.join(IMG_DIR, "turn_trunda.png"),
    "Yumeko": os.path.join(IMG_DIR, "turn_yumeko.png"),
    "Lydia": os.path.join(IMG_DIR, "turn_lydia.png"),
    "Lamasu": os.path.join(IMG_DIR, "turn_lamasu.png"),
}

print("\n=== TESTER WIDOCZNOŚCI TUR (WERSJA Z SCALE GRAYSCALE) ===")
for name, img_path in TURNS.items():
  if os.path.exists(img_path):
    print(f"[PLIK OK] {name}: {img_path}")
  else:
    print(f"[BRAK PLIKU] {name}: {img_path}")

print(
    "\nSkanowanie ekranu w toku... Naciśnij Ctrl+C, aby zatrzymać.\n"
    "------------------------------------------------"
)

counter = 0
while True:
  found_any = False
  for name, img_path in TURNS.items():
    if not os.path.exists(img_path):
      continue
    try:
      # Skanowanie w odcieniach szarości z tolerancją 0.55
      loc = pyautogui.locateOnScreen(img_path, confidence=0.55, grayscale=True)
      if loc:
        print(f"\n>>> BOT WIDZI TURĘ: {name} (pozycja: {loc}) <<<")
        found_any = True
    except Exception as e:
      print(f"\n[BŁĄD WYKRYWANIA - {name}]: {e}")

  if not found_any:
    # Sygnalizacja działania skryptu w konsoli
    sys.stdout.write(".")
    sys.stdout.flush()
    counter += 1
    if counter >= 50:
      print("")
      counter = 0

  time.sleep(0.5)