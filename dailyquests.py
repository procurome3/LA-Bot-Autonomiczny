import datetime
import json
import factionwars
import shared
import campain
import closeadds
import pyautogui
import time

time_now = datetime.datetime.now().replace(microsecond=0)

# Way to solve it:
# 1. Take picture of all quests available
# 2. Do once per day: iterate over the list and build list with 'quests of the day'
# 3. Perform all 'quests of the day'


allQuests = [
    'campainBoss3times', 
    'campain7times', 
    'increaseChampLevel3times', 
    'artUpdate4times', 
    'updateChampInTavern'
    ]

# For those quests that are not repeated everyday
dailyQuestDetected = []

def main():
    if (shared.readyToRun('dailyquests')):
        print("Starting daily quests")
        scanAvailableQuests()
        summon3champions()     
        updateChampInTavern()   
        doScannedQuests()
    if (shared.readyToRun('dailyadvrewards', 6)):
        return collectedAdvancedDaily()
    return False

def updateChampInTavern():
    print("updating champion with brew")
    #open tavern
    shared.clickWrap('tavern')
    shared.clickWrap('sorting')
    shared.clickBelow('tavern_below_filter', 50) #pick champion
    shared.clickBelow('tavern_below_filter', 50) #pick brew
    shared.clickWrap('tavern_update')
    shared.clickWrap('tavern_close')
    closeadds.closeAdds()

def campain7times():
    shared.clickWrap('battle')
    #shared.clickWrap('campain_quick_brimstone_path') # uncomment for brutal
    shared.clickWrap('campain_quick_brimstone_path_NORMAL')
    shared.clickWrap('close_arena')
    #shared.clickToTheRight('brimstone_path_stage3') # uncomment for brutal
    shared.clickToTheRight('brimstone_path_stage3_NORMAL')
    shared.clickWrap('start_dungeon')
    campain.campainRepeat(6)
    shared.clickWrap('bastion')
    closeadds.closeAdds()

def increaseChampLevel3times():
    print("increaseChampLevel3times will run")

def summon3champions():
    print("summon3champions will run")
    shared.clickWrap('portal')
    shared.clickWrap('summon500')
    shared.clickWrap('summon500_2')
    shared.clickWrap('summon500_2')
    shared.clickWrap('close_arena')
    shared.clickWrap('close_arena')
    closeadds.closeAdds()
    
def campainBoss3times():
    shared.clickWrap('battle')
    #shared.clickWrap('campain_quick_brimstone_path') # uncomment for brutal
    shared.clickWrap('campain_quick_brimstone_path_NORMAL')
    shared.clickWrap('close_arena')
    #shared.clickToTheRight('brimstone_path_stage7') # uncomment for brutal
    shared.clickToTheRight('brimstone_path_stage7_NORMAL')
    shared.clickWrap('start_dungeon')
    campain.campainRepeat(2)
    shared.clickWrap('bastion')
    closeadds.closeAdds()

def artUpdate4times():
    print("artUpdate4times will run")

def fightArena5times():
    print("fightArena5times will run")

# Daily quests
# 1. Automatically done
#   -Fight arena 5 times
#
# 2. Need to be done somehow
#   -Campain boss 3 times (auto, ) dailyquests_beatboss3times
#   -Campain 7 times (auto, )
#   -Summon 3 champions (auto, done)
#   -Increase champion level 3 times in tavern (auto)
#   -Upgrade artifact 4 attempts


# Advanced daily quests
# 1. Automatically done
#   -use 12 crypt keys
#   -win 3 artefacts from dungeon
#   -use 5 silver keys in doomtower
#   -fight Demon Lord with rare champ
#   -win 30 Materials from Faction Wars Crypts
# 2. Need to be done somehow
#   -use 3 glyphs (manual)
#   -win Tag Team Arena agains a team with higher Power (manual)
#   -fight 5 tag team arena (mb auto)


def scanAvailableQuests():
    shared.clickWrap('quests')
    bottle_scan = pyautogui.locateOnScreen(f'./bilder/quests_bottle.PNG', grayscale = True, confidence = 0.95)
    if (bottle_scan):
        x,y,w,h = bottle_scan
        pyautogui.moveTo(x,y,0.4)
        pyautogui.scroll(-5)
        pyautogui.scroll(-5)
        pyautogui.scroll(-5)
        pyautogui.scroll(-5)

        # quest scan
        boss3times = pyautogui.locateOnScreen(f'./bilder/dailyquests_beatboss3times.PNG', grayscale = True, confidence = 0.95)
        if (boss3times):
            print("boss 3 times detected")
            dailyQuestDetected.append('campainBoss3times')
        
        campain7times = pyautogui.locateOnScreen(f'./bilder/dailyquests_campain7times.PNG', grayscale = True, confidence = 0.95)
        if (campain7times):
            print("campain 7 times detected")
            dailyQuestDetected.append('campain7times')
        
    shared.clickWrap('close_arena')
    closeadds.closeAdds()

def collectedAdvancedDaily():
    keys_collected = False
    print("collect adv dailyes")
    shared.clickWrap('quests')
    shared.clickWrap('advanced')
    result = pyautogui.locateOnScreen(f'./bilder/daily_quest_adv_5tagteam.png', grayscale = True, confidence = 0.95)
    if(result):
        shared.clickToTheRight('daily_quest_adv_5tagteam')
        keys_collected = True
    
    result2 = pyautogui.locateOnScreen(f'./bilder/daily_quest_adv_12cryptkey.png', grayscale = True, confidence = 0.95)
    if(result2):
        shared.clickToTheRight('daily_quest_adv_12cryptkey')   
    
    time.sleep(1)
    shared.clickWrap('close_arena')
    closeadds.closeAdds()
    #reset factionwars2.txt
    #collected avd rewards today: True

    #write to file

    # then when trying to run faction wars part2 - run if (todaysDate and collectedAdvReward==True)
    return keys_collected

def _switch(x):
    match x:
        case 'campainBoss3times':
            print("starting boss3times")
            campainBoss3times()
            return
        case 'campain7times':
            print("starting campain7times")        
            campain7times()
            return
        case _:
            print("QUEST IS NOT DEFINED")
            return 0   # 0 is the default case if x is not found

def doScannedQuests():
    print("daily quest on the list: ")
    for i in dailyQuestDetected:
        print(i)
        _switch(i)


def collectPlaytimeRewards():
    if (shared.readyToRun('dailyrewards')):
        rewards_playtime = [
            'r1',
            'r2',
            'r3',
            'r4',
            'r5',
            'r6',
            'r7',
        ]
        playtime_ready = pyautogui.locateOnScreen(f'./bilder/rewards_playtime_enter.PNG', grayscale = True, confidence = 0.95)
        pyautogui.click(playtime_ready)

        for x in rewards_playtime:
            result = pyautogui.locateOnScreen(f'./bilder/{x}.PNG', grayscale = True, confidence = 0.95)
            if (result):
                pyautogui.click(result)
                time.sleep(0.6)        
        closeadds.closeAdds()
        return True
    return False

def collectDailyQuestEnergy():
    shared.clickWrap('quests')

if __name__ == "__main__":
    main()
    #campain7times()
    #campainBoss3times()
    #updateChampInTavern()
