import cv2
import pyautogui
import pygetwindow as gw
import time

# Aktywuj okno gry
windows = gw.getWindowsWithTitle('Raid: Shadow Legends')
if windows:
    win = windows[0]
    try:
        win.activate()
    except:
        pass
    time.sleep(1)
    
    # Zrób screena dokładnie z obszaru gry
    img = pyautogui.screenshot(region=(win.left, win.top, win.width, win.height))
    img.save('screen_game.png')
    frame = cv2.imread('screen_game.png')
    
    print('Zaznacz myszka JEDNA postac i wcisnij SPACJE lub ENTER!')
    r = cv2.selectROI('Zaznacz postac i wcisnij Enter', frame, showCrosshair=True)
    cv2.destroyAllWindows()
    
    if r[2] > 0 and r[3] > 0:
        cropped = frame[r[1]:r[1]+r[3], r[0]:r[0]+r[2]]
        cv2.imwrite('bilder/arena_live_test.png', cropped)
        print(f'Wspolrzedne: {r}')
else:
    print('Nie znaleziono okna gry Raid: Shadow Legends!')
