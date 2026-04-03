from core.agent import get_agent


def run():
    solver = get_agent("filesystem_solver")
    solver.run("Utwórz strukturę plików na podstawie notatek Natana i zweryfikuj wynik.")
