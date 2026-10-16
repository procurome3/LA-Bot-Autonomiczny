#import tkinter as tk
from tkinter import *
from tkinter import ttk
import pyautogui
import time #this makes GUI to freeze... need better structure of application

def sel():
    selection = "Selected instance: "+toRepeat.get()
    log.set(selection)

# Instead of selecting what to repeat:
# Search for all type of repeat buttons,
# which button has been found, press it !!! 

# Add better logging. What to log:
# 1. What istance has been repeated
# 2. How many times
# 3. How many successfull/faild runs


def runLoop(*args):
    try:
        currentRun = 0
        _picture_file = toRepeat.get()
        _times_to_run = int(times_to_run.get())
        while(currentRun < _times_to_run):
            result = pyautogui.locateOnScreen(f'./bilder/{_picture_file}.PNG', grayscale = True, confidence = 0.96)
            log.set(result)
            if(result):
                currentRun += 1
                pyautogui.click(result)
                time.sleep(5) 
                refill = pyautogui.locateOnScreen('./bilder/confirm_refill.PNG', grayscale = True, confidence = 0.97)
                if(refill):
                    pyautogui.click(refill)
                    pyautogui.click(result)
            time.sleep(10)
        log.set("COMLETE")
    except ValueError:
        pass


# set up application window (aka html)
root = Tk()
root.title("Repeat Raid runs")

# frame widget (aka html body)
mainframe = ttk.Frame(root, padding="10 10 12 12")
mainframe.grid(column=0, row=0, sticky=(N, W, E, S))
root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

# 1.- input for how many times to run
times_to_run = StringVar()
feet_entry = ttk.Entry(mainframe, width=6, textvariable=times_to_run)
feet_entry.grid(column=1, row=0, sticky=W)

# 2.- widget I need is 3 radio buttons, that will set
toRepeat = StringVar()
R1 = Radiobutton(mainframe, text="Dungeon", variable=toRepeat, value='replay', command=sel)
R1.grid(column=1, row=1, sticky=W)
R2 = Radiobutton(mainframe, text="Doomtower", variable=toRepeat, value='replay2_doomtower', command=sel)
R2.grid(column=1, row=2, sticky=W)

# 3.- Start button that will run while loop
ttk.Button(mainframe, text="Start repeating", command=runLoop).grid(column=3, row=3, sticky=W)

# 4.- show log
log = StringVar(value='Selected instance: ')
ttk.Label(mainframe, textvariable=log).grid(column=0, row=4, columnspan=4, sticky=(N, W))


ttk.Label(mainframe, text="Times to run").grid(column=0, row=0, sticky=W)
ttk.Label(mainframe, text="Type of instance").grid(column=0, row=1, sticky=W)

# some polish
for child in mainframe.winfo_children(): 
    child.grid_configure(padx=5, pady=5)
feet_entry.focus()
root.bind("<Return>", runLoop)

root.mainloop()