import tkinter as tk
import threading
import time
import arena
import arenalive
import dungeon
import os
import ctypes
      
"""
    To add UI element:
    1. create tk.variable holding value         - # Variables
    2. create tk.elementType and bind variable  - # Buttons # Checkboxes
    3. attach element getter to logic           - loop(self)

"""

class AppUI:
    def __init__(self, root: tk.Tk) -> None:
        self.running = False
        self.root = root
        self.thread: threading.Thread | None = None

        # Variables
        self.buyShards = tk.BooleanVar()
        self.upgradeChampions = tk.BooleanVar()
        self.collectgems = tk.BooleanVar()
        self.dailyquests = tk.BooleanVar()
        self.factionwars = tk.BooleanVar()
        self.clanboss = tk.BooleanVar()
        self.doomtower = tk.BooleanVar()
        self.chimeraclash = tk.BooleanVar()
        self.chimera = tk.BooleanVar()
        self.ironTwins = tk.BooleanVar()
        self.dungeon = tk.StringVar(value="dragon")
        self.enable_dungeon = tk.BooleanVar(value=True)


        self.build_ui()          

    def _append_log(self, message):
        self.output.insert(tk.END, message +"\n")
        self.output.see(tk.END)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.loop, daemon=True) # changes made to UI in loop are scheduled with after()
            self.thread.start()
    
    def stop(self):
        self.running = False
        self.log("Stopped")
    
    def kill_all_process(self):
        os._exit(0)
    
    def kill_thread(self):
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(self.thread.ident),
            ctypes.py_object(SystemExit)
        )


    def toggle_dungeon(self):
        state = tk.NORMAL if self.enable_dungeon.get() else tk.DISABLED
        for widget in self.dungeon_frame.winfo_children():
            widget.config(state=state)
        if state == "disabled":
            self.dungeon.set(None)

    def loop(self):
        while self.running:
            self.log(f'Running dungeon {self.dungeon.get()}')
            if self.dungeon.get() == "dragon":
                dungeon.dragon()
            if self.dungeon.get() == "ice_golem":
                dungeon.icegolem()
            if self.dungeon.get() == "spider":
                dungeon.spider()
            if self.dungeon.get() == "fireknight":
                dungeon.fireknight()
            if self.dungeon.get() == "minotaur":
                dungeon.minotaur()
            if self.dungeon.get() == "event":
                dungeon.eventDungeon()
            if self.dungeon.get() == "sanddevil":
                dungeon.sanddevil()
            if self.dungeon.get() == "shogun":
                dungeon.shogun()

            time.sleep(2)

    def build_ui(self):
        self.root.geometry("400x600")

        # Buttons
        tk.Button(self.root, text="Start", command=self.start).pack()
        tk.Button(self.root, text="Stop", command=self.stop).pack()
        tk.Button(self.root, text="Kill process", command=self.kill_all_process).pack()
        tk.Button(self.root, text="Kill tread", command=self.kill_thread).pack()
        self.exampleButton = tk.Button(self.root, text="example", command=lambda: self.exampleButton.config(text="new text")) # changes made to UI directly to root don't need schedule


        # Checkboxes

        # Dungeon to run
        tk.Checkbutton(root, text="Enable dungeon run", variable=self.enable_dungeon, command=self.toggle_dungeon).pack()
        self.dungeon_frame = tk.LabelFrame(self.root, text="Dungeon to run")
        self.dungeon_frame.pack()
        tk.Radiobutton(self.dungeon_frame, text="Dragon", variable=self.dungeon, value="dragon").pack()
        tk.Radiobutton(self.dungeon_frame, text="Ice golem", variable=self.dungeon, value="ice_golem").pack()
        tk.Radiobutton(self.dungeon_frame, text="Spider", variable=self.dungeon, value="spider").pack()
        tk.Radiobutton(self.dungeon_frame, text="Fireknight", variable=self.dungeon, value="fireknight").pack()
        tk.Radiobutton(self.dungeon_frame, text="Minotaur", variable=self.dungeon, value="minotaur").pack()
        tk.Radiobutton(self.dungeon_frame, text="Event dungeon", variable=self.dungeon, value="event").pack()
        tk.Radiobutton(self.dungeon_frame, text="Sanddevil", variable=self.dungeon, value="sanddevil").pack()
        tk.Radiobutton(self.dungeon_frame, text="Shogun", variable=self.dungeon, value="shogun").pack()

        # PVP



        # Output (log area)
        log_frame = tk.Frame(self.root)
        self.scrollbar = tk.Scrollbar(log_frame)
        self.output = tk.Text(log_frame, height=10, yscrollcommand=self.scrollbar.set)

        # pack
        self.exampleButton.pack()
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.scrollbar.pack(side="right", fill="y")
        self.output.pack(side="left", fill="both", expand=True)
    
    # AFTER (logic is - after 0ms run this function)
    def log(self, message):
        self.root.after(0, self._append_log, message)
    
    def updateTextOnElement(self, element):
        self.root.after(0, self.exampleChangeText)

root = tk.Tk()
app = AppUI(root)
root.mainloop() # main tread - handles button clicks, redraws, widgets, root.after(...)


# Mental model

# MAIN THREAD
# ├─ root.mainloop()
# ├─ button callbacks
# ├─ widget updates
# └─ after() callbacks

# WORKER THREAD
# └─ long loops / background tasks
#      └─ schedule UI updates using after()