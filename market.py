import pyautogui
import shared
import time
import closeadds

def buyShards(buyChampions:bool):
    #result = pyautogui.locateOnScreen(f'./bilder/market_new.PNG', grayscale = False, confidence = 0.98)
    result = pyautogui.locateOnScreen(f'./bilder/market_new_oz_event.PNG', grayscale = False, confidence = 0.98)
    #result = pyautogui.locateOnScreen(f'./bilder/market_new_ubileum.PNG', grayscale = False, confidence = 0.98)
    #result = pyautogui.locateOnScreen(f'./bilder/market_new_halloween.PNG', grayscale = False, confidence = 0.98)
    #result = pyautogui.locateOnScreen(f'./bilder/market_new_xmas.PNG', grayscale = False, confidence = 0.98)
    if(result):
        print("market has new items")
        pyautogui.click(result)
        __buyAndScroll(buyChampions)
        shared.clickWrap('close_arena')
        closeadds.closeAdds()
    else:
        print("market has't updated yet...")

def __buyAndScroll(buyChampions:bool):
    time.sleep(2)
    __buyStufOneCycle(buyChampions)
    __shopScroll()
    __buyStufOneCycle(buyChampions)

def __buyStufOneCycle(buyChampions:bool):
    __buyGreenShards()
    time.sleep(1)
    __buyAncientShards()
    if(buyChampions):
        #time.sleep(1)
        #__buyChampions6000()
        time.sleep(1)
        __buyChampions39000()
        #time.sleep(1)
        #__buyChampions44000()
        #time.sleep(1)

def __buyGreenShards():
    __buyShardsGeneral('market_green_shard', 'get5000')

def __buyAncientShards():
    __buyShardsGeneral('market_ancient_shard','get200000')

def __buyShardsGeneral(type, get_price):
    result = pyautogui.locateAllOnScreen(f'./bilder/{type}.PNG', grayscale = True, confidence = 0.9)
    for i in result:
        x,y,w,h = i
        print(x, y, w,h)
        pyautogui.click(x, y)
        shared.clickWrap(get_price)
        time.sleep(0.6)

def __buyChampions6000():
    result = pyautogui.locateAllOnScreen('./bilder/market_6000_champ.PNG', grayscale = True, confidence = 0.92)
    for i in result:        
        x,y,w,h = i
        pyautogui.click(x+5,y+5)
        __buyWithArtifactCheck()
        time.sleep(2)

# Wainting to be tested
def __buyChampions39000():
    result = pyautogui.locateAllOnScreen('./bilder/market_uncommon_39000.PNG', grayscale = True, confidence = 0.92)
    for i in result:        
        x,y,w,h = i
        pyautogui.click(x+5,y+5)
        __buyWithArtifactCheck()
        time.sleep(2)

# Wainting to be tested
def __buyChampions44000():
    result = pyautogui.locateAllOnScreen('./bilder/market_uncommon_44000.PNG', grayscale = True, confidence = 0.9)
    # wha wha whaaaaa, the array seem to save multiple time one location and attept to purchase it again
    for i in result:        
        x,y,w,h = i
        pyautogui.click(x+5,y+5)
        __buyWithArtifactCheck()
        time.sleep(2)

def __buyChampions49000():
    result = pyautogui.locateAllOnScreen('./bilder/market_uncommon_49000.PNG', grayscale = True, confidence = 0.87)
    for i in result:        
        x,y,w,h = i
        pyautogui.click(x+5,y+5)
        __buyWithArtifactCheck()
        time.sleep(2)

def __buyWithArtifactCheck():
    # MAKE A CHECK IF BUYING A CHAMP - NOT AN ARTIFACT
    isArtifact = pyautogui.locateOnScreen('./bilder/market_uncommon_is_artifact.PNG', grayscale = True, confidence = 0.87, minSearchTime=0.7)
    if (isArtifact):
        pyautogui.click(isArtifact)
    else:
        # To prevent restat when sometimes fails to find, because it hasnt entered CHAMPION VIEW/BUY screen.
        result = pyautogui.locateAllOnScreen('./bilder/markeg_champ_get.PNG', grayscale = True, confidence = 0.87)
        if(result):
            shared.clickWrap('markeg_champ_get')
            shared.clickWrap('close_arena')

def __buyChampions8000():
    result = pyautogui.locateAllOnScreen('./bilder/8000.PNG', grayscale = True, confidence = 0.9)
    for i in result:        
        x,y,w,h = i
        pyautogui.click(x+5,y+5)
        shared.clickWrap('8000get')
        shared.clickWrap('close_arena')
        time.sleep(2)

def __buyChampions10000():
    result = pyautogui.locateAllOnScreen('./bilder/market_10000_champ.PNG', grayscale = True, confidence = 0.9)
    for i in result:        
        x,y,w,h = i
        pyautogui.click(x+5,y+5)
        shared.clickWrap('markeg_champ_get')
        shared.clickWrap('close_arena')
        time.sleep(2)

def __buyChampions():
    champs_to_buy = ['market_6000', 'market_8000'] # disse alle er uncommon champions, better to target 'uncommon'
    for champs in champs_to_buy:
        print("champs ", champs)
        for i in range(10): #expect to buy up to 10 champs of one kind
            print("i ", i)
            result = pyautogui.locateOnScreen(f'./bilder/{champs}_champ.PNG', minSearchTime=0.6, grayscale = False, confidence = 0.9)
            if (result):
                pyautogui.click(result)
                shared.clickWrap('markeg_champ_get')
                shared.clickWrap('close_arena')
            #time.sleep(0.3)

def __buyShards():
    shards_to_buy = ['market_mystery'] #dette kan kjøpe artifakt som koster 200k, better to target shard picture
    for shard in shards_to_buy:
        for i in range(10): #expect to buy up to 10 champs of one kind
            result = pyautogui.locateOnScreen(f'./bilder/{shard}_shard.PNG', grayscale = False, confidence = 0.9)
            print(result)
            if (result):
                pyautogui.click(result)
                shared.clickWrap('market_get_shard')
            time.sleep(0.3)          

def __shopScroll():
    time.sleep(2)
    marke_bazar_button = pyautogui.locateOnScreen(f'./bilder/marke_bazar_button.PNG', grayscale = False, confidence = 0.9)
    if(marke_bazar_button):
        x,y,w,h = marke_bazar_button
        pyautogui.moveTo(x+300, y)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)
    pyautogui.scroll(5)


if __name__ == "__main__":
    #__buyAncientShards()
    #buyShards()
    #time.sleep(2)
    #__buyGreenShards()
    #__buyAncientShards()
    #__buyChampions39000()
    __buyChampions44000()
    #__buyChampions49000()
    #__buyAndScroll()

