import os
import cv2

# Dynamiczne wyznaczenie ścieżki do obrazka
script_dir = os.path.dirname(os.path.abspath(__file__))
image_path = os.path.join(script_dir, 'bilder', 'arena.PNG')

print(f"Szukam pliku pod ścieżką: {image_path}")

# Sprawdzenie czy plik istnieje
if os.path.exists(image_path):
    img = cv2.imread(image_path)
    if img is not None:
        print("Obraz został pomyślnie wczytany!")
    else:
        print("Plik istnieje, ale OpenCV nie mogło go odczytać (uszkodzony plik/zły format).")
else:
    print("Nie znaleziono pliku! Sprawdź czy nazwa i folder się zgadzają.")