MODULARNY LIVE ARENA BOT - INSTALACJA
=====================================

Pliki, które mają leżeć obok raid.py:
  arenalive.py
  livearena_config.py
  livearena_vision.py
  livearena_runtime.py
  requirements_livearena.txt
  install_livearena_dependencies.ps1
  verify_livearena_setup.py

Folder bilder pozostaje ten sam co dotychczas.

1. Skopiuj wszystkie powyższe pliki do folderu raid-scripts.

2. W PowerShell:
   cd "C:\Users\procu\OneDrive\Pulpit\LA R\raid-scripts"
   Set-ExecutionPolicy -Scope Process Bypass
   .\install_livearena_dependencies.ps1

3. Sprawdź instalację:
   py verify_livearena_setup.py

4. Uruchamianie pozostaje bez zmian:
   py raid.py

Najważniejsze zmiany architektury:
- livearena_config.py: priorytety, skille, state machine, progi i ROI.
- livearena_vision.py: MSS, preload/cache PNG, ROI, OpenCV matching, performance.
- livearena_runtime.py: płynny kursor, Click Guard, watchdog.
- arenalive.py: logika Live Areny i decyzje.

Hotkeye:
  `   pauza/wznowienie
  TAB screenshot + diagnostyka do ./debug

Uwagi:
- MSS jest opcjonalny w kodzie (fallback do pyautogui), ale dla szybkości warto go zainstalować.
- Jeśli po zmianie obrazu w bilder bot używa starego wzorca, cache automatycznie odświeża plik po zmianie mtime.
- Log PERF pojawia się rzadko (domyślnie co 20 s), żeby nie spamować konsoli.


FAST V2 (na podstawie testu video 2026-09-28):
- standardowe UI: 1 skala zamiast 5,
- state-aware phase matching,
- ROI dla opponent-left/cant-find/refill/result,
- skille: 1.00 najpierw + dwa fallbacki,
- early-stop po score >= 0.80.


MOUSE GUARD V4:
- bot czeka, gdy uzytkownik porusza myszka,
- finalny klik jest wykonywany w zaplanowanym punkcie,
- jesli kursor zostanie przesuniety w trakcie ruchu, pozycja jest korygowana,
- jesli nie da sie ustabilizowac kursora, klik jest anulowany i state machine ponawia akcje.


V5 CALIBRATED (2026-09-29)
--------------------------
Najważniejsze poprawki na podstawie filmu 20260929-0218:
1. Leader:
   - priorytet: Fabian > Ankora > Harima > Mikage,
   - klik po skalibrowanych slotach względem client-area RAID,
   - po kliknięciu bot sprawdza zieloną obwódkę WYBRANEGO slotu,
   - Confirm jest klikany dopiero po pozytywnej weryfikacji wyboru,
   - jeśli wybór nie wszedł, bot ponawia TEN SAM slot, a nie przechodzi losowo dalej.

2. Combat:
   - poprawione środki skilli:
       A1=(476,706), A2=(596,706), A3=(716,706)
     w referencji clienta 1024x769,
   - stare punkty były przesunięte ok. 120-140 px w prawo,
   - każdy template skilla jest sprawdzany tylko w ROI swojego przycisku,
   - podczas własnej tury, jeśli template nie zadziała przez 0.70 s,
     bot używa skalibrowanego A1 jako bezpiecznego fallbacku.

3. Kalibracja:
   - livearena_calibration.py centralizuje współrzędne,
   - wszystkie punkty są skalowane względem aktualnej pozycji/rozmiaru okna,
   - verify_livearena_calibration.py zapisuje debug/livearena_calibration_overlay.png.


V6 DPI + DYNAMIC SCALE
----------------------
Naprawa dla Windows DPI scaling / zmiany rozmiaru okna:
- ctypes, MSS i pyautogui używają Per-Monitor-V2 DPI awareness,
- template PNG jest automatycznie skalowany do aktualnego client-area,
- Your Turn / fazy draftu również używają dynamicznej skali,
- skill PNG używają dynamicznej skali w osobnym ROI A1/A2/A3,
- tester wypisuje physical client i template_scale.


V7 CORRECTED CALIBRATION
------------------------
Na podstawie screena 1024x769:
A1 = (596, 706)
A2 = (716, 706)
A3 = (836, 706)

Poprzednia wersja była przesunięta o jeden skill (~120 px) w lewo.

Tester:
  py verify_livearena_calibration.py
      -> tylko combat A1/A2/A3

  py verify_livearena_calibration.py --leader
      -> tylko Pick Leader


V8 DYNAMIC SKILL LAYOUT
-----------------------
Nie ma już mapowania:
  A1 -> slot X
  A2 -> slot Y
  A3 -> slot Z

Normalna walka:
  skill_<champ>_aN.PNG
  -> wyszukanie na całym pasku
  -> środek REALNIE znalezionej ikony
  -> klik

Dlatego liczba aktywnych skilli może być różna.

Pasywka z "P":
- nie jest w SKILL_PLAN,
- nie jest wybierana przez template matcher,
- awaryjny fallback wybiera tylko LEWY pierwszy okrągły skill (A1),
  nigdy ostatnią pasywkę.

A4 jest wspierane bez nowej kalibracji.
Wystarczy dodać template i wpis SKILL_PLAN, np.:
  ("skill_nazwa_a4", "A4", "normal", "aoe")

Diagnostyka:
  py verify_skill_detection.py


V9 GLOBAL MYTHICAL A4 + MIKAGE/ANKORA
-------------------------------------
Dodano:
- Mikage A2 -> AOE.
- Ankora A1 -> single target.
- Ankora A2 -> self/support.
- Ankora A3 -> ally_dead:
    * skill jest pomijany, jeśli nikt nie jest martwy,
    * bot śledzi 4 friendly HP bary,
    * po potwierdzeniu śmierci klika A3, potem martwy slot.
- skill_mythical_transform_a4.PNG -> globalny A4 dla mitycznych:
    * jeden template dla wszystkich,
    * priorytet: A2/A3/... -> transform A4 -> A1,
    * po transformie bot czeka 0.45 s na zmianę paska skilli.
- Pasywka P nadal nie jest w planie i nie jest klikalna.

Template A4 z rozmowy jest dołączony w:
  bilder/skill_mythical_transform_a4.PNG


V11 - ACTIVE ALLY + SLOT-FIRST SKILL RECOGNITION
=================================================

Powód:
Nagranie 2026-09-29 pokazało:
  COMBAT WAIT ... family=None
  top score ~0.39-0.47
mimo że skille były wyraźnie widoczne.
Jednocześnie Fenax A1 potrafił później uzyskać score ~0.958.

Zmiana:
1. Zielony ring:
   - wykrywa który z 4 friendly slotów ma aktualnie turę.
2. Pamięć w obrębie pojedynku:
   - mocne rozpoznanie zapisuje active slot -> family.
   - następna tura tego slota nie musi ponownie zgadywać całej rodziny.
3. Slot-first:
   - wykrywane są fizyczne okrągłe przyciski na pasku,
   - każdy jest osobno cropowany,
   - centralny art porównywany jest z PNG po normalizacji,
   - border/glow ma znacznie mniejszy wpływ.
4. P:
   - pasywka nigdy nie jest bezpiecznym fallbackiem.
   - jeśli rozpoznanie zawiedzie, po 0.75 s własnej tury
     używany jest wyłącznie LEWY pierwszy okrągły skill = A1.
5. Target:
   - A1 fallback w obecnej puli traktowany jest jako single target.
6. Action verification:
   - Your Turn,
   - zmiana aktywnego ringu,
   - zmiana paska skilli.
7. Replay:
   - pokazuje active slot, ring ratios, family memory,
     liczbę wykrytych kółek oraz top normalized skill matches.

Paczka V11 NIE zawiera bilder ani PNG.


V11.1 - TARGET + PRIORITY FIX
==============================

Problem z V11:
- skill był wybierany, ale target click następował zbyt szybko,
- match skilla mógł "przeskoczyć" na inny fizyczny przycisk,
- cooldown skill mógł wygrać samym priorytetem.

Naprawa:
1. A1/A2/A3/A4 -> fizyczne sloty 0/1/2/3 od lewej.
   Template jest porównywany TYLKO z właściwym slotem.
2. Cooldown/disabled:
   jasność i saturation są porównywane z aktywnym PNG.
3. Jawne priorytety:
   Fabian: A3>A2>A1
   Mikage: A3>A2>A1
   Mithrala: A3>A2>A1
   Ankora: A3(revive only)>A2>A1
   UDK: A3>A2>A1
   Ronda: A2>A3>A1
   Harima: A2>A3>A1
   Fenax: A1
   global A4 transform: przed A1, po wyższych skillach.
4. Target:
   - po skill click czeka 140-220 ms,
   - bierze świeżą klatkę,
   - X celu pochodzi z faktycznego paska HP,
   - jeśli pierwszy target click nie wykona akcji -> jeden TARGET RETRY,
     bez ponownego klikania skilla.
5. Log:
   TARGET CLICK -> ...
   TARGET RETRY -> ...
   top skill pokazuje też available True/False.

Paczka nie zawiera bilder ani PNG.


V11.3 - MERGED FIX: LEADER / OPPONENT TURN / ANKORA
====================================================

1. LEADER VERIFIED
- wybór lidera najpierw używa realnych arena_live_lead_*.PNG,
- historia picków jest fallbackiem,
- zielona obwódka jest oceniana dla WSZYSTKICH 5 slotów,
- tylko jeden jednoznaczny najlepszy slot może zostać VERIFIED,
- log pokazuje border score wszystkich kart.

2. OPPONENT TURN
- usunięto ring jako alternatywny dowód własnej tury,
- jeśli nie ma "Your Turn", bot NIE uruchamia analizy skilli,
- jeden log: "tura przeciwnika -> czekam",
- brak spamu COMBAT WAIT podczas ruchu przeciwnika.

3. ANKORA / CHAMPIONY Z WIĘKSZĄ LICZBĄ IKON
- skill ROI wraca do szerokiego zakresu,
- fizyczne skille są wykrywane jako regularny klaster od prawej,
- pasek może mieć 2/3/4/5 okrągłych ikon,
- pasywka P może być ostatnia, ale nie jest wybierana jako skill,
- nie ucina już A1/A2 po lewej stronie (problem V11/V11.1).

4. Zachowane:
- V11.1 target delay/retry,
- affinity / Stone Skin / Veil / HP,
- Harima lowest HP,
- Ankora A3 tylko po potwierdzonym dead ally,
- V11.2 reklamy.


V11.4 - STATE / TURN / LEADER / ANKORA
=======================================

1. STATE LOG
Każde przejście:
========== STATE: PICK -> BAN ==========
========== STATE: BAN -> LEADER ==========
========== STATE: LEADER -> LOADING ==========
========== STATE: LOADING -> COMBAT ==========

2. Nie uruchamiamy COMBAT na loading screenie.
Po Pick Leader bot trafia do LOADING.
COMBAT startuje dopiero po 2 kolejnych klatkach z realną zieloną
ramką jednego z portretów graczy.

3. Turn owner
Główne źródło:
- zielona ramka NASZEGO portretu = player turn,
- zielona ramka PRZECIWNIKA = opponent turn.
Napisy Your Turn są tylko fallbackiem.

Offline test na materiałach użytkownika:
- Pick Leader: owner=None
- ekran loading: owner=None
- realne Your Turn: owner=player
- realne Opponent's Turn: owner=opponent

4. Leader
Podczas normalnego draftu nazwa lidera pochodzi WYŁĄCZNIE z PICK TRACK.
Nie używamy arena_live_lead_* do rozpoznawania nazwy, bo Ankora
fałszywie dopasowała się do slotu Fabiana na nagraniu.
Template pozostaje wyłącznie awaryjnym fallbackiem po restarcie w Phase 3.

5. Ankora
Progi family recognition obniżone dla spójnego zestawu 3 ikon.
Na nagraniu Ankora miała około:
A2=0.533, A3=0.508, A1=0.483
czyli 3 zgodne sloty, mimo że żaden pojedynczy score nie był wysoki.
V11.4 uznaje taki zestaw za wiarygodną rodzinę Ankory.

6. Zachowano:
- target delay/retry,
- affinity / Stone Skin / Veil,
- revive Ankory tylko przy confirmed dead ally,
- dynamiczny 2-5 skill cluster,
- poprawkę reklam.
