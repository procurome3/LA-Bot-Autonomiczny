import pyautogui
import keyboard

print("Narzędzie do kalibracji współrzędnych.")
print("Najedź kursorem na wybrany punkt w grze i wciśnij klawisz 'g'.")
print("Wciśnij 'esc', aby zakończyć działanie skryptu.\n")

def pobierz_pozycje():
    x, y = pyautogui.position()
    print(f"Zapisano pozycję -> X: {x} | Y: {y}")

# Przypisanie klawisza 'g' do wywołania funkcji
keyboard.add_hotkey('g', pobierz_pozycje)

# Skrypt działa w tle i czeka, aż wciśniesz 'esc'
keyboard.wait('esc')
print("Zakończono kalibrację.")