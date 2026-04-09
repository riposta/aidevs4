# Task: failure

## Opis
Przeanalizuj logi awarii elektrowni i stworz skompresowana wersje do analizy. Duzy plik logow musi byc zredukowany do maksymalnie 1500 tokenow zachowujac kluczowe informacje o awariach — deduplikacja, skroty, zachowanie pierwszego i ostatniego wystapienia.

## API
- Endpoint: https://hub.ag3nts.org/verify
- Task name: failure
- Answer format: skompresowany tekst logow (przesylany bezposrednio przez `failure_submit`)

## Wskazówki
- Workflow:
  1. `failure_fetch_logs` — pobranie pelnego pliku logow
  2. `failure_compress_logs` — automatyczna kompresja do <= 1500 tokenow
  3. `failure_submit` — wyslanie do weryfikacji
  4. Jesli feedback mowi o brakujacych komponentach — uzyj `failure_search_logs(severity, component)` i `failure_update_logs(additional_lines)`
  5. Powtarzaj submit az do uzyskania flagi
- Kluczowe komponenty elektrowni:
  - ECCS8 — awaryjne chlodzenie
  - WTRPMP — pompa wodna
  - WTANK07 — zbiornik wodny
  - WSTPOOL2 — basen odpadow
  - STMTURB12 — turbina parowa
  - PWR01 — zasilanie
  - FIRMWARE — oprogramowanie sterujace
- Poziomy severity: CRIT, ERRO, WARN, ALL
- Szukanie logow: `failure_search_logs(severity="CRIT", component="ECCS8")`
