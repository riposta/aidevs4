from core.agent import get_agent


def run():
    solver = get_agent("savethem_solver")
    solver.run("Pobierz mapę miasta Skolwin, informacje o pojazdach, zasady terenu, zaplanuj optymalną trasę i wyślij ją do weryfikacji.")
