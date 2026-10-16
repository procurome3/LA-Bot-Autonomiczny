import shared
import pyautogui
import closeadds
from chimera import Mode
from enum import Enum


class PresetName(Enum):
    BEFORE = "chimera_preset"
    AFTER = "primary"

# TODO: script that gear up for chimera fight, runs both battles on auto, regears back to Primary !!!
# schedule chimera run on saturday/sunday
# provide input ( TANK or PUSH )

# ther todos:
# - cvc calendar
# - nice graph for chimera estimates ( should include number of error readings)
# - estimate hydra clash

# Before chimera run - gear up chimera team
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
    'Nekmo'
]

championsAfterTank = [
    'Gnut',
    'Titus',
    'Hegemon',
    'Daithi'
]

selection_map = {
    Mode.PUSH: (championsBeforePush, championsAfter),
    Mode.TANK: (championsBeforeTank, championsAfter)
}

def gerForBattle(mode: Mode):
    initRegear()
    print("mode ", mode)
    champBeforeFight, champAfterFight = selection_map[mode]
    loopChampions(champBeforeFight, PresetName.BEFORE)
    finilizeRegear()

def gearAfterBattle(mode: Mode):
    initRegear()
    champBeforeFight, champAfterFight = selection_map[mode]
    loopChampions(champAfterFight, PresetName.AFTER)
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
        shared.clickAboveAndTotheright(preset, 170, -35)
        shared.clickWrap('accessories')
        shared.clickAboveAndTotheright(preset, 170, -35)
        shared.clickWrap('equip')
        shared.clickWrap('continue')
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
    print()
    # shared.clickWrap('search_button')
    # now what
    # right most 'cose_arena' exit to bastion

