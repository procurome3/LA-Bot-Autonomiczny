import os
import time
import datetime

# Jak często ponownie sprawdzać dostępność zadań/Live Areny.
CHECK_INTERVAL_SECONDS = 60

# Włączenie obsługi kolorów ANSI w konsoli Windows
os.system('')

# Wypisanie tekstu w kursywie, pogrubionym/większym oraz jasnym fioletowym kolorze (95) z trzema spacjami na początku
print("   \033[1;3;95mHELLO WORLD!\033[0m")

import farmcampain
import clanboss
import opengame
import collectgems
import closeadds
import dailylogin
import dailyquests
import dungeon
import doomtower
import arena
import guardianring
import market
import factionwars
import arenalive
from flags import flagInstance
import errorhandling
from errorhandling import errorManager, unfinishedBattleCheck
#import chimeraclash
#import hydraclash
#import chimera
#from chimera import Mode
import shared


# This will
# run dungeons, arena, update units, etc...
# runs until stopped
# works only on resolution - 1024x768

# restart is managed inside errorhandling

while(True):
    # TODO: make a global swither for main theme in stronghold: x-mas, halloween, etc...
    # 'is_halloween' png
    # it can automatically check what theam is it and apply it
    # buy items in bazaar

    print("cvcIncoming ", shared.cvcIncoming(True))
    #flagInstance.no_cvc = True # manual override

    print("Fresh start")
    errorManager.did_reset = False
    errorManager.error_detected = False
    closeadds.closeAdds()
    if(unfinishedBattleCheck() == 'detected'):
        closeadds.closeAdds()
    
  # market.buyShards(False)
  # guardianring.upgradeChampions()
    collectgems.main()
  # dailyquests.main()

   # dungeon.ironTwins()
   # dungeon.icegolem() # TODO: make dungeon.main() that accept ENUM SPIDER | DRAGON | FK | MINO | EVENT | SD | SHOGUN | IRONTWINS | POTIONKEEP
    #dungeon.spider()
    #dungeon.dragon()
    #dungeon.fireknight()
    #dungeon.minotaur()
    #dungeon.eventDungeon()
    #dungeon.sanddevil()
    #dungeon.shogun()

   # factionwars.main() 
   # clanboss.main()
   # doomtower.main()

    #chimeraclash.main()
    #hydraclash.main()
    #chimera.main(Mode.PUSH)

    arenalive.main()
   # arena.tagTeam("2026-09-16")
   # arena.classic() 

    #dungeon.arcaneKeep()
    #dungeon.forceKeep()
    #dungeon.magicKeep()
    #dungeon.spiritKeep()
    #dungeon.voidKeep()
    print(
        f"Cykl zakończony. Ponowne sprawdzenie za "
        f"{CHECK_INTERVAL_SECONDS} sekund..."
    )
    time.sleep(CHECK_INTERVAL_SECONDS)