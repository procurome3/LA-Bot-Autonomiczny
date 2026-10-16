import shared
import pyautogui
import time
import closeadds
import errorhandling
from errorhandling import errorManager
from flags import flagInstance
from datetime import datetime, timedelta

# This refresh classic arena and search champions from list of easy champions
# When no more arena tokens, will use free refills.

#todo: will probably break on gem refyll. take screenshot, and update line 83-90

refyll_w_gem = False
TAG_ARENA_GEM_REFYLL = False #seem to refyll infinetly

easy_champs = [
    'arena_classic_arbiter',
    'arena_classic_armiger',
    'arena_classic_armanz',
    'arena_classic_akemtum',
    'arena_classic_athel',
    'arena_classic_coldheart',
    'arena_classic_dh',
    'arena_classic_dk',
    'arena_classic_diabolist',
    'arena_classic_duches',
    'arena_classic_elhain',
    'arena_classic_fenax',
    'arena_classic_frozen_banshee',
    'arena_classic_gravechill',
    'arena_classic_heiress',
    'arena_classic_hk',
    'arena_classic_hounds',
    'arena_classic_incubus',
    'arena_classic_kael',
    'arena_classic_kymar',
    'arena_classic_knot',
    'arena_classic_lydia',
    'arena_classic_lysandra',
    'arena_classic_marishka',
    'arena_classic_mavara',
    'arena_classic_magekiller',
    'arena_classic_mikage',
    'arena_classic_nekmo',
    'arena_classic_panda',
    'arena_classic_pythion',
    'arena_classic_painkeeper',
    'arena_classic_renegade',
    'arena_classic_rector',
    'arena_classic_spirithost',
    'arena_classic_siphi',
    'arena_classic_ultan',
    ]



def classic():
    shared.clickWrap('battle')
    shared.clickWrap('arena')
    shared.clickWrap('arena_classic')
    shared.clickWrap('arena_classic_refresh', 1000)
    result = pyautogui.locateOnScreen(f'./bilder/battle_arena_classic.PNG', grayscale = True, confidence = 0.95)
    if (result):
        x,y,w,h = result
        pyautogui.moveTo(x,y,0.4)
    if(searchAndFight() == 100):
        return # one of exits handle exitArena by himself
    exitArena()
    print("arena run finish")

def tagTeam(event_start_iso_date: str):
    if(flagInstance.no_cvc and allowToRanTagArena(event_start_iso_date)):
        shared.clickWrap('battle')
        shared.clickWrap('arena')
        shared.clickWrap('tag_arena')
        shared.clickWrap('tag_arena_refresh', 1000)
        result = pyautogui.locateOnScreen(f'./bilder/tag_arena_battle.PNG', grayscale = True, confidence = 0.95)
        if (result):
            x,y,w,h = result
            pyautogui.moveTo(x,y,0.4)
        searchAndFightTagTeam()
        print("Tag arena run finish")
    else:
        print("preparing for cvc")

def allowToRanTagArena(date_str: str, date_format: str = "%Y-%m-%d") -> bool:
    """
    To prevent spending up tag arena ferylls before tournament starts
    Returns False if:
      - Today is one day before the provided date (any time), OR
      - Today is the provided date and current time is before 11:00
    Returns True otherwise.
    """
    now = datetime.now()
    target_date = datetime.strptime(date_str, date_format).date()
    day_before = target_date - timedelta(days=1)

    # Case 1: One day before target date
    if now.date() == day_before:
        print("Run tag arena: False")
        return False

    # Case 2: Same day but before 11:00
    if now.date() == target_date and now.hour < 14:
        print("Run tag arena: False")
        return False

    print("Run tag arena: True")
    return True


def searchAndFightTagTeam():
    result = errorhandling.gameReset() 
    if (result == 'skip'):
        print(f'skip clickWrap for searchAndFightTagTeam')
        return
    
    total_scrolls = 0
    while (True):
        result = errorhandling.gameReset() 
        if (result == 'skip'):
            print(f'skip clickWrap for searchAndFightTagTeam')
            return
        
        print("scanning for easy team")        
        result = pyautogui.locateOnScreen(f'./bilder/tag_arena_easyteam.PNG', grayscale = True, confidence = 0.98)
        if(result):
            shared.clickToTheRight('tag_arena_easyteam', 0.9)
            #return_result = refyllTagTeam(result)
            #if(return_result == 100):
            #    return ## Way to exit when all free battle are used up
            if (engageAndWaitTagTeam() == 100):
                return # this need to return to exit loop
            total_scrolls = 0
        else:
            # print("Arbiter was not detected")
            print("easy team was not detected")
            pyautogui.scroll(-5)
            pyautogui.scroll(-5)
            pyautogui.scroll(-5)
            pyautogui.scroll(-5)
            time.sleep(0.5)
            total_scrolls += 1
            print("total scrolls", total_scrolls)
            if(total_scrolls > 6):
                print("no team has been found.")
                exitArena()
                return 'nomore_opponents' # ONLY WAY TO EXIT
        time.sleep(1)
        # return 'battle_finish'

def refyllTagTeam():
    #x,y,w,h = attempted_battle_result # now, after update, instead of attempted team, re click on "Start 1"

    # free refyll
    result = pyautogui.locateOnScreen('./bilder/confirm_arena_tokens.PNG', grayscale = True, confidence = 0.97, minSearchTime=2)
    if (result):
        shared.clickWrap('confirm_arena_tokens')
        #pyautogui.click(x+w/2+100,y+h/2)
        shared.clickWrap('arena_classic_start')
        return
    
    result_gem = pyautogui.locateOnScreen('./bilder/tag_arena_gem_refyll.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if (result_gem):
        if(TAG_ARENA_GEM_REFYLL):
            shared.clickWrap('tag_arena_gem_refyll')
            #pyautogui.click(x+w/2+100,y+h/2)
            shared.clickWrap('arena_classic_start')
            return
        else:
            print("cross out gem refyll")
            print("Tag arena done for today")
            shared.clickWrap('tag_arena_refill_close')
            shared.clickWrap('close_arena')
            exitArena()
            return 100

def searchAndFight():
    result = errorhandling.gameReset() 
    if (result == 'skip'):
        print(f'skip clickWrap for searchAndFight')
        return

    total_scrolls = 0
    while (True):
        result = errorhandling.gameReset() 
        if (result == 'skip'):
            print(f'skip clickWrap for searchAndFight')
            return
    
        print("scanning for easy hero")        
        for x in easy_champs:
            easy_champion_detected = pyautogui.locateOnScreen(f'./bilder/{x}.PNG', grayscale = True, confidence = 0.95)
            if (easy_champion_detected):
                print("breaking for loop, champ detected")
                break # breaks for loop
        if (easy_champion_detected):
            print("Easy champ detected")
            x,y,w,h = easy_champion_detected
            pyautogui.click(x+w/2+100,y+h/2)
            #if(refyll(easy_champion_detected) == 100):
            #    return 100
            if (engageAndWait() == 100):
                return
            total_scrolls = 0
        else:
            print("easy champion was not detected")
            pyautogui.scroll(-10)
            pyautogui.scroll(-10)
            pyautogui.scroll(-10)
            pyautogui.scroll(-10)
            time.sleep(0.5)
            total_scrolls += 1
            print("total scrolls", total_scrolls)
            if(total_scrolls > 6):
                print("no opponents has been found.")
                return
        time.sleep(1)

def startOnAuto():
    not_super_raid = pyautogui.locateOnScreen(f'./bilder/arena_not_auto.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if(not_super_raid):
        shared.clickToTheLeft('arena_start_on_auto', 0.9)

def exitArena():
    shared.clickWrap('close_arena')
    shared.clickWrap('bastion')
    closeadds.closeAdds()

def refyll():
    #x,y,w,h = attempted_battle_result

    result = pyautogui.locateOnScreen('./bilder/confirm_arena_tokens.PNG', grayscale = True, confidence = 0.97, minSearchTime=2)
    if (result):
        shared.clickWrap('confirm_arena_tokens')
        #pyautogui.click(x+w/2+100,y+h/2)
        shared.clickWrap('arena_classic_start')
        return
    
    result_gem = pyautogui.locateOnScreen('./bilder/confirm_arena_gem_refyll.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if (result_gem):
        if(refyll_w_gem):
            shared.clickWrap('confirm_arena_gem_refyll 40gem')
            pyautogui.click(result_gem)
            #pyautogui.click(x+w/2+100,y+h/2)
            shared.clickWrap('arena_classic_start')
        else:
            print("cross out gem refyll")
            shared.clickWrap('tag_arena_refill_close')
            shared.clickWrap('close_arena')
            exitArena()
            return 100

def engageAndWait():
    startOnAuto()
    shared.clickWrap('arena_classic_start') # confirm to start battle
    return_result = refyll()
    if(return_result == 100):
       return 100 ## Way to exit when all free battle are used up
    shared.clickWrap('arena_classic_taptocontinue', 900)
    shared.clickWrap('arena_classic_returntoarena')

def engageAndWaitTagTeam():
    shared.clickWrap('tag_arena_start')
    return_result = refyllTagTeam()
    if(return_result == 100):
       return 100 ## Way to exit when all free battle are used up
    shared.clickWrap('tag_arena_continue', 900)
    shared.clickWrap('tag_arena_returntoarena')

if __name__ == "__main__":
    flagInstance.no_cvc = True
    classic()
    #for i in range(10):
    #    tagTeam()
    #tagTeam()
    #print("cross out gem refyll")
    #print("Tag arena done for today")
    #shared.clickWrap('tag_arena_refill_close')
    #shared.clickWrap('close_arena')
    #exitArena()
    # allowToRanTagArena("2026-02-23")