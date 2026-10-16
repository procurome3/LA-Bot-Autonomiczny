# V16.2 — factual kit DB + active-roster combat vision

- Added 421-name Legendary/Mythical roster index (33 Mythical, 388 Legendary).
- Added `champion_database.py` and `data/champion_database.json` facts-only schema.
- Added resumable HellHades individual-champion updater; tier/rating/Live Arena ranking fields are explicitly ignored.
- Autonomous knowledge now falls back to kit-derived tactical metrics and skill tags when no manual override exists.
- Combat skill vision now filters `SKILL_PLAN` to champions actually drafted on our team; mythical roots retain both forms.
- Safe fallback to full skill plan when draft hints are unavailable/mismatched.
- Preserved family-specific A4 semantics (e.g. Arbiter A4 revive, explicit mythical transforms only).
- Added DB/parser/regression tests.
