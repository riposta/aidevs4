## Zadanie praktyczne

Twoim zadaniem jest przechwycić i przeanalizować materiały z radiowego nasłuchu, a następnie przesłać do Centrali końcowy raport na temat odnalezionego miasta. W eterze panuje chaos: część komunikatów to zwykły szum, część to tekstowe transkrypcje, a czasem trafisz też na pliki binarne przekazane jako dane encodowane w Base64.

Nazwa zadania: **radiomonitoring**

Odpowiedź wysyłasz do: <https://hub.ag3nts.org/verify>

Cała komunikacja odbywa się przez **POST** na `/verify` w standardowym formacie:

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "radiomonitoring",
  "answer": {
    "action": "..."
  }
}
```

### Jak działa zadanie

Najpierw uruchamiasz sesję nasłuchu, potem wielokrotnie pobierasz kolejne przechwycone materiały, a na końcu wysyłasz raport końcowy.

#### 1. Start sesji

Na początku wywołaj:

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "radiomonitoring",
  "answer": {
    "action": "start"
  }
}
```

To przygotowuje sesję nasłuchu i ustawia pulę materiałów do odebrania.

#### 2. Nasłuchiwanie

Kolejne porcje materiału pobierasz przez:

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "radiomonitoring",
  "answer": {
    "action": "listen"
  }
}
```

W odpowiedzi możesz dostać jeden z dwóch głównych typów danych:

- tekstową transkrypcję komunikatu głosowego w polu `transcription`
- plik binarny opisany metadanymi i przekazany jako `attachment` w Base64

Przykład odpowiedzi tekstowej:

```json
{
  "code": 100,
  "message": "Signal captured.",
  "transcription": "fragment przechwyconej rozmowy radiowej"
}
```

Przykład odpowiedzi z plikiem:

```json
{
  "code": 100,
  "message": "Signal captured.",
  "meta": "application/json",
  "attachment": "BASE64...",
  "filesize": 12345
}
```

Zwróć uwagę na kilka rzeczy:

- nie każda odpowiedź będzie przydatna, bo część materiału to zwykły radiowy szum
- pliki binarne mogą mieć sensowną zawartość, ale mogą też być kosztowne w analizie
- zakodowanie binarki w Base64 dodatkowo zwiększa rozmiar danych, więc bezpośrednie przekazanie całości do LLM-a może być bardzo drogie!
- rozsądne rozwiązanie zwykle zaczyna się od decyzji programistycznej: co da się odsiać, co zdekodować i przeanalizować lokalnie, a co rzeczywiście wymaga modelu

Gdy materiał się skończy, system poinformuje Cię, że masz już wystarczająco dużo danych do analizy.

### Co musisz ustalić

Na podstawie zebranych materiałów przygotuj końcowy raport zawierający:

- `cityName` - jak nazywa się miasto, na które mówią "Syjon"?
- `cityArea` - powierzchnię miasta zaokrągloną do dwóch miejsc po przecinku
- `warehousesCount` - liczbę magazynów jaka jest na Syjonie
- `phoneNumber` - numer telefonu osoby kontaktowej z miasta Syjon

Ważna uwaga dotycząca `cityArea`:

- wynik musi mieć dokładnie dwa miejsca po przecinku
- chodzi o prawdziwe matematyczne zaokrąglenie, a nie o obcięcie wartości
- format końcowy ma wyglądać jak `12.34`

#### 3. Wysłanie raportu końcowego

Gdy ustalisz wszystkie dane, wyślij:

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "radiomonitoring",
  "answer": {
    "action": "transmit",
    "cityName": "NazwaMiasta",
    "cityArea": "12.34",
    "warehousesCount": 321,
    "phoneNumber": "123456789"
  }
}
```

### Praktyczna wskazówka

To zadanie jest przede wszystkim ćwiczeniem z mądrego routingu danych. Podczas nasłuchiwania możesz otrzymywać DUŻE porcje danych binarnych. Wrzucenie takich danych bezpośrednio do modelu językowego może wygenerować bardzo duże koszty. W praktyce przyda Ci się programistyczny router, który najpierw oceni, z jakim materiałem ma do czynienia, a dopiero potem zdecyduje, czy coś analizować kodem, zdekodować lokalnie, odfiltrować jako mało istotne, czy dopiero skierować do odpowiednio dobranego modelu. Być może warto też użyć różnych modeli do różnych typów danych.

Najbardziej opłacalne podejście do tego zadania to nie "jeden wielki prompt", tylko sensowny pipeline:

- odbierasz materiał
- rozpoznajesz, czy to tekst, szum czy binarka
- dla binarki podejmujesz decyzję, czy analizować ją kodem, zdekodować lokalnie, czy dopiero potem przekazać dalej
- wybrane, wartościowe dane kierujesz do odpowiednio dobranego modelu

Jeśli dobrze rozplanujesz taki router, ograniczysz liczbę tokenów i koszt całej operacji, a właśnie to jest tutaj jednym z najważniejszych celów.
