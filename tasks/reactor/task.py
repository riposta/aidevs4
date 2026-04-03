from core.agent import get_agent


def run():
    solver = get_agent("reactor_solver")
    solver.run("Przeprowadź robota przez reaktor do punktu docelowego. Użyj narzędzia do nawigacji.")
