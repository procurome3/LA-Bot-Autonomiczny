import cv2
import numpy as np


#Upgrade in campain

#simple implementation - only 1*
#upgrade only lvl 1 champions by running 3 times in 12-3
#better option: run 2 times in 12-3 brutal and 1 time in 12-3 hard. (2 less energy)

#simple
#select 3 champions at the end of the champ row - run 3 times

#advanced - need to use alpha channel
#select 3 champions lvl 1 (same star rating)
#if 1* run 3 times
#if 2* run 10 times



#Upgrade champions in tavern


#
# read game image
screenshot = cv2.imread('./bilder/game.png') #ss of the screen or game window for better performance

# read image template (image with transparent pixels)
template = cv2.imread('./bilder/upgradechamp1star.png', cv2.IMREAD_UNCHANGED)
hh, ww = template.shape[:2]

# extract bananas base image and alpha channel and make alpha 3 channels
base = template[:,:,0:3]
alpha = template[:,:,3]
alpha = cv2.merge([alpha,alpha,alpha])

# do masked template matching and save correlation image
correlation = cv2.matchTemplate(screenshot, base, cv2.TM_CCORR_NORMED, mask=alpha)

# set threshold and get all matches
threshhold = 0.95
loc = np.where(correlation >= threshhold)

# draw matches 
result = screenshot.copy()
for pt in zip(*loc[::-1]):
    cv2.rectangle(result, pt, (pt[0]+ww, pt[1]+hh), (0,0,255), 1)
    print(pt) #gives coordinates (x, y) of each match. I assume upper left corner.

# save results
cv2.imwrite('bananas_base.png', base)
cv2.imwrite('bananas_alpha.png', alpha)
cv2.imwrite('game_bananas_matches.jpg', result)  

cv2.imshow('base',base)
cv2.imshow('alpha',alpha)
cv2.imshow('result',result)
cv2.waitKey(0)
cv2.destroyAllWindows()

#results with threshhold 0.95 
# It did much all common champions(grey frame). It did match both 1 star and 2 stars.
# It did not match any uncommon(green frame)

#results with threshhold 0.97
# did match some 2star level 1 uncommon champions, also 3 star uncommon lvl1

#Simple solution:
# take picture of every common and uncommon level 1 champ. Search these and upgrade.
# take picture of the part with level 1. Don't take into picture # of stars.