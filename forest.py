import pyautogui
import shared


def main():
    # start looking for uncovered tiles 
    # do it in a for-loop ?
    result = pyautogui.locateOnScreen(f'./bilder/forest_uncovered_tile.PNG', grayscale = False, confidence = 0.85)
    if (result):
        pyautogui.click(result)
        # pyautogui.moveTo(result)
    
    # if no uncovered tiles have been found, two type of tiles can be found:
    # V1. common           - pentagonal frame
    # V2. wave tile        - a bigger pentagonal frame
    # V3. boss tile with   - a bigger pentagonal frame with 3 rewards
    # V4. chest tile       - regular hexagon frame
    # V5. Phrygius boss    - special (icy) frame

    # some frames have scull attached at bottom
    # boss tiles V3 - can be with or without scull. The one with scull means boss has blessing


    # IF tile can be accessed - frame is always has light, thick rim

    # how to spot these?
    # they have a frame - 

    # when V1 is defeated, view is centered to this tile


def setupDecks():
    if shared.clickWrapWithSkip('forest_setup_decks'):
        shared.clickWrap('forest_deck_set')
        shared.clickWrap('forest_deck_confirm')

if __name__ == "__main__":
    main()
    #setupDecks()
