## Zadanie praktyczne

Twoim zadaniem jest zbudowanie agenta, który wytyczy optymalną trasę dla naszego posłańca, który podejmie negocjacje w mieście Skolwin. Niewiele wiemy na temat tego, jak wygląda teren, więc z pewnością na początku będziemy musieli zdobyć mapę. Musimy też zdecydować się na konkretny pojazd, którym wyruszymy z bazy. Jest ich do wyboru kilka. Myślę, że bez problemu znajdziesz informacje na ich temat. Każdy pojazd spala paliwo. Im szybciej się porusza, tym więcej paliwa zużywa. Jednocześnie nasz wysłannik potrzebuje prowiantu. Im dłużej trwa podróż, tym więcej będzie wymagał jedzenia. Trzeba więc odpowiednio rozplanować tę drogę w taki sposób, by poruszać się możliwie szybko, ale jednocześnie tak, aby wystarczyło nam jedzenia i paliwa na dotarcie do celu.

Tym razem nie dajemy Ci dostępu do konkretnych narzędzi, a jedynie do wyszukiwarki narzędzi, która pomoże Ci zdobyć informację o pozostałych narzędziach. Używasz jej jak poniżej:

Endpoint: https://hub.ag3nts.org/api/toolsearch

```json
{
  "apikey": "tutaj-twoj-klucz",
  "query": "I need notes about movement rules and terrain"
}
```

Uwaga: wszystkie narzędzia porozumiewają się tylko w języku angielskim!

Wszystkie znalezione narzędzia obsługuje się identycznie jak toolsearch, czyli wysyła się do nich parametr 'query' oraz własny apikey.

Twoim zadaniem jest wysłać do centrali optymalną trasę podróży dla naszego wysłannika.

**Zadanie nazywa się savethem**, a dane wysyłasz do /verify

```json
{
  "apikey": "tutaj-twoj-klucz",
  "task": "savethem",
  "answer": ["wehicle_name", "right", "right", "up", "down", "up","..."]
}
```

Tutaj znajdziesz podgląd trasy, którą pokonuje nasz człowiek:
https://hub.ag3nts.org/savethem\_preview.html

## Wskazówki

Co wiemy?

- wysłannik musi dotrzeć do miasta Skolwin
- pozyskane mapy zawsze mają wymiary 10x10 pól i zawierają rzeki, drzewa, kamienie itp.
- masz do dyspozycji 10 porcji jedzenia i 10 jednostek paliwa
- każdy ruch spala paliwo (no, chyba że idziesz pieszo) oraz jedzenie. Każdy pojazd ma własne parametry spalania zasobów.
- im szybciej się poruszasz, tym więcej spalasz paliwa, ale im wolniej idziesz, tym więcej konsumujesz prowiantu. Trzeba to dobrze rozplanować.
- w każdej chwili możesz wyjść z wybranego pojazdu i kontynuować podróż pieszo.
- narzędzie toolsearch może przyjąć zarówno zapytanie w języku naturalnym, jak i słowa kluczowe
- wszystkie narzędzia zwracane przez toolsearch przyjmują parametr "query" i odpowiadają w formacie JSON, zwracając zawsze 3 najlepiej dopasowane do zapytania wyniki (nie zwracają wszystkich wpisów!)
- jeśli dotrzesz do pola końcowego, zdobędziesz flagę i zaliczysz zadanie (flaga pojawi się zarówno na podglądzie, w API jak i w debugu do zadań)
