import shared
import time
import pyautogui

# TODO: don't need to actually collect the reward, just cross out and reward will be collected.

def collect():
    # check if visible daily_login
    time.sleep(30)
    #make wrapper for locateOnScreen
    daily_rewards = pyautogui.locateOnScreen('./bilder/daily_login.PNG', grayscale = True, confidence = 0.98)
    if(daily_rewards):
        print("collecting daily")
        #when is collected, "COLLECT" sign dissapear
        not_collected = True
        while(not_collected): 
            time.sleep(1)       
            x, y, w, h = pyautogui.locateOnScreen('./bilder/collect_daily.PNG', grayscale = True, confidence = 0.90)
            if (x):
                print(x, y, w, h)
                x2 = x+w/2
                y2 = y + 53
                pyautogui.moveTo(x2, y2)
                pyautogui.click(x2, y2)
                not_collected = False
    else:
        print("No daily login rewards was detected")
    shared.clickWrap('close_daily')