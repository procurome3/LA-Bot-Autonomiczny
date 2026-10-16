# make_crops.py
import os
import pyautogui
from PIL import ImageGrab

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("1. Najedź myszką dokładnie na środek elementu, który chcesz wyciąć.")
print("2. Nie ruszaj myszy! Zapis nastąpi za 3 sekundy...")
pyautogui.sleep(3)

# Pobieramy aktualną pozycję kursora
x, y = pyautogui.position()
print(f"Wykryto kursor na pozycji: X={x}, Y={y}")

# Ustalamy rozmiar wycinka wokół kursora (np. 50 pikseli w każdą stronę = kwadrat 100x100)
# Możesz zwiększyć tę wartość, jeśli element jest większy
size = 50
left = x - size
top = y - size
right = x + size
bottom = y + size

# Zrobienie zrzutu całego ekranu i wycięcie fragmentu wokół kursora
screenshot = ImageGrab.grab()
cropped_img = screenshot.crop((left, top, right, bottom))

# Zapis pliku
output_path = os.path.join(OUTPUT_DIR, "szablon_z_kursora.png")
cropped_img.save(output_path)

print(f"SUKCES! Wycinek zapisano w folderze templates jako: szablon_z_kursora.png")