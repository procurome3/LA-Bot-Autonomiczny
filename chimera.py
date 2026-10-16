import shared
import pyautogui
import closeadds
from enum import Enum
from datetime import datetime


class Mode(Enum):
    TANK = "TANK"
    PUSH = "PUSH"

class PresetName(Enum):
    BEFORE = "chimera_preset"
    AFTER = "primary"

championsBeforeTank = [
    'Elva autumnborn',
    #'Kaja',
    'Aphidus',
    'Nekmo',
    'Klaazag'
]

championsBeforePush = [
    'Elva autumnborn',
    #'Kaja',
    'Marius',
    'Nekmo',
    'Klaazag'
]

# After chimera run - regear all champions back to gear preset with name 'Primary'
championsAfter = [
    'Wukong',
    'Thor',
    'Tholin',
    'Shamael',
    'Herakletes',
    'Razelvarg',
    'Padraig',
    'Lydia',
    'Tolf',
    'Mikage',
    'Glaicad',
    'Noelle',
    'Brogni',
    'Scyl',
    'Armanz',
    'Staltus',
    'Elva autumnborn',
    'Marius', # different list after tank week
    'Nekmo',
    # 'KLaazag' # not gearing back because he doesn't do anything else
]

rotation_1_void_force = [
    # 'Wukong',
    # 'Thor',
    # 'Titus',
    # 'Seer',
    'Galkut',
    'Ugir',
    'Tholin',
    'Hegemon',
    'Daihatsu',
    'Gala',
    'Elva autumnborn',
    'Armanz',
    'Padraig',
    'Fabian',
    'Bivald',
    'Esme'
]

championsAfterTank = [
    'Gnut',
    'Titus',
    'Hegemon',
    'Daithi',
    'Aphidus'
]

selection_map = {
    Mode.PUSH: (championsBeforePush, championsAfter),
    Mode.TANK: (championsBeforeTank, championsAfter)
}

difficulty_to_run = ['chimera_unm', 'chimera_nm']

def main(mode: Mode):
    if(shared.readyToRun('chimera', 6) and datetime.now().weekday() == 6):
        gearForBattle(mode)
        initChimera()
        initFight(mode, 'chimera_unm')
        initFight(mode, 'chimera_nm')
        shared.clickWrap('close_arena')
        shared.clickWrap('bastion')
        closeadds.closeAdds()
        gearAfterBattle(mode)
    else:
        print("Chimera DONE this week")

def initChimera():
    shared.clickWrap('battle')
    shared.clickWrap('clan')
    shared.clickWrap('chimera')

def initFight(mode: Mode, difficulty: str):
    shared.clickWrap('chimera_easy')
    scrollToBottom()
    shared.clickWrap(difficulty)
    # claim rewards (most likely I claim these myself)
    shared.clickWrap('chimera_battle')
    selectTeam(mode)
    shared.clickWrap('chimera_start_battle')

    # why? - am I gonna check damage? - if not, skip this and just wait for "keep result"
    # battle_ended = pyautogui.locateOnScreen(f'./bilder/chimera_result_screen.PNG', grayscale = True, confidence = 0.96, minSearchTime=3600)

    # can check if did all 65 turns: 
    # chimera_turns_65_65
    shared.clickWrap('chimera_keep_result', 3600)
    shared.clickWrap('chimera_exit')

def scrollToBottom():
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)
    pyautogui.scroll(-5)

def selectTeam(mode: Mode):
    shared.clickWrap('chimera_team_setup') # button has blue color if team is selected
    if (mode == Mode.PUSH):
        team_not_checked = pyautogui.locateOnScreen(f'./bilder/chimera_push_team_empty.PNG', grayscale = True, confidence = 0.96, minSearchTime=3)
        if(team_not_checked):
            shared.clickToTheLeft('chimera_push_team', 0.95)
    else:
        team_not_checked = pyautogui.locateOnScreen(f'./bilder/chimera_tank_team_empty.PNG', grayscale = True, confidence = 0.96, minSearchTime=3)
        if(team_not_checked):
            shared.clickToTheLeft('chimera_tank_team', 0.95)
    shared.clickWrap('chimera_select_team_end')

def gearForBattle(mode: Mode):
    initRegear()
    print("mode ", mode)
    champBeforeFight, champAfterFight = selection_map[mode]
    loopChampions(champBeforeFight, PresetName.BEFORE)
    finilizeRegear()

def gearAfterBattle(mode: Mode):
    initRegear()
    champBeforeFight, champAfterFight = selection_map[mode]
    new_list = champAfterFight.copy()
    if mode == Mode.TANK:
        new_list.extend(championsAfterTank)
    
    loopChampions(new_list, PresetName.AFTER)
    finilizeRegear()

def loopChampions(champList, preset: PresetName):
    for i, champ in enumerate(champList):
        shared.clickWrap('search_button')
        if i == 0:
            shared.clickToTheLeft('include_master_vault')
        shared.clickBelow('champion_filter')
        pyautogui.write(champ, interval=0.05)
        shared.clickBelow('by_rank')
        shared.clickWrap('hide_button')
        shared.clickWrapWithSkip('to_collection', 2)
        shared.clickBelow('gear_button', 30)
        shared.clickWrap('gear_filter')
        shared.clickWrap('preset_manager_button')
        shared.clickAboveAndTotheright(preset.value, 170, -35)
        shared.clickWrap('accessories')
        shared.clickAboveAndTotheright(preset.value, 170, -35)
        shared.clickWrap('equip')
        shared.clickWrapWithSkip('continue')
        shared.clickWrap('end_champion')
        print(f'done regearing {champ}')

def locatePrimary():
    print("")

def initRegear():
    shared.clickWrap('champions')

def finilizeRegear():
    shared.clickWrap('close_arena')
    closeadds.closeAdds()

if __name__ == "__main__":
    #main(Mode.PUSH)
    #gerForBattle(Mode.TANK) - seem to work
    #initChimera() - ok
    #initFight(Mode.TANK, 'chimera_unm') - ok
    # shared.clickWrap('chimera_keep_result', 3600)
    # shared.clickWrap('chimera_exit')
    # initFight(Mode.TANK, 'chimera_nm') - ok
    #gearAfterBattle(Mode.TANK)
    loopChampions(rotation_1_void_force, PresetName.AFTER)
