# Live Arena V16.5 — baza i importer

Paczka jest poprawką do V16.4 i zawiera tylko zmienione/dodane pliki. Nie wymaga GitHuba ani programu Git.

## Instalacja

1. Zamknij bota.
2. Wypakuj zawartość ZIP-a bezpośrednio do folderu testowej V16.4. Plik `champion_database.py` ma trafić obok `arenalive.py`, a katalogi `data` i `tools` mają połączyć się z istniejącymi katalogami.
3. Zgódź się na zastąpienie plików.
4. Uruchom bota tak samo jak dotychczas. Dołączona baza jest już pobrana i przetworzona — przed tym testem nie trzeba uruchamiać aktualizatora.

Przy późniejszych aktualizacjach uruchom `UPDATE_CHAMPION_DATABASE.bat`. Aktualizator rozpoznaje starszy parser i odświeża jego rekordy także przy opcji `--resume`.

## Zawartość danych z 16 października 2026

- 430 unikalnych postaci z indeksu HellHades: 396 Legendary i 34 Mythical.
- 429 postaci ma powiązania do modelu gry, identyfikatorów form i widocznych skilli.
- Wszystkie 34 Mythicale mają osobno bazową i alternatywną formę.
- 1882 widoczne wpisy skilli pochodzą z aktualnego interfejsu danych używanego przez strony HellHades.
- Orynyx Mindcrawler nie ma modelu gry w obecnym indeksie. Jego 4 skille pochodzą z osobnego interfejsu zapowiedzi; ograniczenie jest zapisane przy rekordzie.
- W bazie jest łącznie 1886 wpisów skilli i 388 rekordów aur. Zachowano parametry statusów, ulepszeń i wzorów obrażeń, bez ocen i rankingów.

`detailed` oznacza pobrane i poprawne strukturalnie dane. Nie oznacza potwierdzenia kompletnego rozumienia każdej mechaniki przez AI. Złożone warunki i nieprzetłumaczone operacje są wskazane w `review_flags` oraz w `data/champion_database_validation_report.json`.

W wykazach modeli występują też identyfikatory wewnętrzne, których interfejs skilli nie wystawia jako oddzielnych przycisków. Zapisano je w `unexposed_skill_ids`. Walidator oddzielnie porównuje identyfikatory widocznych skilli i ich przynależność do wybranej formy.

## Naprawione przypadki

- Odczyt obu tablic form zamiast odrzucania drugiej, m.in. Embrys.
- Aktualne nazwy i typy Miny: bazowa transformacja to pasywka; nie jest klikalnym A4. W poprzednim raporcie zbyt szeroko opisałem błąd jako cały zestaw Arnego — stare API mieszało jego nazwy z opisami mechanik Miny.
- Brak przesuwania numeracji po zdublowanych wierszach Lazariusa; brak aktywnego A5 dla pasywki Nell.
- Veil/Perfect Veil w Predatorze A2 są warunkiem ignorowania DEF, nie nakładanym buffem.
- Taunt i Poison Cloud są poprawnie klasyfikowane jako buffy. Parametry nakładanego efektu są oddzielone od wymagań i ignorowanych statusów.
- Nagłówki „Passive Effect” i „Active Effect” nie są efektami.
- Cooldown bazowy i po bookach, w tym poprawne 0 dla skilli bez cooldownu; osobna szansa bazowa i po bookach.
- Alias nie usuwa pełniejszego zestawu form. Nazwy używane w profilach pozostają rozpoznawane.
- Brakujący skill F2 nie jest zastępowany skillem F1. Pasywki nie dostają profilu klikalnej akcji.
- Wybór lidera może korzystać z rzeczywistej, bezwarunkowej aury SPD na Arenę lub wszystkie bitwy.
- Błąd sieci nie kasuje wcześniej pobranego zestawu. Walidacja wykrywa błędne sloty, pasywki, cooldowny i niezgodne identyfikatory.

## Kontrola

Raport pobierania: `data/champion_database_update_report.json`.
Raport walidacji: `data/champion_database_validation_report.json`.

Samodzielna kontrola:

```bat
py tools\validate_champion_database.py --report data\champion_database_validation_report.json
py -m unittest test_champion_database test_champion_database_api test_champion_database_regressions test_livearena_autonomy
```

Wersja wymaga testu w prawdziwej walce. Testy automatyczne sprawdzają parser, bazę i logikę decyzji, ale nie potwierdzają działania rozpoznawania ekranu i kliknięć na Twoim komputerze. Złożone reguły nieprzełożone jeszcze na predykaty AI pozostają ograniczeniem tej wersji.
