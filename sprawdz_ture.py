import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyautogui

name = sys.argv[1] if len(sys.argv) > 1 else "maly"
folder = Path("hydra_profiles")
profile = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
template = cv2.imread(str(folder / f"{name}_a3.png"))

if template is None:
    raise SystemExit("Brak wzorca A3. Sprawdz folder hydra_profiles.")

print("Pokaz wybrana ture w grze. Zrzut za 5 sekund...")
time.sleep(5)

image = cv2.cvtColor(
    np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR
)
x1, y1, x2, y2 = profile["a3"]
current = image[y1:y2, x1:x2]

if current.shape != template.shape:
    raise SystemExit("Rozmiar ekranu lub obszaru A3 sie zmienil.")

a = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY).astype(np.float32)
b = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY).astype(np.float32)
a -= a.mean()
b -= b.mean()
denominator = np.linalg.norm(a) * np.linalg.norm(b)
score = float(np.sum(a * b) / denominator) if denominator > 1e-6 else -1.0

print(f"Podobienstwo ikony A3 Lamasu: {score:.3f}")
