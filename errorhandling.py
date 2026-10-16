import pyautogui
import time
import opengame
import shared


# LOGGEG_ON_ANOTHER_DEVICE_WAIT_TIME = 21600 # 3 hours
LOGGEG_ON_ANOTHER_DEVICE_WAIT_TIME = 7500 # 1 hours
DO_NOT_RESTART = False

class ErrorManager:
    # to restart game client in case of unexpected fail (when could not find next click object)
    error_detected = False
    did_reset = False

    @classmethod
    def setErrorStatus(cls, value):
        cls.error_detected = value

    @classmethod
    def getErrorStatus(cls):
        return cls.error_detected

errorManager = ErrorManager()

# when can not find button it means something went wrong and game will not recover anymore
# in this case solution is to restart client and start all over
# if shared clickwrapper did not find something
# restart game
def gameReset():
    #print("gameReset")
    #print("errorManager.error_detected ", errorManager.error_detected)
    #print("errorManager.did_reset ", errorManager.did_reset)

    if(errorManager.error_detected == True and errorManager.did_reset == False):
        print("restarting the game in 5 seconds")
        time.sleep(5)
        if(DO_NOT_RESTART):
            print("SHALL NOT RESTART, waiting 24 hours")
            time.sleep(87000)
        opengame.closeGame()
        time.sleep(10)
        opengame.openGame()
        errorManager.did_reset = True
        return 'skip'


        #start script from the start (need a flag) & break script loop?

        #dont forget to ser Flag back to True
    
    # to skip rest of the script
    if(errorManager.did_reset == True):
        return 'skip'
    
    return 'continue'



def clientError():
    result = pyautogui.locateOnScreen(f'./bilder/client_error.PNG', grayscale = False, confidence = 0.95)
    if (result):
        print("Client error. Continue")
        pyautogui.click(result)
        time.sleep(5)

def logedInOnAnotherDevice():
    result = pyautogui.locateOnScreen(f'./bilder/loogged_inn_from_another_device.PNG', grayscale = True, confidence = 0.95)
    if (result):
        print(f'Logged from another device. Waiting {LOGGEG_ON_ANOTHER_DEVICE_WAIT_TIME} hours...')
        time.sleep(LOGGEG_ON_ANOTHER_DEVICE_WAIT_TIME)
        print("Resuming script")
        #shared.clickWrap('re_login') # don't need to re log in because game will restart anyway
        errorManager.error_detected = True

def connectionError():
    result = pyautogui.locateOnScreen(f'./bilder/client_connection_error.PNG', grayscale = True, confidence = 0.95)
    if (result):
        print("Connection error. Retry.")             
        retry = pyautogui.locateOnScreen(f'./bilder/client_connection_retry.PNG', grayscale = True, confidence = 0.95)  
        if(retry):
            pyautogui.click(retry)
        #picture seem to be changing after first retry click
        retry2 = pyautogui.locateOnScreen(f'./bilder/client_connection_retry2.PNG', grayscale = True, confidence = 0.95)  
        if(retry2):
            pyautogui.click(retry2)
        time.sleep(5)

def maintennanceHandler():
    maintenance = pyautogui.locateOnScreen(f'./bilder/maintenance_warning.PNG', grayscale = True, confidence = 0.95)  
    if(maintenance):
        print("meintennance detected")
        print("should close client and reopen 1 hour later")
        time.sleep(2)
        opengame.closeGame()
        time.sleep(60) # should be 1 hour - 3600
        opengame.runopen()
        # TODO:
        # now the script was in the middle of something
        # how to reset whole script and make it start from the start ?

def unfinishedBattleCheck():
    result = pyautogui.locateOnScreen(f'./bilder/unfinished_battle.PNG', grayscale = True, confidence = 0.89, minSearchTime=10)
    if(result):
        shared.clickWrap('unfinished_battle_close')
        return 'detected'


if __name__ == "__main__":
    #connectionError()
    #maintennanceHandler()
    opengame.runopen()