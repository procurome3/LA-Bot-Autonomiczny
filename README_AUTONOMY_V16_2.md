# Live Arena V16.2 — factual champion kit database + active-roster vision

## What changed

V16.2 adds a structured database for **Legendary and Mythical** champions and connects it to the autonomous draft/combat scorer.

The database is **facts only**. It deliberately does **not** import or use HellHades tier positions, Overall Rating, Arena rating, win rate, pick rate, ban rate or Book Value score. The autonomous engine derives its own tactical metrics from actual kit mechanics (damage, control, revive, strip, cooldown manipulation, Turn Meter, protection, cleanse, etc.). Existing manual tactical rules remain overrides where they already exist.

## Files

- `data/champion_roster_legendary_mythical_2026.json` — 421 indexed Legendary/Mythical champions.
- `data/champion_database.json` — structured factual kit database. The package starts with the full roster index plus a verified Arbiter example; run the updater to populate remaining skill details.
- `champion_database.py` — loader + factual-kit-to-autonomy derivation.
- `tools/update_champion_database.py` — resumable HellHades individual-page updater.
- `UPDATE_CHAMPION_DATABASE.bat` — one-click Windows updater.

## Populate/update the factual kit database

Run:

`UPDATE_CHAMPION_DATABASE.bat`

or manually:

`py tools\update_champion_database.py --resume --rarity legendary mythical`

For a small parser test:

`py tools\update_champion_database.py --names "Arbiter,Tekteon Fissureflesh" --force`

The updater writes after every successful champion, so it can be stopped and resumed.

## Combat performance change

At combat start, `CombatAnalyzer` now filters `SKILL_PLAN` to **only the champions actually drafted on our team**. Mythical champions keep both forms. If draft hints are missing or inconsistent, it automatically falls back to the full skill plan.

Expected log:

`COMBAT ACTIVE TEMPLATE SET: 4 champs -> 13 skill templates (filtered from 90)`

This means the textual knowledge database can contain hundreds of champions without making every combat turn compare hundreds of skill templates.

## A4 safety

A4 remains family-specific. Arbiter A4 is `ally_dead` revive. Mythical A4 is transform only for champions explicitly configured that way. V16.2 does not introduce a global `A4 = transform` rule.

## V16.3 roster discovery

`UPDATE_CHAMPION_DATABASE.bat` now starts from HellHades faction roster pages rather than the Tier List. The faction pages are used only to discover champion profile URLs, faction and rarity grouping. Skill mechanics still come from individual champion pages. Ratings/tier positions are never imported.
