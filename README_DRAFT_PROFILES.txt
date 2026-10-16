LIVE ARENA — DRAFT PROFILES V15.2
=================================

CEL
Każdy użytkownik może mieć własne PICK / BAN / COUNTER-PICK / LEADER bez
edytowania arenalive.py.

URUCHOMIENIE
1) Domyślny profil z livearena_config.py:
   ACTIVE_DRAFT_PROFILE = "default"

2) Jednorazowo z PowerShell:
   py arenalive.py --draft-profile piotr

3) Albo zmienna środowiskowa:
   set LIVEARENA_DRAFT_PROFILE=piotr
   py arenalive.py

PLIKI
- draft_profiles/default.json   -> zachowuje stare zachowanie bota
- draft_profiles/example_user.json -> przykład składni
- utwórz np. draft_profiles/piotr.json dla własnych zasad

POLA JSON
pick_priority
  Bazowa kolejność wyboru. Gdy pierwszy champion nie jest dostępny,
  bot sprawdza następnego, zamiast zatrzymywać draft.

ban_priority
  Bazowa kolejność banów.

leader_priority
  Kolejność liderów spośród REALNIE wybranej drużyny. Jeśli żaden nie pasuje,
  bot bezpiecznie wraca do kolejności rzeczywistych picków.

counter_pick
  Prosta reguła:
    "fabian": ["marius", "yumeko"]
  oznacza: jeśli po stronie przeciwnika rozpoznano Fabiana, spróbuj najpierw
  Mariusa, potem Yumeko, a następnie wróć do pick_priority.

counter_pick_rules
  Bardziej złożone reguły. Obsługiwane:
    if_enemy_any -> wystarczy jeden champion z listy
    if_enemy_all -> muszą być wszyscy z listy
    priority     -> kolejność kandydatów do picku

ban_rules
  Działa tak samo jak counter_pick_rules, ale tworzy priorytet bana.
  Warunkowy ban jest dokładany PRZED ban_priority.

opponent_templates / pick_templates / ban_templates
  Opcjonalne mapy ręcznych nazw plików, gdy nazwa PNG odbiega od standardu.
  Przykład:
    "opponent_templates": {
      "galathir": "arena_live_enemy_galathier.png"
    }

STANDARDOWE NAZWY
- własny pick:      arena_live_<champion>.png
- przeciwnik:       arena_live_enemy_<champion>.png
- ban:              arena_live_ban_<champion>.png

Wbudowane aliasy obejmują obecne różnice nazw:
- Gliseah <-> glicea
- Galathir <-> galathier
- Embrys <-> embris

BEZPIECZEŃSTWO / FALLBACK
- brak lub uszkodzony JSON -> bot wraca do starego MY_CHAMPIONS / BAN_CHAMPIONS /
  LEADER_PRIORITY z livearena_config.py;
- brak template'u warunkowego przeciwnika -> reguła po prostu się nie aktywuje;
- żaden ban z profilu niewidoczny -> zachowany stary fallback slot 1;
- profil nie może zmienić logiki COMBAT ani priorytetów skilli.

WYDAJNOŚĆ
Skan przeciwnika obejmuje TYLKO championów użytych jako warunek w aktywnym
profilu. Profil bez counter/ban rules nie wykonuje żadnego dodatkowego skanu
przeciwnika.


SYMBIONT
========
Profil: draft_profiles/symbiont.json
Uruchomienie: py arenalive.py --draft-profile symbiont
Lub: RUN_SYMBIONT.bat
Szczegóły i brakujące template'y: PROFILE_SYMBIONT_REPORT.txt


V15.5 UPDATE
============
Symbiont profile received extra templates for Komidus, Tekteon, Shu-Zhen and Odin.
Added rule: enemy Odin -> Cruetraxa.
