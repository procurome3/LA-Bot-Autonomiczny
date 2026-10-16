# Live Arena V16 — autonomous-live-arena-ai

Ta gałąź dodaje autonomiczną warstwę decyzyjną bez usuwania zabezpieczeń V15.
Vision i kliknięcia nadal należą do istniejącego silnika. Nowa warstwa jedynie
porządkuje legalnych kandydatów na podstawie bieżącego stanu gry.

## Przepływ

`Vision -> Game state -> utility scoring -> strict legality -> click guard`

### Draft
- wykrywa szerszy, ograniczony wydajnościowo zestaw przeciwników,
- ocenia picki według kontr, synergii, brakujących ról i modelu kompozycji,
- ban ocenia realne zagrożenie oraz synergię wrogiej drużyny,
- lider jest wybierany według wartości aury/tempa, ale tylko spośród naszych picków.

### Walka
- skille dostają explainable utility score,
- dynamiczny priorytet może przestawiać tylko skille potwierdzone jako gotowe,
- `unknown` wyższego skilla pozostaje twardą barierą bezpieczeństwa,
- hard rules (Gliseah/Fabian, revive, Unkillable, Stoneskin, Veil itd.) nadal mają
  pierwszeństwo,
- target po filtrach legalności jest oceniany przez utility zamiast prostego
  "pierwszy slot",
- explicit `lowest_hp` pozostaje twardą semantyką skilla.

### Arbiter A4
A4 Arbiter pozostaje `ally_dead` / revive. Nie jest globalnym transformem.
Autonomia zwiększa jego utility tylko przy potwierdzonym martwym sojuszniku.

### Model przeciwnika
Z wykrytych championów powstaje model: speed/control/burst/sustain/revive/
protection/lockout/strip. Model wpływa na pick i wartość skilli.

### Uczenie
`state/livearena_autonomy_learning.json` przechowuje wolno zmieniające się priory
z wyników. Silnik zapisuje tylko konserwatywne outcome hints i stosuje mocny
Beta prior, więc kilka walk nie może gwałtownie przestawić draftu.

### Telemetria
`logs/livearena_autonomy.jsonl` zapisuje rankingi pick/ban/leader, skill utility,
target utility i outcome hints. `combat_replay_test.py --json-out ...` zawiera też
`autonomy_skill_scores`.

## Wyłączenie bez cofania plików

Windows PowerShell:

`$env:LIVEARENA_AUTONOMY="0"`

Po restarcie procesu bot wraca do legacy order, zachowując wszystkie poprawki
V15/V15.26 w vision/click engine.

## Pliki V16
- `livearena_autonomy.py` — scoring, opponent model, telemetry, learning
- `livearena_autonomy_knowledge.json` — wiedza champion/skill
- `draft_engine.py` — autonomiczny ranking pick/ban/leader
- `combat_tree.py` — bezpieczny `priority_override`
- `livearena_combat.py` — integracja dynamicznych skilli/targetów
- `arenalive.py` — szersza detekcja finalnego enemy teamu i batching draft scan
- `combat_replay_test.py` — zapis utility w replay
- `test_livearena_autonomy.py` — testy regresyjne czystej logiki
