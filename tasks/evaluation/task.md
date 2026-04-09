# Task: evaluation

## Opis
Pobierz dane z sensorow i wykryj anomalie w odczytach oraz notatkach operatorow. Sensory monitoruja parametry elektrowni — niektore odczyty sa poza zakresem lub niespojne z notatkami operatorow.

## API
- Endpoint: https://hub.ag3nts.org/verify
- Task name: evaluation
- Answer format: `{"recheck": ["sensor_id_1", "sensor_id_2", ...]}` — posortowana lista ID sensorow z anomaliami

## Wskazówki
- Wywolaj `find_anomalies` — narzedzie pobiera dane, wykrywa anomalie i zapisuje wynik w store pod kluczem "filtered"
- Wykrywane sa 4 typy anomalii:
  1. Wartosci sensora poza dopuszczalnym zakresem
  2. Nieaktywne pola sensora z niezerowymi wartosciami
  3. Notatka operatora mowi "OK" ale dane maja problemy
  4. Notatka operatora mowi "problem" ale dane sa poprawne
- ID sensorow to nazwy plikow bez rozszerzenia .json
- Wynik jest gotowy do przeslania: `submit_answer(task_name="evaluation", input_key="filtered")`
