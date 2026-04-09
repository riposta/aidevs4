# Task: electricity

## Opis
Rozwiaz puzzle elektryczne na planszy 3x3. Kazde pole zawiera fragment kabla, ktory mozna obracac o 90 stopni. Celem jest polaczenie zrodla pradu ze wszystkimi elektrowniami poprzez prawidlowe ustawienie kabli.

## API
- Endpoint: https://hub.ag3nts.org/verify
- Task name: electricity
- Answer format: flaga pojawia sie po prawidlowym ustawieniu wszystkich pol (w odpowiedzi z API rotacji)

## Wskazówki
- Najprostrze podejscie: wywolaj `electricity_solve` — rozwiazuje cale puzzle automatycznie
- Automatyczny solver:
  1. Resetuje plansze
  2. Pobiera i analizuje obrazy (aktualny stan vs cel) metoda pikselowa
  3. Oblicza ile rotacji potrzeba dla kazdego pola
  4. Wysyla wszystkie rotacje do API
  5. Weryfikuje stan koncowy
- Jesli solver zglasza niezgodnosci, uzyj `electricity_reset` do ponownej analizy i `electricity_rotate(field)` do recznej korekty
- Format pola: "AxB", np. "2x3" (kolumna x wiersz)
- Kazda rotacja obraca pole o 90 stopni w prawo
- Flaga pojawia sie w odpowiedzi z API po ostatniej prawidlowej rotacji
