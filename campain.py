import pyautogui
import time
import errorhandling
import shared


#heroStars 1-5*
heroLevel = 3
# campaing difficulty normal/hard/brutal/nightmare
difficulty = 'normal'


def calculateRuns(herolvl):
    #12.3 +8652
    match herolvl:
        case 1:
            if (difficulty == 'normal'):
                print("runs to run: ", 7)  # 24 energy
                return 6
            print("runs to run: ", 3)  # 24 energy
            return 2
        case 2:
            print("runs to run: ", 10) # 88 energy
            return 9
        case 3:
            print("runs to run: ", 22) # 200 energy
            return 23
        case 4:
            print("runs to run: ", 52) # 424 energy
            return 51
        case 5:
            print("runs to run: ", 112) # 896 energy
            return 112 #done 65
    return 0


def campainRepeat(_timesToRun):
    result = errorhandling.gameReset() 
    if (result == 'skip'):
        print(f'skip campainRepeat')
        return
    
    currentRun = 0
    while(currentRun < _timesToRun):
        result = errorhandling.gameReset() 
        if (result == 'skip'):
            print(f'skip __repeatDungeon for replay_campain')
            return
        
        time.sleep(2)
        result = shared.clickWrap('replay_campain', 300) # will escape while loop if this sets error state
        if(result):
            currentRun += 1
            #_refill(result)
    print("COMLETE")

def _refill(result_repeat):
    time.sleep(3)
    refill = pyautogui.locateOnScreen('./bilder/confirm_refill.PNG', grayscale = True, confidence = 0.97)
    if(refill):
        pyautogui.click(refill)
        time.sleep(1)
        pyautogui.click(result_repeat)

if __name__ == "__main__":
    timesToRun = calculateRuns(heroLevel)
    campainRepeat(timesToRun)
