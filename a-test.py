#import tkinter as tk
from tkinter import *
from tkinter import ttk

def sel():
    selection = "Selected instance: "+toRepeat.get()
    log.set(selection)


def runLoop(*args):
    try:
        _picture_file = toRepeat.get()
        _times_to_run = int(times_to_run.get())
        for i in range(_times_to_run):
            print("for loop #",i, "- picture file: ", _picture_file)

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