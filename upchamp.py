import pyautogui
import time


#step 1 clear all spaces next to Razelvarg


#step 2 make sure 2 empty spaces exist
#step 3 find 3 champions to level up
#step 4 make sure no empty spaces exist
#run dungeon 3 times ?
# problem is : how many times to run??? I can not determine how many stars they have. (picture recognition seem to fail)

#So I need pictures of every champ with 1star, 2 stars, 3 stars. Make a spreadsheet for overview. ... a lot of work


# v2. another method:
# check how many stars champions in the slots have
# start by serching 4stars, then 3, 2, 1
#   if detected 3 stars, 
#   stop search,
#   check what level they are, if lvl 30, replace champions

results = pyautogui.locateAllOnScreen('./bilder/training_preacher.PNG', grayscale = True, confidence = 0.95)
for result in results:
    print(result)
    pyautogui.click(result)
    time.sleep(0.5)