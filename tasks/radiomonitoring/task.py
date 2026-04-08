from core.agent import get_agent


def run():
    solver = get_agent("radiomonitoring_solver")
    solver.run(
        "Rozpocznij nasłuch radiowy, zbierz wszystkie sygnały, przeanalizuj je "
        "i ustal: jakie miasto kryje się pod nazwą Syjon, jaka jest jego powierzchnia, "
        "ile ma magazynów i jaki jest numer telefonu osoby kontaktowej. "
        "Następnie wyślij raport końcowy."
    )
