import pyautogui
import shared
import time
import closeadds


def upgradeChampions():
    print("upgradeChampions. Checking if upgrade required...")
    # result = pyautogui.locateOnScreen('./bilder/guardian_ring_new.PNG', grayscale = False, confidence = 0.99)
    result = pyautogui.locateOnScreen('./bilder/guardian_ring_new_oz_even.PNG', grayscale = False, confidence = 0.99)
    # result = pyautogui.locateOnScreen('./bilder/guardian_ring_aniversary_7.PNG', grayscale = False, confidence = 0.99)
    #result = pyautogui.locateOnScreen('./bilder/guardian_ring_6th_aniversary.PNG', grayscale = False, confidence = 0.99)
    #result = pyautogui.locateOnScreen('./bilder/guardian_ring_new_xmas.PNG', grayscale = False, confidence = 0.99)
    #result = pyautogui.locateOnScreen('./bilder/guardian_ring_new_halloween.PNG', grayscale = False, confidence = 0.99)
    if(result):
        print("guardian ring - training finished")
        pyautogui.click(result)
        while(True):
            time.sleep(3)
            all_results = pyautogui.locateAllOnScreen('./bilder/guardian_ring_upgrade1.PNG', grayscale = True, confidence = 0.8)
            if(all_results):
                for i in all_results:
                    pyautogui.click(i)
                    time.sleep(0.5)
                print("Level up in training pit.")
                break # break out of while
            max_lvl = pyautogui.locateAllOnScreen(f'./bilder/guardian_ring_max_level.PNG', grayscale = False, confidence = 0.95)
            if (len(list(max_lvl)) == 5):
                print("Max level in training pit.")
                break # in case max level reached


        shared.clickWrap('close_arena')

        closeadds.closeAdds()
    else:
        print("not ready yet.")

if __name__ == "__main__":
    upgradeChampions()