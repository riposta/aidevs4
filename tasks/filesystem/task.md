## Zadanie praktyczne

Twoje zadanie polega na logicznym uporządkowaniu notatek Natana w naszym wirtualnym file systemie. Potrzebujemy dowiedzieć się, które miasta brały udział w handlu, jakie osoby odpowiadały za ten handel w konkretnych miastach oraz które towary były przez kogo sprzedawane.

Dokładny opis potrzebnej nam struktury znajdziesz poniżej.

Nazwa zadania to: **filesystem**

Wszystkie operacje wykonujesz przez /verify/

Link do notatek Natana: https://hub.ag3nts.org/dane/natan\_notes.zip

Podgląd utworzonego systemu plików: https://hub.ag3nts.org/filesystem\_preview.html

Na początek warto wywołać przez API funkcję 'help':

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "filesystem",
  "answer": {
    "action": "help"
  }
}
```

W udostępnionym API znajdziesz funkcje do tworzenia plików i katalogów, usuwania ich, listowania katalogów oraz dwie funkcje specjalne:

- **reset** - czyści cały filesystem (usuwa wszystkie pliki)
- **done** - wysyła utworzoną strukturę danych do Centrali w celu weryfikacji zadania.

### Komunikacja z API

Możesz wysyłać do API pojedyncze instrukcje lub wykonać wiele operacji hurtowo.

Przykładowo, utworzenie 2 plików może wyglądać tak:

Zapytanie 1:

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "filesystem",
  "answer": {
    "action": "createFile",
    "path": "/plik1",
    "content": "Test1"
  }
}
```

Zapytanie 2:

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "filesystem",
  "answer": {
    "action": "createFile",
    "path": "/plik2",
    "content": "Test2"
  }
}
```

Możesz także wykorzystać **batch\_mode** i wysłać wszystko razem - dzięki tej funkcji, możliwe jest utworzenie całego filesystemu w jednym requeście.

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "filesystem",
  "answer": [
    {
      "action": "createFile",
      "path": "/plik1",
      "content": "Test1"
    },
    {
      "action": "createFile",
      "path": "/plik2",
      "content": "Test2"
    }
  ]
}
```

### Oto nasze wymagania

- Potrzebujemy trzech katalogów: `/miasta`, `/osoby` oraz `/towary`
- W katalogu `/miasta` mają znaleźć się pliki o nazwach (w mianowniku) takich jak miasta opisywane przez Natana. W środku tych plików powinna być struktura JSON z towarami, jakie potrzebuje to miasto i ile tego potrzebuje (bez jednostek).
- W katalogu `/osoby` powinny być pliki z notatkami na temat osób, które odpowiadają za handel w miastach. Każdy plik powinien zawierać imię i nazwisko jednej osoby i link (w formacie markdown) do miasta, którym ta osoba zarządza.
- Nazwa pliku w `/osoby` nie ma znaczenia, ale jeśli nazwiesz plik tak jak dana osoba (z podkreśleniem zamiast spacji), a w środku dasz wymagany link, to system też rozpozna, o co chodzi.
- W katalogu `/towary/` mają znajdować się pliki określające, które przedmioty są wystawione na sprzedaż. We wnętrzu każdego pliku powinien znajdować się link do miasta, które oferuje ten towar. Nazwa towaru to mianownik w liczbie pojedynczej, więc "koparka", a nie "koparki"

### Oczekiwany filesystem

Efektem Twojej pracy powinny być takie trzy katalogi wypełnione plikami.

> **Uwaga**: w nazwach plików nie używamy polskich znaków. Podobnie w tekstach w JSON.
