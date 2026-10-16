SYMBIONT — KRÓTKA KOMENDA
==========================

CEL
Po jednorazowej instalacji zamiast:

    py arenalive.py --draft-profile symbiont

wpisujesz po prostu:

    symbiont

INSTALACJA — TYLKO RAZ
1. Rozpakuj paczkę do docelowego folderu bota.
2. Uruchom dwuklikiem:
       INSTALL_SYMBIONT_COMMAND.bat
3. Instalator doda folder bota do PATH bieżącego użytkownika Windows.
   Nie wymaga uprawnień administratora.
4. Zamknij obecne okno PowerShell/CMD.
5. Otwórz nowe okno terminala.
6. Wpisz:
       symbiont

DZIAŁANIE
symbiont.cmd automatycznie:
- przechodzi do folderu bota,
- uruchamia:
      py arenalive.py --draft-profile symbiont
- przekazuje także ewentualne dodatkowe argumenty.

WAŻNE
Jeżeli później przeniesiesz cały folder bota w inne miejsce, uruchom ponownie
INSTALL_SYMBIONT_COMMAND.bat z nowej lokalizacji.

NIE ZMIENIA TO
- logiki walki,
- priorytetów skilli,
- profilu Symbiont,
- pick/counter-pick/ban/leader,
- folderu bilder.

Zmienia tylko sposób uruchamiania programu.
