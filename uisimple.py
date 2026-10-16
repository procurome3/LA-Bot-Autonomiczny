import tkinter as tk
import threading
import time
import arena
import arenalive


running = False


def runScript():
    log(f'Running checked {isChecked.get()}, dungeon: {dungeon.get()}')

def loop():
    global running
    while running:
        runScript()
        if arenaClassic.get():
            arena.classic() # could make classic() accept boolean to avoid if check in this file
        if arenaClassic.get():
            arena.tagTeam("2026-02-23")
        if arenaLive.get():
            arenalive.main()
        time.sleep(2)

def start():
    global running
    if not running:
        running = True
        threading.Thread(target=loop, daemon=True).start()

def stop():
    global running
    running = False
    log("Stopped")

def log(message):
    output.insert(tk.END, message +"\n")
    output.see(tk.END) # unsafe. to be replaced with root.after() or queue.Queue()


root = tk.Tk()
root.geometry("400x600")
isChecked = tk.BooleanVar() # StringVar, IntVar, DoubleVar
arenaClassic = tk.BooleanVar(value=True)
arenaLive = tk.BooleanVar(value=True)
arenaTag = tk.BooleanVar(value=True)
dungeon = tk.StringVar(value="minotaur") # use ENUM to not make mistakes

frame = tk.LabelFrame(root, text="Dungeon to run")
framePvp = tk.LabelFrame(root, text="Pvp")
frame.pack(padx=10, pady=10, fill="x")
framePvp.pack(padx=10, pady=10, fill="x")

tk.Button(root, text="Start", command=start).pack()
tk.Button(root, text="Stop", command=stop).pack()
tk.Checkbutton(root, text="Enable checked", variable=isChecked).pack()
tk.Checkbutton(framePvp, text="Arena classic", variable=arenaClassic).pack(anchor="w")
tk.Checkbutton(framePvp, text="Arena live", variable=arenaLive).pack(anchor="w")
tk.Checkbutton(framePvp, text="Arena tag", variable=arenaTag).pack(anchor="w")
tk.Radiobutton(frame, text="Minotaur", variable=dungeon, value="minotaur").pack(anchor="w")
tk.Radiobutton(frame, text="Dragon", variable=dungeon, value="dragon").pack(anchor="w")
tk.Radiobutton(frame, text="Event dungeon", variable=dungeon, value="event").pack(anchor="w")


frame = tk.Frame(root)
frame.pack(fill="both", expand=True, padx=10, pady=10)

scrollbar = tk.Scrollbar(frame)
scrollbar.pack(side="right", fill="y")

output = tk.Text(frame, height=10, yscrollcommand=scrollbar.set)
output.pack(side="left", fill="both", expand=True)

root.mainloop()

# TODO:
# toggle between simple and advanced layout (options)