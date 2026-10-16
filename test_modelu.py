import getpass
import time
from pathlib import Path

import pyautogui
from inference_sdk import InferenceHTTPClient, InferenceConfiguration

FOLDER = Path(r"C:\Users\procu\OneDrive\Pulpit\LA R\raid-scripts")
IMAGE = FOLDER / "hydra_test.png"

FOLDER.mkdir(parents=True, exist_ok=True)

print("Przełącz się na grę. Zrzut ekranu za 5 sekund...")
time.sleep(5)
pyautogui.screenshot().save(IMAGE)
print(f"Zapisano zdjęcie: {IMAGE}")

api_key = getpass.getpass("Wpisz klucz API Roboflow: ")

client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=api_key,
).configure(InferenceConfiguration(api_key_transport="header"))

result = client.run_workflow(
    workspace_name="piotr-michal",
    workflow_id="hydra-ui-annotations",
    images={"image": str(IMAGE)},
    parameters={
        "confidence": 0.4,
        "iou_threshold": 0.3,
        "class_agnostic_nms": False,
        "max_detections": 1000,
    },
    use_cache=True,
)

print("Wynik Modelu:")
print(result)
