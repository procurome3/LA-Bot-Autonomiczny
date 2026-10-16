# V16.4 — facts-only full champion database pipeline

- Added `tools/update_champion_database_api.py`.
- Uses the public HellHades champion identity + skill endpoints for factual kit data.
- Explicit allow-list discards rankings, ratings, Book Value, Live Arena statistics, pick/win/ban rates and other editorial metrics.
- Stores normalized mechanics only; full third-party skill prose is not persisted.
- Populates cooldowns (base/booked), target/attack types, hit count, buffs/debuffs, durations, chances, TM effects, revive, strip, cleanse, cooldown manipulation, anti-revive, protection, healing and transform tags when present.
- Mythical alternate forms are enriched from factual skill sections on individual champion pages, with a factual `gacha.gg` Skills-section fallback if needed.
- Existing champion-specific combat overrides remain untouched. The database is knowledge/scoring input, not a replacement for safety rules.
- Exact current faction URLs supplied by the user are retained as discovery fallback, including `/the-sacred-order/`.
- `UPDATE_CHAMPION_DATABASE.bat` now uses the fast API-first updater and is resumable.
