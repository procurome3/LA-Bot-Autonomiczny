import pyautogui
import time
from datetime import datetime, timedelta
import shared
import closeadds
import errorhandling
from errorhandling import errorManager
import cv2
import numpy as np
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
from pprint import pprint
import json
import requests
from PIL import Image
import matplotlib.pyplot as plt


TESSERACT_CONFIG_CHIMERA_DAMAGE = r'-c tessedit_char_whitelist=0123456789.BM --psm 6'

data = {} #dictionary containing "clan_name"=[123, 234, 345, ...] all member damage

# 1. on chimera clash window locate (i) icon and click it
this_clan = []
clan_name = "" #extract clan name with tesseract

def main():
    if (errorhandling.gameReset()  == 'skip'):
        return
    file_path = f'./textfiles/chimeraclash.txt'
    print("starting chimera clash extraction", file_path)
    ready_to_run: bool = __ready_to_run_clash(file_path)
    if ready_to_run:
    #if True:
        _init()

        # for loop here mb for all 5 clans
        # if position of clans will change during script execution, wrong clan will be estimated.
        # better approach will be to save 5 clan names first, then for each clan name extract data

        # but start simple first
        clans_info = pyautogui.locateAllOnScreen('./bilder/chimera_i.PNG', grayscale=True, confidence=0.8)
        info_list = list(clans_info)
        print(info_list)
        #print("length: ", len(info_list))

        for index, item in enumerate(info_list, start=1):
            x, y, w, h = item
            print("item #: ", index, "coordinates: ", x, y)
            clan_dmg = []
            clan_name = getClanName(x, y)
            print(clan_name)
            pyautogui.click(x, y)

            getFirst25players(clan_dmg)        
            getLast5Players(clan_dmg)
            # there is a problem if clan has less than 26 members, can't scroll to player 25
            
            data[clan_name.strip()] = round(sum(clan_dmg), 2)
            print("clan_dmg ", clan_dmg)
            target = pyautogui.locateOnScreen('./bilder/chimera_close_clan_info.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
            chimera_clash = pyautogui.locateOnScreen('./bilder/chimera_clash.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
            if target and not chimera_clash:
                pyautogui.click(target)
            else:
                print("failed chimera_close_clan_info")
            time.sleep(3)
        pprint(data) # TODO: save to file # try to send to discord
        __write_execution_status(file_path)
        __clash_data(data)
        sendToDiscord(data)
        # write data to chimeraclashdata.txt # then try to send it to discord
        _finilize()
    else:
        print("execution status / ready to run ", ready_to_run)

def _init():
    shared.clickWrap('battle')
    shared.clickWrap('clan')
    shared.clickWrap('chimera_clanboss')

    # clicking chimera clash -> battle - ends clash (no need to press the button)
    # should click back and forth to be sure 
    shared.clickWrapWithSkip('chimera_clash_end')
    shared.clickWrapWithSkip('chimera_claim_chest')
    shared.clickWrapWithSkip('chimera_claim_chest_confirm')
    time.sleep(1)
    shared.clickWrapWithSkip('chimera_clash_battles')
    time.sleep(1)
    shared.clickWrapWithSkip('chimera_clash_end')
    time.sleep(1)


def _finilize():
    shared.clickWrap('close_arena')
    shared.clickWrap('bastion')
    closeadds.closeAdds()


def __write_execution_status(file_path):
    current_datetime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with open(file_path, 'w') as file:
        file.write(current_datetime)

def __clash_data(data):
    pretty_data = json.dumps(data, indent=4)
    current_datetime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    data_to_file = current_datetime + "\n" + pretty_data
    print(data_to_file)
    with open("textfiles/chdata.txt", 'w') as file:
        file.write(data_to_file)

def __ready_to_run_clash(file_path, current_time=None):
    try:
        with open(file_path, 'r') as file:
            execution_datetime_str = file.read().strip()
            executed_last_time = datetime.strptime(execution_datetime_str, "%d.%m.%Y %H:%M:%S")
            current_datetime = current_time or datetime.now()

            # Check if it’s Friday, after 15:00, and hasn’t run today
            did_not_run_today = executed_last_time.date() != current_datetime.date()
            is_friday = current_datetime.weekday() == 4  # Monday=0 ... Friday=4
            is_after_15 = current_datetime.hour >= 14

            if did_not_run_today and is_friday and is_after_15:
                print("Ready to run Chimera clash numbers")
                return True
            else:
                print("Already done for this week or not time yet")
                return False
    except FileNotFoundError:
        return False


def getFirst25players(clan_dmg):
    for player in range(25):
        if try_to_open_top_player() == 0: #if fail to open top player - it still stay in Clan performance window
            print("getFirst25players returns")
            return
        player_damage = getPlayerChimeraDamage(player) # ok, this can return 0 if its actually is in player info, but failed to read number . BUT ALSO if not detected player info
        if player_damage == 99999:
            return
        clan_dmg.append(player_damage)
        closePlayer()
        scrollToNextPlayer()
        # if clan has 29 players, can't scroll to player 25 
        # check if player info was not open - assume is has less than 30. run last 5 people

def getLast5Players(clan_dmg):
    for i in range(5):
        if open_player_at(i) == 0:
            return
        player_damage = getPlayerChimeraDamage(25+i)
        if player_damage == 99999:
            return
        clan_dmg.append(player_damage)
        #if player_damage > 0: # why dmg > 0 only then close? I had dmg 0 and not closing window cause script to fail on next step
        closePlayer()


def mooveToScrollPosition():
    target = pyautogui.locateOnScreen('./bilder/chimera_clan_performance.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
    if target:
        x,y,w,h = target
        left = x-150
        top = y+200
        pyautogui.moveTo(left, top)
    else:
        print("failed mooveToScrollPosition()")

def scrollToNextPlayer():
    target = pyautogui.locateOnScreen('./bilder/chimera_clan_performance.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
    if target:
        x,y,w,h = target
        left = x+300
        top = y+200
        pyautogui.moveTo(left, top)
        pyautogui.mouseDown()
        pyautogui.moveTo(left,top-132, duration=0.5) # might need to add 1 pixel on every 4th drag
        time.sleep(0.5)
        pyautogui.mouseUp()
        time.sleep(1)
    else:
        print("failed scrollToNextPlayer()")

def getClanName(x, y):
    left = x-455
    top = y-10
    width = 200
    height = 20
    screenshot = pyautogui.screenshot(region=(left, top, width, height))
    final_img = _prepareImageForTesseract(screenshot)
    chimera_dmg_text = pytesseract.image_to_string(final_img)
    return chimera_dmg_text

    #pyautogui.click(first_match)

def _prepareImageForTesseract(img):
    img_np = np.array(img)
    gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
    scale_percent = 400  # percent of original size (e.g., 200% = double size)
    width = int(gray.shape[1] * scale_percent / 100)
    height = int(gray.shape[0] * scale_percent / 100)
    dim = (width, height)
    resized = cv2.resize(gray, dim, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(resized, 105, 250, cv2.THRESH_BINARY)
    return Image.fromarray(thresh)

def _prepareNumberImageForTesseract(screenshot):
        img_np = np.array(screenshot)
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        scale_percent = 1000  # percent of original size (e.g., 200% = double size)
        width = int(gray.shape[1] * scale_percent / 100)
        height = int(gray.shape[0] * scale_percent / 100)
        dim = (width, height)
        resized = cv2.resize(gray, dim, interpolation=cv2.INTER_LANCZOS4)
        _, thresh = cv2.threshold(resized, 108, 255, cv2.THRESH_BINARY)
        # 60, 200 - sword is visible but is ignored
        # 80, 200 - sword is not visible, tale og g is visible = wrong reading
        # 50, 200-> 240 wrong reading
        # 70, 250 - sword visible - correct reading
        # 100, 255 - 100% correct reading
        # 108, 255 - was better for certain situations
        # INTER_LINEAR - wrong reading
        # INTER_CUBIC - correct reading
        # INTER_LANCZOS4 - correct reading
        # resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU - 80% correct reading
        # resized, 70, 255, cv2.THRESH_BINARY - 50% correct reading
        # adaptiveTreshhold - wrong reading

        final_img = Image.fromarray(thresh)
        #final_img.show()
        #screenshot.show()
        return final_img

def open_player_at(index):
    target = pyautogui.locateOnScreen('./bilder/chimera_clan_performance.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
    if target:
        x,y,w,h = target
        left = x-150
        top = y+200+index*120
        pyautogui.moveTo(left, top)
        pyautogui.click(left, top)
    else:
        print("failed open_player_at()")

def try_to_open_top_player():
    target = pyautogui.locateOnScreen('./bilder/chimera_clan_performance.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
    if target:
        x,y,w,h = target
        left = x-150
        top = y+150
        _click_and_verify(left, top)
    else:
        print("failed to locate chimera_clan_performance")
        return 0
    
def _click_and_verify(left, top, retries=3):
    for attempt in range(retries):
        pyautogui.click(left, top)
        player_info = pyautogui.locateOnScreen('./bilder/chimera_cog.PNG', grayscale=True, confidence=0.8, minSearchTime=3)
        if player_info:
            return 1
        print(f"Retry {attempt+1}/{retries} failed, trying again...")
    print("❌ Failed to open player window after retries.")
    return 0

def getPlayerChimeraDamage(index):
    index = index + 1
    player_info = pyautogui.locateOnScreen('./bilder/chimera_cog.PNG', grayscale=True, confidence=0.8, minSearchTime=3)
    if player_info:
        x,y,w,h = player_info

        left = x+445
        top = y+386 # because of stupid plarium UI, some numbers are 7 pixel above at 380. But then lower numbers wont be read.
        width = 55
        height = 13

        screenshot = pyautogui.screenshot(region=(left, top, width, height))
        final_img = _prepareNumberImageForTesseract(screenshot)

        # 4. extract numbers (and convert B to M)
        chimera_dmg_text = pytesseract.image_to_string(final_img, config=TESSERACT_CONFIG_CHIMERA_DAMAGE)
        #print("text extracted: ", chimera_dmg_text)

        converted = _convert_to_millions(chimera_dmg_text)
        print("player ", index, " dmg ", converted)

        if(converted == 0):
            top = top - 7
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            final_img = _prepareNumberImageForTesseract(screenshot)
            chimera_dmg_text = pytesseract.image_to_string(final_img, config=TESSERACT_CONFIG_CHIMERA_DAMAGE)
            converted = _convert_to_millions(chimera_dmg_text)
            print("player ", index, " second reading dmg", converted)

        if (converted > 4300):
            first_three = int(str(converted)[:3])
            print("player ", index, " normilized dmg ", first_three)
            return first_three
        
        return converted
    else:
        print("failed to locate player info")
        return 99999

def closePlayer():
    player_info = pyautogui.locateOnScreen('./bilder/chimera_close_player.PNG', grayscale=True, confidence=0.8, minSearchTime=5)
    pyautogui.click(player_info)


""" def _convert_to_millions(value: str):
    val = value.strip()
    if val.endswith("M"):
        num = float(val[:-1])
        return round(num, 2)
    elif val.endswith("B"):
        num = float(val[:-1]) * 1000  # convert billions to millions
        return round(num, 2)
    else:
        # No suffix, just add as is
        return round(float(val), 2) """

def _convert_to_millions(value: str):
    if not value or not isinstance(value, str):
        return 0

    val = value.strip().upper()  # normalize casing and strip spaces
    if not val:
        return 0

    try:
        if val.endswith("M"):
            num_str = val[:-1].strip()
            return round(float(num_str), 2) if num_str else 0
        elif val.endswith("B"):
            num_str = val[:-1].strip()
            return round(float(num_str) * 1000, 2) if num_str else 0
        else:
            return round(float(val), 2)
    except ValueError:
        return 0  # or raise an error/log a warning


def sendToDiscord(clan_data):
    webhook_url ="https://discord.com/api/webhooks/1409465055325585468/nvnhBkwoV_wrDmWmmK-XuG8zVEd-8AmMVyQfsoOdWwj3Utdpr9gnv_oH8cCh2FFmXV8F"

    # 1️⃣ Sort data from largest to smallest
    sorted_data = dict(sorted(clan_data.items(), key=lambda x: x[1], reverse=True))

    names = list(sorted_data.keys())
    values = list(sorted_data.values())

    # 2️⃣ Create horizontal bar chart
    plt.figure(figsize=(10,2))
    plt.barh(names, values)

    # largest on top
    plt.gca().invert_yaxis()

    # plt.title("Clan Scores")
    # plt.xlabel("Score")
    plt.yticks(fontsize=14)

    # 3️⃣ Add score labels next to bars
    for i, v in enumerate(values):
        plt.text(v, i, f" {v:,.0f}", va="center")

    plt.tight_layout()

    # 4️⃣ Save chart
    chart_file = "clan_scores.png"
    plt.savefig(chart_file)
    plt.close()

    # 5️⃣ Send image to Discord webhook
    today = datetime.now().strftime("%d %b %Y")
    with open(chart_file, "rb") as f:
        response = requests.post(
            webhook_url,
            files={"file": ("clan_scores.png", f, "image/png")},
            data={"content": f"Chimera clash — {today}"}
        )

    # # 6️⃣ Debug result
    if response.status_code in (200, 204):
        print("Graph sent successfully!")
    else:
        print(f"Failed: {response.status_code}, {response.text}")

def __testOneClan():
    clan_dmg = []

    getFirst25players(clan_dmg)        
    getLast5Players(clan_dmg)
    # there is a problem if clan has less than 26 members, can't scroll to player 25
     
    print("clan_dmg ", round(sum(clan_dmg), 2))

"""
todo:
1 - convert all code to function like in other files - to easy test each function separated

after clicking (i) - extract clan name
use that name as key for list of damage numbers


"""


if __name__ == "__main__":
    main()
    #scrollToNextPlayer()
    #__testOneClan()
    #for i in range(20):
    #    getPlayerChimeraDamage(1)
    #getPlayerChimeraDamage(1)
    #sendToDiscord()
    #getPlayerChimeraDamage(1)

#TODO:
# - count failed reads per clan