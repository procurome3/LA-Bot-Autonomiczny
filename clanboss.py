import shared
import pyautogui
import time
from datetime import datetime, timedelta
import closeadds
import errorhandling


cb = ['unm', 'nm', 'brutal', 'hard']
#cb = ['unm', 'nm', 'brutal']

def main():
    for i in cb:
        __cbSelected(i)

def __cbSelected(cb_difficulty):
    if (errorhandling.gameReset()  == 'skip'):
        return
    file_path = f'./textfiles/{cb_difficulty}.txt'
    print("starting clan boss run for ", file_path)
    ready_to_run: bool = __ready_to_run_cb(file_path) #was did_run_today
    print("execution status: ", ready_to_run)
    if ready_to_run:
        __initCB()
        if __hasKeys():#key check here. What happens when there is no key, why it does write execution????
            __initFight(cb_difficulty)
            __write_execution_status(file_path)
            __finilizeCNrun
        __finilizeCB() # need changes here
    else:
        print("execution status / ready to run ", ready_to_run)

def __initFight(difficulty):
    shared.clickWrap('demonlord')
    shared.clickWrap('clanboss_easy')
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    shared.clickWrap(f'clanboss_{difficulty}')
    __claimRewards()
    shared.clickWrap('battle-clan-boss')
    if (__extracheck() == '+0'):
        return '+0'
    shared.clickWrap('start-clan-boss')
    print("cb started")
    return '+1'

def __initCB():
    print(f'Starting clanboss run')
    shared.clickWrap('battle')
    shared.clickWrap('clan')

def __finilizeCNrun():
    while(True):
        result = pyautogui.locateOnScreen('./bilder/clanboss_result.PNG', grayscale = True, confidence = 0.95)
        if(result):
            shared.clickWrap('clanboss_continue')
            break
    shared.clickWrap('close_arena')
    shared.clickWrap('close_arena')

def __finilizeCB():
    shared.clickWrap('bastion', 3600)
    closeadds.closeAdds()

def __claimRewards():
    time.sleep(1)
    result = pyautogui.locateOnScreen('./bilder/clan_boss_claim_rewards.PNG', grayscale = True, confidence = 0.95)
    if (result):
        pyautogui.click(result)
        shared.clickWrap('clan_boss_claim_rewards2')
        time.sleep(2)
        shared.clickWrap('clan_boss_claim_rewards2')

# zero Keys - True
def __hasKeys():
    time.sleep(2)
    if (pyautogui.locateOnScreen('./bilder/0cb_key.PNG', grayscale = True, confidence = 0.99, minSearchTime=3)):
        print("zero CB keys")
        return False
    return True

# first check should not fail, but if it will:
def __extracheck():
    time.sleep(2)
    if (pyautogui.locateOnScreen('./bilder/demon_lord_key.PNG', grayscale = True, confidence = 0.99)):
        shared.clickWrap('demon_lord_key_close')
        shared.clickWrap('close_arena')
        shared.clickWrap('bastion', 3000)
        closeadds.closeAdds()
        return '+0'
  
def test_write_brutal():
    __write_execution_status('brutal')

def __write_execution_status(file_path):
    current_datetime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with open(file_path, 'w') as file:
        file.write(current_datetime)


def __ready_to_run_cb(file_path, current_time=None):
    try:
        with open(file_path, 'r') as file:
            execution_datetime_str = file.read().strip()
            executed_last_time = datetime.strptime(execution_datetime_str, "%d.%m.%Y %H:%M:%S")
            current_datetime = current_time or datetime.now()
            if current_datetime.hour >= 13 and (current_datetime.hour > 13 or current_datetime.minute >= 15):
                current_time_frame_start = datetime(
                    current_datetime.year, current_datetime.month, current_datetime.day, 13, 15, 0
                )
            else:
                previous_day = current_datetime - timedelta(days=1)
                current_time_frame_start = datetime(
                    previous_day.year, previous_day.month, previous_day.day, 13, 15, 0
                )
            time_frame_end = current_time_frame_start + timedelta(days=1) - timedelta(minutes=20) - timedelta(seconds=1)
            print("current_time_frame_start ", current_time_frame_start)
            print("executed_last_time ", executed_last_time)
            print("time_frame_end ", time_frame_end)
            if current_time_frame_start <= executed_last_time <= time_frame_end:
                print("Allready did run today")
                return False
            else:
                print("Ready to run")
                return True
    except FileNotFoundError:
        return False
    

def __ready_to_run(file_path, current_time=None):
    try:
        with open(file_path, 'r') as file:
            execution_datetime_str = file.read().strip()
            executed_last_time = datetime.strptime(execution_datetime_str, "%d.%m.%Y %H:%M:%S")
            current_datetime = current_time or datetime.now()
            if current_datetime.hour >= 12 and (current_datetime.hour > 12 or current_datetime.minute >= 15):
                current_time_frame_start = datetime(
                    current_datetime.year, current_datetime.month, current_datetime.day, 12, 15, 0
                )
            else:
                previous_day = current_datetime - timedelta(days=1)
                current_time_frame_start = datetime(
                    previous_day.year, previous_day.month, previous_day.day, 12, 15, 0
                )
            time_frame_end = current_time_frame_start + timedelta(days=1) - timedelta(minutes=20) - timedelta(seconds=1)
            if current_time_frame_start <= executed_last_time <= time_frame_end:
                print("Allready did today")
                return False
            else:
                print("Ready to run")
                return True
    except FileNotFoundError:
        return False



if __name__ == "__main__":
    main()
    #__hasKeys()
    #__claimRewards()