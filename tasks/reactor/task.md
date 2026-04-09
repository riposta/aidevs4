# Task: reactor

## Opis
Przeprowadz robota przez reaktor do punktu docelowego. Robot musi unikac przeszkod (blokow) ktore poruszaja sie w reaktorze. Narzedzie nawigacji automatycznie analizuje pozycje blokow, przewiduje ich ruchy i wybiera bezpieczne komendy (right/wait/left).

## API
- Endpoint: https://hub.ag3nts.org/verify
- Task name: reactor
- Answer format: nawigacja odbywa sie przez API gry (komendy start/right/left/wait), flaga pojawia sie po dotarciu do celu

## Wskazówki
- Uzyj `navigate_reactor` — narzedzie wykonuje caly algorytm nawigacji automatycznie
- Robot porusza sie w prawo (cel jest po prawej stronie planszy)
- Bloki poruszaja sie gora-dol i stanowia przeszkody
- Narzedzie analizuje bezpieczenstwo kolumn na 2 kroki do przodu
- Jesli robot utknie lub zginie, gra restartuje sie automatycznie
- Flaga jest zwracana przez API po dotarciu do celu
