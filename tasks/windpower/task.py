from core.agent import get_agent


def run():
    solver = get_agent("windpower_solver")
    solver.run("Skonfiguruj turbinę wiatrową i zdobądź flagę. Użyj narzędzia do automatycznej konfiguracji.")
