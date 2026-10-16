import shared
import time
import pyautogui
import closeadds


def farm(times_to_run=1):
    shared.clickWrap('battle')

    #check energy
    time.sleep(2)
    if (pyautogui.locateOnScreen('./bilder/fullenergy.PNG', grayscale = True, confidence = 0.98)):
        print("Energy is full, starting campain farm")
        shared.clickWrap('brutal')
        shared.clickWrap('start8')
        current_run = 0
        while (current_run < times_to_run):
            print(f"run#{current_run}")
            result = shared.clickWrap('replay', 10)
            if (result):
                current_run += 1

        shared.clickWrap('bastion')
        print("Campain farming done")
        closeadds.closeAdds()
    else:
        print("Energy is not full yet")