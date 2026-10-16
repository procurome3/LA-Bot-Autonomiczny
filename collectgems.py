import pyautogui
import shared
import datetime
import json
import errorhandling
from errorhandling import errorManager

def main():
    if (errorhandling.gameReset()  == 'skip'):
        return
    
    if(shared.readyToRun('collectgems')):
    #if(True):
        # result = pyautogui.locateOnScreen('./bilder/gem_mine_halloween.PNG', grayscale = True, confidence = 0.9, minSearchTime=5)
        result = pyautogui.locateOnScreen('./bilder/gem_mine.PNG', grayscale = True, confidence = 0.9, minSearchTime=5)
        if(result):
            x,y,w,h = result
            pyautogui.click(x, y)
            print("Collected gems")
            return
        else:
            print("Failed to locate gem mine")
            time_now = datetime.datetime.now().replace(microsecond=0)
            with open(f'./textfiles/gemfail.txt', 'w') as file:
                file.write(json.dumps({"FAILET TO COLLECT GEM: ": time_now.isoformat()}))


if __name__ == "__main__":
    main()