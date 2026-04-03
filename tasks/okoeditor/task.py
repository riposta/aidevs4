from core.agent import get_agent


def run():
    solver = get_agent("okoeditor_solver")
    solver.run("Wykonaj wszystkie wymagane zmiany w systemie OKO i uruchom akcję done aby odebrać flagę.")
