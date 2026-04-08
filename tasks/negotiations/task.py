from core.agent import run_task


def run():
    run_task("negotiations",
        "Pobierz dane CSV z przedmiotami i miastami, uruchom serwer API do przeszukiwania danych, "
        "wystaw go publicznie i zgłoś narzędzia do centrali. Następnie poczekaj na wynik i odbierz flagę."
    )
