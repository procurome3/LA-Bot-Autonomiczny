V15.8 — PROFILE COMMANDS START THE FULL BOT
=============================================

WHAT WAS WRONG
The earlier command:
    symbiont

started:
    py arenalive.py --draft-profile symbiont

That bypassed the normal raid.py startup sequence.  Therefore startup work
performed by raid.py — especially closeadds.closeAdds() — did not happen first.

FIX
Every profile command now executes:
    py profile_start.py <profile>

profile_start.py then runs the existing raid.py FROM ITS FIRST LINE while
forwarding:
    --draft-profile <profile>

Therefore the old startup sequence is restored:
    raid.py startup
    -> Fresh start
    -> reset error flags
    -> closeadds.closeAdds()
    -> unfinishedBattleCheck()
    -> all other modules currently enabled in YOUR raid.py
    -> arenalive.main() using the selected profile

SYMIBONT
Typing:
    symbiont

now starts the entire raid.py flow with draft profile "symbiont".

OTHER PROFILES
Run once:
    INSTALL_PROFILE_COMMANDS.bat

It creates a Windows command for every:
    draft_profiles/<name>.json

Examples:
    draft_profiles/symbiont.json -> command: symbiont
    draft_profiles/kuba.json     -> command: kuba
    draft_profiles/piotr.json    -> command: piotr

When you add another profile JSON, run INSTALL_PROFILE_COMMANDS.bat again.

HELLO WORLD
profile_start.py checks raid.py.
- If raid.py already contains HELLO WORLD!, it does not print a second copy.
- If raid.py does not contain it, the launcher prints purple italic HELLO WORLD!
  before executing raid.py.

IMPORTANT
This package does not replace your existing raid.py.  Keep your current raid.py
in the project root.  The profile launcher deliberately executes that exact
file, preserving whichever tasks you currently have enabled/commented there.
