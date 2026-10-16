import shared
import closeadds
import pyautogui
import time
from datetime import datetime
import errorhandling
from errorhandling import errorManager
from flags import flagInstance

# Dungeons to run. Each takes input with
# 1.file name with picture of dungeon entrance - example 'spider'
# 2.file name with dungeon level to run - example 'spider_20'
# 3.how many time to repeat dungeon


def ironTwins():
    if(flagInstance.no_cvc):
        if(shared.readyToRun('irontwins', 6) and collectEnergy()):
        # if(True):
            shared.clickWrap('all_keys')
            shared.clickWrap('fortress_keys')
            
            if (shared.clickToTheRightWrapWithSkip('iron_twins_15', 3) or 
                shared.clickToTheRightWrapWithSkip('iron_twins_15_blue', 3)
                ):

                shared.clickWrap('multi-battle')
                shared.clickToTheLeft('iron_twins_use_gems')
                is_sunday = datetime.now().weekday() == 6
                if (is_sunday):
                    shared.clickToTheLeft('iron_twins_buy_more_keys')

                shared.clickWrap('start-multi-battle')
                complete = pyautogui.locateOnScreen(f'./bilder/iron_twins_autobattle_complete.PNG'
                                                    , grayscale = True, confidence = 0.95, minSearchTime=2960)
                if(complete):
                    shared.clickWrap('iron_twins_close_autocomplete')
                else:
                    errorManager.error_detected = True
                shared.clickWrap('bastion')
                closeadds.closeAdds()

def collectEnergy():
    shared.clickWrap("rewards_playtime_enter")
    pt_energy = pyautogui.locateOnScreen(f'./bilder/pt_energy.PNG', grayscale = True, confidence = 0.96, minSearchTime=10)
    if(pt_energy):
        pyautogui.click(pt_energy)
        shared.clickWrap("close_pt")
        closeadds.closeAdds()
        return True
    else:
        return False

def icegolem(times_to_run=1):
    __dungeonRun('ice_golem', 'ice_golem_20', times_to_run)

def spider(times_to_run=1):
    __dungeonRun('spider', 'spider_20', times_to_run)

def dragon(times_to_run=1):
    __dungeonRun('dragon', 'dragon_20', times_to_run)

def fireknight(times_to_run=1):
    __dungeonRun('fireknight', 'fireknight_20', times_to_run)

def minotaur(times_to_run=1):
    __dungeonRun('minotaur', 'minotaur_15', times_to_run)

def eventDungeon(times_to_run=1):
    __dungeonRun('event_dungeon', 'event_dungeon_30', times_to_run)
    
def sanddevil(times_to_run=1):
    __initDungeonMore()
    shared.clickWrap('sanddevil_dungeon')
    shared.clickToTheRight('sanddevil_25')
    if(__refyllAndReclick('sanddevil_25', 'onStart') == 100):
        return
    #__refyllAndReclick('sanddevil_25')
    if(__startAndRepeatDungeon(times_to_run, 'sanddevil_25', 'start_dungeon') == 100):
        return
    #__startAndRepeatDungeon(times_to_run, 'sanddevil_25', 'start_dungeon')
    __finilizeDungeon()

def shogun(times_to_run=1):
    __initDungeonMore()
    shared.clickWrap('shogun_dungeon')
    shared.clickToTheRight('shogun_25')
    if(__refyllAndReclick('shogun_25', 'onStart') == 100):
        return
    if(__startAndRepeatDungeon(times_to_run, 'shogun_25', 'start_dungeon') == 100):
        return
    #__refyllAndReclick('shogun_25')
    #__startAndRepeatDungeon(times_to_run, 'shogun_25', 'start_dungeon')
    __finilizeDungeon()

def arcaneKeep(times_to_run=1):
    __potionRun('arcane_keep', 'potion_keep_arcane_20', times_to_run)

def forceKeep(times_to_run=1):
    __potionRun('force_keep', 'potion_keep_force_20', times_to_run)

def magicKeep(times_to_run=1):
    __potionRun('magic_keep', 'potion_keep_magic_20', times_to_run)

def spiritKeep(times_to_run=1):
    __potionRun('spirit_keep', 'potion_keep_spirit_20', times_to_run)

def voidKeep():
    print("not done yet")

def __dungeonRun(dungeon_name:str, dungeon_level:str, times_to_run:int, start_energy='start_dungeon'):
    __initDungeon()
    shared.clickWrap(dungeon_name)
    shared.clickToTheRight(dungeon_level)
    if(__refyllAndReclick(dungeon_level, 'onStart') == 100):
        return
    if(__startAndRepeatDungeon(times_to_run, dungeon_name, start_energy) == 100):
        return
    __finilizeDungeon()

def __potionRun(dungeon_name:str, dungeon_level:str, times_to_run:int, start_energy='start_dungeon'):
    shared.clickWrap('battle')
    shared.clickWrap('dungeons')
    shared.clickWrap(dungeon_name)
    shared.clickToTheRight(dungeon_level)
    if(__refyllAndReclick(dungeon_level, 'onStart') == 100):
        return
    if(__startAndRepeatDungeon(times_to_run, dungeon_name, start_energy) == 100):
        return
    __finilizeDungeon()

def __initDungeon():
    shared.clickWrap('battle', 5)
    shared.clickWrap('dungeons')
    shared.dragDungeon()

def __initDungeonMore():
    shared.clickWrap('battle', 5)
    shared.clickWrap('dungeons')
    shared.dragDungeon()
    time.sleep(1)
    shared.dragDungeonMore()

def __startAndRepeatDungeon(times_to_run: int, dungeon_name: str, start_energy: str):
    shared.clickWrap(start_energy) #click start button
    if(__refyllAndReclick(start_energy, 'onStart2') == 100):# this is needed in case super raid is enabled, refyll will be asked here
        return 100
    __noAuraCheck() # does it comes before or after refyll bs?
    current_run = 1

    # current behavior: if(flagInstance.normal_cycle): run 1 time else run 5 times
    # desired behavior: 
    # run until run out of energy - ok , lets test
    # run until run out of refylls in inventory
    # run amout of times with gem refylls

    # when no more energy this will exit dungeon to bastion
    while (flagInstance.run_until_empty): # REPEAT UNTILL NO MORE ENERGY
        result = errorhandling.gameReset() 
        if (result == 'skip'):
            print(f'skip __repeatDungeon for {dungeon_name}')
            return
        shared.clickWrap('replay', 2000)
        if(__refyllAndReclickAfterBattle('replay', 'onRepeat') == 100):
            return 100
                    
    while (current_run < times_to_run):
        result = errorhandling.gameReset() 
        if (result == 'skip'):
            print(f'skip __repeatDungeon for {dungeon_name}')
            return
        result = shared.clickWrap('replay', 9000)
        if(__refyllAndReclick('replay', 'onRepeat') == 100): #why this? for intensive_cycle ?
            return
        if (result):
            current_run += 1

def __finilizeDungeon():
    shared.clickWrap('bastion', 600) #10 min
    print("Dungeon run finished")
    closeadds.closeAdds()

def __refyllAndReclick(what_to_repeat: str, typeExit: str):
    #refill_detected = pyautogui.locateOnScreen('./bilder/refyll_bottle.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    refill_detected = pyautogui.locateOnScreen('./bilder/refyll_detected.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if (refill_detected):
        refyll_from_inventory_detected = pyautogui.locateOnScreen('./bilder/confirm_refill.PNG', grayscale = True, confidence = 0.9, minSearchTime=1)
        refyll_w_gem_detected = pyautogui.locateOnScreen('./bilder/confirm_refyll_gem.PNG', grayscale = True, confidence = 0.9, minSearchTime=1)

        if (refyll_from_inventory_detected and flagInstance.refyll_from_inventory): #TODO TEST
            shared.clickWrap('confirm_refill')
            shared.clickToTheRight(what_to_repeat) # TO BE USED TO REFYLL FROM INVENTORY NEED TO USE clickWrap('replay') 
        if (refyll_w_gem_detected and flagInstance.refyll_with_gem): #WORKS OK
            shared.clickWrap('confirm_refyll_gem')
            shared.clickToTheRight(what_to_repeat)
        else: #WORKS OK
            print("not refylling, exiting to bastion")
            exitDungeon(typeExit)
            return 100
    else:
        print("refyll not needed, run the dungeon")

def __refyllAndReclickAfterBattle(what_to_repeat: str, typeExit: str):
    # refill_detected = pyautogui.locateOnScreen('./bilder/refyll_bottle.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    refill_detected = pyautogui.locateOnScreen('./bilder/refyll_detected.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if (refill_detected):
        # if these are not detected - going to restart
        # should handle in elif (not detected ?)
        refyll_from_inventory_detected = pyautogui.locateOnScreen('./bilder/confirm_refill.PNG', grayscale = True, confidence = 0.8, minSearchTime=2)
        refyll_w_gem_detected = pyautogui.locateOnScreen('./bilder/confirm_refyll_gem.PNG', grayscale = True, confidence = 0.8, minSearchTime=2)

        if (refyll_from_inventory_detected and flagInstance.refyll_from_inventory):
            shared.clickWrap('confirm_refill')
            shared.clickWrap(what_to_repeat)
        if (refyll_w_gem_detected and flagInstance.refyll_with_gem):
            shared.clickWrap('confirm_refyll_gem')
            shared.clickWrap(what_to_repeat)
        else:
            print("not refylling, exiting to bastion")
            exitDungeon(typeExit)
            return 100
    else:
        print("refyll not needed, run the dungeon")

def __noAuraCheck():
    print("checking no aura bullshit")
    no_aura = pyautogui.locateOnScreen('./bilder/no_aura.PNG', grayscale = True, confidence = 0.97, minSearchTime=4)
    if(no_aura):
        shared.clickWrap('no_aura_continue')
    else:
        print("no_aura not detected")

def exitDungeon(typeExit):
    if(typeExit == 'onStart'):
        shared.clickWrap('tag_arena_refill_close')
        time.sleep(1)
        shared.clickWrap('tag_arena_refill_close')
        shared.clickWrap('bastion')
        closeadds.closeAdds()
    elif(typeExit == 'onStart2'):
        shared.clickWrap('tag_arena_refill_close')
        time.sleep(1)
        shared.clickWrap('tag_arena_refill_close')
        time.sleep(1)
        shared.clickWrap('tag_arena_refill_close')
        shared.clickWrap('bastion')
        closeadds.closeAdds()
    elif(typeExit == 'onRepeat'):
        shared.clickWrap('tag_arena_refill_close')
        shared.clickWrap('bastion')
        closeadds.closeAdds()
    else:
        print("WRONG USE OF FUNCTION DETECTED")


if __name__ == "__main__":
    #print("Dungeon run #")
    #minotaur()
    #shared.dragDungeon()
    flagInstance.no_cvc = True
    ironTwins()
    #collectEnergy()
    #sanddevil()
    #dragon()
    #shogun()
    #icegolem()
    #__initDungeon()
    #eventDungeon()
    #shogun()

    #event_dungeon
    #event_dungeon_30
