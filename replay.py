import pyautogui
import time


timesToRun = 40
currentRun = 0


while(currentRun < timesToRun):
    result = pyautogui.locateOnScreen('./bilder/replay.PNG', grayscale = True, confidence = 0.76)
    #print (result)
    if(result):
        time.sleep(1)
        currentRun += 1
        print(currentRun, " clicking", result)
        #pyautogui.click(result, duration=0.6)
        pyautogui.moveTo(result)
        pyautogui.mouseDown()
        pyautogui.mouseUp()
        #shared.clickWrap('dragonheir_challenge_again10')

        time.sleep(5)
        # if energy is empty
        refill = pyautogui.locateOnScreen('./bilder/confirm_refill.PNG', grayscale = True, confidence = 0.97)
        if(refill):
            pyautogui.click(refill)
            pyautogui.click(result)

    time.sleep(0.5)
print("COMLETE")

"""
leveling up chickens
spider 20 - exp per run - 5999
spider 25 - exp per run - 5999
minotaur 15-exp per run - 4152
SD-25 - 11998 epx per double run - 687 energy to max 3*
dragon 10h -exp per run - 

                    runs    energy
rank 1 - 22761      - 4     - 64
rank 2 - 81326      - 14    - 224 (when setting a repeat, set one less)
rank 3 - 200681     - 34    - 544 (lvl18 -> max 24 runs)
rank 4 - 449082     - 75    - 1200
rank 5 - 963806     - 160   - 2560
rank 6 - 2010669    - 335   - 5360

300k exp

"""