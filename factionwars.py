import pyautogui
import shared
import time
import closeadds
from errorhandling import errorManager
from flags import flagInstance
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional

class Faction(str, Enum):
    BANNER_LORD = "banner_lord" 
    BARBARIAN = "barbarian" 
    DARK_ELF = "dark_elf"
    DEMON_SPAWN = "demon_spawn" 
    DWARF = "dwarf"
    HIGH_ELF = "high_elf"
    KNIGHTS_REVENANT = "knights_revenant"
    LIZARDMEN = "lizardmen"
    OGRYN = "ogryn"
    ORC = "orc"
    SACRED_ORDER = "sacred_order"
    SKINWALKERS = "skinwalkers" 
    SHADOWKIN = "shadowkin"
    SYLVAN_WATCHERS = "sylvan_watchers"
    UNDEAD_HORDE = "undead_horde"

@dataclass
class FactionSettings:
    auto: bool
    tetsuya: bool
    stage: int
    tetsuya_coord: Optional[int] = None
    target_boss: Optional[bool] = None

# demon_spawn-stage-21
# fw_dark_elf_crypt_round2
FW_HARD_SETTINGS: Dict[Faction, FactionSettings] = {
    Faction.BANNER_LORD: FactionSettings(True, False, 21, 150, True), # - new ok
    Faction.BARBARIAN: FactionSettings(True, True, 21, 150), # new round 2 ss - ok
    Faction.DARK_ELF: FactionSettings(True, True, 21, 200), # new ok
    Faction.DEMON_SPAWN: FactionSettings(True, False, 21), # na
    Faction.DWARF: FactionSettings(True, False, 21), # na
    Faction.HIGH_ELF: FactionSettings(True, True, 21, 150), # new round 2 - ok
    Faction.KNIGHTS_REVENANT: FactionSettings(True, False, 21), # na
    Faction.LIZARDMEN: FactionSettings(True, True, 21, 200), # - new ok
    Faction.OGRYN: FactionSettings(True, True, 21, 200), # new round 2 - ok
    Faction.ORC: FactionSettings(True, False, 21), # na
    Faction.SACRED_ORDER: FactionSettings(True, True, 21, 150, True), # new round 2 ok, new round 3 - ok
    Faction.SKINWALKERS: FactionSettings(True, False, 21), # na
    Faction.SHADOWKIN: FactionSettings(True, True, 21, 470), # - new ok
    Faction.SYLVAN_WATCHERS: FactionSettings(True, False, 21), # na
    Faction.UNDEAD_HORDE: FactionSettings(True, True, 21, 200), # - new ok
}

def getFactionStageFilename(faction: Faction) -> str:
    settings: FactionSettings = FW_HARD_SETTINGS[faction]
    return f"{faction}-stage-{settings.stage}"

def getFactionCryptFilename(faction: Faction) -> str:
    return f"factionwars_{faction}_crypt"

def getTetsuyaRoundFilename(faction: Faction) -> str:
    filename = f"fw_{faction}_crypt_round2"
    print ("getTetsuyaRoundFilename filename ", filename)
    return filename

def getBossRoundFilename(faction: Faction) -> str:
    filename = f"fw_{faction}_crypt_round3"
    print ("getBossRoundFilename filename ", filename)
    return filename

crypts_today: List[Faction] = []

middle_section: List[Faction] = [
    Faction.BARBARIAN,
    Faction.DEMON_SPAWN,
    Faction.OGRYN,
    Faction.HIGH_ELF,
    Faction.DARK_ELF,
    Faction.ORC,
    Faction.SACRED_ORDER,
    Faction.BANNER_LORD    
    ]

left_section: List[Faction] = [
    Faction.KNIGHTS_REVENANT,
    Faction.LIZARDMEN,
    Faction.SKINWALKERS,
    Faction.UNDEAD_HORDE    ]

right_section: List[Faction] = [
    Faction.SHADOWKIN,
    Faction.DWARF,
    Faction.SYLVAN_WATCHERS    ]

sections: List[List[Faction]] = [middle_section, left_section, right_section]
# sections: List[List[Faction]] = [middle_section]

def main():
    if(flagInstance.no_cvc):
        # 1. collect extra keys today - save to file if collected.
        if (not collectKeys(4)):
            return
        # 2. run if collected. Save to file if did run.
        if (not shared.readyToRun_NoSave('factionwars')):
            return

        _initFaction()
        _findCryptAndFight()
        shared.clickWrap('bastion')
        shared.saveRun('factionwars')
        closeadds.closeAdds()
    else:
        print("preparing for cvc")

def _findCryptAndFight():
    global crypts_today
    for section in sections:
        _dragTo(section)
        _scanCryptsAndAppend(section)
        if len(crypts_today) > 0:
            _doAllFightsIn(section)
        else:
            shared.clickWrap('close_arena')
            shared.clickWrap('factionwars')
        crypts_today = []

# will fight all crypt in provided section
def _doAllFightsIn(current_section: List[Faction]):
    print("cur section ", current_section)
    print("crypts_today ", crypts_today)
    navigate_back_to_section = False
    for crypt in crypts_today: 
        if navigate_back_to_section == True: #never True on first run
            print(f'Navigating back to {current_section} for second crypt')
            _dragTo(current_section)
        print("crypt " , crypt)
        print("auto ", FW_HARD_SETTINGS[crypt].auto)
        print("stage ", FW_HARD_SETTINGS[crypt].stage)
        if(FW_HARD_SETTINGS[crypt].auto):
            shared.clickWrap(getFactionCryptFilename(crypt))
            crypt_stage_filename = getFactionStageFilename(crypt)
            shared.clickToTheRight(crypt_stage_filename)
            superRaids()
            shared.clickWrap('start_factionwars')

            print("current section ", current_section)
            # special cases
            if current_section == Faction.SHADOWKIN:
                print("Shadowkin detected")


            # but if team dies in first round - script will wait for Tetsuya round for 25 minutes. Only then it will check if defeat.
            monitorTetsuya(crypt)
            monitorBoss(crypt)
            for i in range(3):
                if (repeatIfDefeated()):
                    monitorTetsuya(crypt)
                    monitorBoss(crypt)

            shared.clickWrap('map', 2000)

            if len(crypts_today) > 1:
                navigate_back_to_section = True

def superRaids():
    not_super_raid = pyautogui.locateOnScreen(f'./bilder/not_super_raids.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
    if(not_super_raid):
        shared.clickToTheLeft('fw_crypt_superraids', 0.9)

def monitorTetsuya(crypt: Faction):
    y_correction = 230 # minus 50 to offsett for UI updates
    if (FW_HARD_SETTINGS[crypt] == FW_HARD_SETTINGS[Faction.SHADOWKIN] or 
        FW_HARD_SETTINGS[crypt] == FW_HARD_SETTINGS[Faction.BANNER_LORD]):
        print("Shadowkin or Bannerlord detected")
        y_correction = 170 # did minus 50 here too

    if (FW_HARD_SETTINGS[crypt].tetsuya):
        print("monitoring Tetsuya")
        tetsuya = pyautogui.locateOnScreen(f'./bilder/{getTetsuyaRoundFilename(crypt)}.PNG', grayscale = True, confidence = 0.96, minSearchTime=1500)
        if (tetsuya):
            x,y,w,h = tetsuya
            left = x-FW_HARD_SETTINGS[crypt].tetsuya_coord
            top = y+y_correction
            print("Tetsuya detected ", left, top)
            pyautogui.click(left, top)

def monitorBoss(crypt: Faction):
    if (FW_HARD_SETTINGS[crypt].target_boss):
        print("monitoring round 3")
        boss = pyautogui.locateOnScreen(f'./bilder/{getBossRoundFilename(crypt)}.PNG', grayscale = True, confidence = 0.96, minSearchTime=1500)
        if (boss):
            x,y,w,h = boss
            left = x-300
            top = y+200
            print("Boss round detected ", left, top)
            pyautogui.click(left, top)

def repeatIfDefeated():
    battle_ended = pyautogui.locateOnScreen(f'./bilder/bastion.PNG', grayscale = True, confidence = 0.96, minSearchTime=3000)
    if(battle_ended):
        was_defeated = pyautogui.locateOnScreen(f'./bilder/fw_defeat.PNG', grayscale = True, confidence = 0.96, minSearchTime=3)
        if (was_defeated):
            shared.clickWrap('fw_replay')
            return True
    return False

# append to crypts_today if found a crypt
def _scanCryptsAndAppend(section:List[Faction]):
    time.sleep(2)
    print('scanning crypts')
    for crypt in section:
        print("searching ", crypt)
        crypt_found = pyautogui.locateOnScreen(f'./bilder/{getFactionCryptFilename(crypt)}.PNG', grayscale = True, confidence = 0.9, minSearchTime=3)
        if(crypt_found):
            crypts_today.append(crypt)
    print("crypts_today ", crypts_today)

def _dragTo(section:list):
    if section == left_section :
        _dragLeft()
    if section == right_section:
        _dragRight()
       
#drag to right from middle section
def _dragRight():
    print("dragRight")
    result = pyautogui.locateOnScreen('./bilder/doom_tower_drag_right.PNG', grayscale = True, confidence = 0.88, minSearchTime=200)
    if(result):
        pyautogui.mouseDown(result)
        x,y,w,h = result
        pyautogui.moveTo(x-600, y, 1)
        pyautogui.mouseUp()
        print("done")
        return
    else:
        errorManager.error_detected = True

#drag to left from middle section
def _dragLeft():
    print("dragLeft")
    result = pyautogui.locateOnScreen('./bilder/doom_tower_drag_left.PNG', grayscale = True, confidence = 0.88, minSearchTime=200)
    if(result):
        pyautogui.mouseDown(result)
        x,y,w,h = result
        pyautogui.moveTo(x+800, y, 1)
        pyautogui.mouseUp()
        print("done")
        return
    else:
        errorManager.error_detected = True
        
def _initFaction():
    shared.clickWrap('battle')
    shared.clickWrap('factionwars')

# This function does return True if collected keys. Use return value to write to file.
def collectKeys(collectAtClock:int):
    already_collected_today = shared.didRunToday('collectkeys')
    if (already_collected_today):
        return True

    readyToRun = shared.readyToRun_NoSave('collectkeys', collectAtClock)
    if (not readyToRun):
        return False

    shared.clickWrap('quests')
    shared.clickWrap('advanced')
    ready_to_claim = pyautogui.locateOnScreen('./bilder/ready_to_claim_fw_keys.PNG', grayscale = True, confidence = 0.88, minSearchTime=5)
    if(ready_to_claim):
        shared.clickWrap('ready_to_claim_fw_keys')
        shared.saveRun('collectkeys')
        shared.clickWrap('close_arena')
        closeadds.closeAdds()
        return True
    else:
        shared.clickWrap('close_arena')
        closeadds.closeAdds()
        return False


if __name__ == "__main__":
    flagInstance.no_cvc = True
    # _initFaction()
    # _findCryptAndFight()
    # shared.clickWrap('bastion')
    # shared.saveRun('factionwars')
    # closeadds.closeAdds()
    crypts_today.append(Faction.BANNER_LORD)
    _doAllFightsIn([Faction.BANNER_LORD])

