import pyautogui
import shared
import pyautogui
import time
import closeadds
from flags import flagInstance
import errorhandling
from errorhandling import errorManager

hard_is_done = False
normal_is_done = False

# Will repeat selected boss.
# To select boss, make screenshot of him and save as 'doom_towerboss.png'

def main():
    if(flagInstance.no_cvc):
        if(shared.readyToRun('doomtower')):
            _init()

            if(_isHardDone()):
                _fromHardToNormalAutofarmAndBackToHard()
            else:
                climbHardStages(True) # todo: exclude init & finilize
                
            _finilize()
        doExtraKeys()

def mainBossRepeat(times_to_repeat:int):
    if(flagInstance.no_cvc):
        if(shared.readyToRun('doomtower')):
            _init()
            _findFightRepeat(times_to_repeat)
            _finilize()

# override this if don't farm top boss
def _isHardDone():
    global hard_is_done
    its_done = pyautogui.locateOnScreen('./bilder/doom_tower_hard_is_done.PNG', grayscale = True, confidence = 0.88, minSearchTime=3)
    its_done2 = pyautogui.locateOnScreen('./bilder/doom_tower_hard_is_done2.PNG', grayscale = True, confidence = 0.88, minSearchTime=3)
    its_done3 = pyautogui.locateOnScreen('./bilder/doom_tower_hard_is_done3.PNG', grayscale = True, confidence = 0.88, minSearchTime=3)
    if (its_done or its_done2 or its_done3):
        hard_is_done = True
        print("hard is done")
        return True
    else:
        print("still doing DT hard")
        return False

def doExtraKeys():
    if (not collectKeys(4)):
        return
    #main boss repeat but without checking txt file
    _init()
    _findFightRepeat(7)
    _finilize()

def _ifNormalIsDone():
    global normal_is_done
    its_done = pyautogui.locateOnScreen('./bilder/doom_tower_normal_is_done.PNG', grayscale = True, confidence = 0.88, minSearchTime=5)
    if (its_done):
        normal_is_done = True
        print("normal is done")
        return True
    else:
        print("still doing DT normal")
        return False

def collectKeys(collectAtClock:int):
    readyToRun = shared.readyToRun_NoSave('collectkeysdt', collectAtClock)
    if (not readyToRun):
        return False

    shared.clickWrap('quests')
    shared.clickWrap('advanced')
    ready_to_claim = pyautogui.locateOnScreen('./bilder/ready_to_claim_dt_keys.PNG', grayscale = True, confidence = 0.88, minSearchTime=5)
    if(ready_to_claim):
        shared.clickWrap('ready_to_claim_dt_keys')
        shared.saveRun('collectkeysdt')
        shared.clickWrap('close_arena')
        closeadds.closeAdds()
        return True
    else:
        shared.clickWrap('close_arena')
        closeadds.closeAdds()
        return False

def climbHardStages(replay_boss:bool):
    if(flagInstance.no_cvc):
        # then set farm_normal = True , then climbing hard should be skipped and go farm normal stages instead.
        #if(shared.readyToRun('doomtowerhard')):

        _autoClimb_9battles()
        doomTowerBossClick()
        shared.clickWrap('doom_tower_start_boss')
        if(replay_boss):
            _replayBoss()   
        #_finilize() # bastion & adds
    else:
        print("preparing for cvc")

def farmNormalWhenHardIsDone():
    #if(shared.readyToRun('doomtowernormal')):
    _init()
    _fromHardToNormalAutofarmAndBackToHard()
    _finilize()

def _farmHard():
    shared.clickWrap('doom_tower_double_swords', 60, 0.75)
    shared.clickWrap('doom_tower_start')
    while(True):
        result = errorhandling.gameReset() 
        if (result == 'skip'):
            print(f'skip clickWrap for _farmHard')
            return
        complete = pyautogui.locateOnScreen(f'./bilder/doom_tower_auto_climb_complete.PNG', grayscale = True, confidence = 0.95)
        if(complete):
            shared.clickWrap('doom_tower_close_autocomplete')
            break
    shared.clickWrap('doom_tower_kill_boss_next')
    shared.clickWrap('doom_tower_start_boss')
    _noAuraCheck()
    shared.clickWrap('map', 600)

def _fromHardToNormalAutofarmAndBackToHard():
    result = errorhandling.gameReset() 
    if (result == 'skip'):
        print(f'skip clickWrap for _fromHardToNormalAutofarmAndBackToHard')
        return
    shared.clickWrap('doom_tower_hard')
    shared.clickWrap('doom_tower_normal')

    if(_ifNormalIsDone()):
        shared.clickWrap('doom_tower_normal2')
        shared.clickWrap('doom_tower_hard2')
        _findFightRepeat(11)
        return
    
    _autoClimb_9battles()
    doomTowerBossClick()
    shared.clickWrap('doom_tower_start_boss')
    _noAuraCheck()
    shared.clickWrap('map', 600)
    secretRoom()
    shared.clickWrap('doom_tower_normal2')
    shared.clickWrap('doom_tower_hard2')
    _findFightRepeat(11)


def secretRoom():
    if(shared.clickWrapWithSkip("secret_room") 
       or shared.clickWrapWithSkip('sr9')
       or shared.clickWrapWithSkip('sr11')
       ):
        shared.clickWrap("secret_room_start")
        shared.clickWrap("secret_room_map", 600)

def _noAuraCheck():
    result = pyautogui.locateOnScreen(f'./bilder/no_aura.PNG', grayscale = True, confidence = 0.95)
    if(result):
        shared.clickWrap('no_aura_continue')


def superRaids():
    not_super_raid = pyautogui.locateOnScreen(f'./bilder/not_super_raids_dt.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if(not_super_raid):
        shared.clickToTheLeft('fw_crypt_superraids_dt', 0.9)


def _autoClimb_9battles():
    shared.clickWrapWithSkip('doom_tower_step1', 3, 0.8)
    shared.clickWrapWithSkip('doom_tower_step1_not_first_time', 3, 0.8)
    superRaids()
    shared.clickWrap('doom_tower_step2') #click start

    # - while it was climbing, screen wasn't mooving at all, 100% static
    print("sleep 1500, waiting for autoclimb to complete ")
    time.sleep(1500)

    # shared.clickWrap('doom_tower_bastion')
    shared.clickWrap('close_arena')
    shared.clickWrap('doom_tower')

    # this is a problem when climbed to floor 120, boss is at different location
    doomTowerBossClick()
    closeBackgroundBattleResults()

def doomTowerBossClick():
    # if not final boss, click above rankings button, else click final boss
    final_boss = pyautogui.locateOnScreen(f'./bilder/doom_tower_final_boss.PNG', grayscale = True, confidence = 0.9, minSearchTime=5)
    if(final_boss):
        pyautogui.click(final_boss)
    else:
        rankings = pyautogui.locateOnScreen(f'./bilder/doom_tower_rankings_button.PNG', grayscale = True, confidence = 0.9, minSearchTime=5)
        if (rankings):
            x,y,w,h = rankings
            time.sleep(2)
            pyautogui.click(x-50, y-200)


def closeBackgroundBattleResults():
    shared.clickWrap('doom_tower_results')
    shared.clickWrap('doom_tower_close_results')

def mainStageClimb():
    print("This is not developed yet")

def _findFightRepeat(to_repeat=13):
    if(shared.clickWrapWithSkip("doom_towerboss") or 
       shared.clickWrapWithSkip('dt_boss3') or
       shared.clickWrapWithSkip('dt_boss4') or
       shared.clickWrapWithSkip('doom_tower_boss_top')
       ):
        shared.clickWrap("start_doomtower")
        _replayBoss(to_repeat)

def _replayBoss(to_repeat=12):
    if (shared.clickWrapWithSkip('replay_doomtower_boss', 120)):
        shared.clickWrap('replay_doomtower_boss')
        for i in range(to_repeat):
            shared.clickWrap('replay_doomtower_boss', 120)

def _init():
    shared.clickWrap('battle')
    shared.dragDoomtower()
    shared.clickWrap('doom_tower')

def _finilize():
    shared.clickWrap('bastion', 3000, 0.8)
    closeadds.closeAdds()

if __name__ == "__main__":
    flagInstance.no_cvc = True
    # main()
    doomTowerBossClick()
    shared.clickWrap('doom_tower_start_boss')
    _replayBoss()  
    
