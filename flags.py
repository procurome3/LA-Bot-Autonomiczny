

class FlagManager:
    #One way to use up overflow of energy is 
    # - 1. to use teserract to read current value and run dungeons until below 130
    # - 2. set flag here for intensive rounds

    # I'll start with #2
    #normal_cycle = False # Else intensive(run dungeon more frequent)
    normal_cycle = True
    intensive_cylce_rounds_left = 1
    refyll_from_inventory = False
    refyll_with_gem = False
    run_until_empty = True #set to False overnight to have energy for campaign battles

    do_tag_team_arena = False # This can be automatically turned off on CVC days
    no_cvc = False # THIS VARIABLE NEEDD A BETTER NAME. False - means cvc is tomorrow
    do_arena = True # This can be automatically turned off on CVC days
    do_faction_run2 = False     #do_faction_run2 = dailyquests.main() # includes advanced quest collection

    # some ideas
    use_refylls = False



flagInstance = FlagManager()