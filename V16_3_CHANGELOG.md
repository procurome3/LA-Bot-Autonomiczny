# V16.3 — faction-roster discovery

- HellHades Tier List is no longer used as the champion discovery source.
- The updater can refresh champion profile slugs from every faction `/roster/` page.
- Only factual kit mechanics are imported; rankings/ratings remain explicitly disabled.
- Existing Legendary/Mythical champions are matched by exact profile slug first, then canonical name.
- Newly discovered champions are added only if the faction roster itself identifies them as Legendary or Mythical.
- Faction discovery failure is non-fatal: the existing local roster remains usable.
- A coverage/status report is generated at `data/champion_database_update_report.json`.
- Individual champion pages remain the source for skills/effects/cooldowns. Faction pages are only the roster/index layer.
