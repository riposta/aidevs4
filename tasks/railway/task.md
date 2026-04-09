# Task: railway

## Opis
Aktywuj trasę kolejową przez self-documenting API. Trasa musi zostac przełączona w tryb rekonfiguracji, ustawiona na RTOPEN i zapisana. API zwraca flagę po pomyślnym zapisaniu otwartej trasy.

## API
- Endpoint: https://hub.ag3nts.org/verify
- Task name: railway
- Answer format: wynik operacji save (JSON z API), przechowywany w store pod kluczem "filtered"

## Wskazówki
- Trasa do aktywacji: `x-01`
- Format tras: litera-numer, np. "x-01", "a-12"
- Sekwencja operacji (kolejnosc krytyczna):
  1. `railway_reconfigure(route)` — wejscie w tryb edycji
  2. `railway_setstatus(route, "RTOPEN")` — otwarcie trasy
  3. `railway_save(route)` — zapis i wyjscie z trybu edycji
- Mozna wywolac `railway_help` aby uzyskac pelna dokumentacje API
- `railway_getstatus(route)` pozwala sprawdzic aktualny status trasy
- Flaga pojawia sie w odpowiedzi z `railway_save`
- Wynik save jest automatycznie zapisywany do store pod kluczem "filtered"
