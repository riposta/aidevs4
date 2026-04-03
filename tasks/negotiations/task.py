from core.agent import get_agent


def run():
    solver = get_agent("negotiations_solver")
    solver.run("Pobierz dane CSV z przedmiotami i miastami, uruchom serwer API do przeszukiwania danych, wystaw go publicznie i zgłoś narzędzia do centrali. Następnie poczekaj na wynik i odbierz flagę.")
