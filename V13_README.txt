V13 PY_TREES - COMBAT ONLY

Files to copy to raid-scripts:
- livearena_combat.py
- combat_tree.py
- combat_rules.py

Install once:
  py -m pip install py_trees

Current decision rules:
- default for every champion: A3 > A2 > A1
- A3 READY -> use A3
- A3 confirmed cooldown/unavailable -> test A2
- A2 READY -> use A2
- A3 + A2 confirmed cooldown/unavailable -> use A1
- UNKNOWN is not treated as cooldown; the bot waits instead of guessing
- A4 is not part of the universal tree
- Ankora A3/revive is ineligible without a confirmed dead ally, so it falls to A2
- Predator override already prepared: A2 > A3 > A1

Future priority changes go only in combat_rules.py.
Targeting, Veil, Stone Skin, affinity and action verification remain in livearena_combat.py.
