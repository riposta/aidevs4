from core.agent import get_agent


def run():
    solver = get_agent("categorize_solver")
    solver.run("Sklasyfikuj wszystkie towary z CSV. Zresetuj budżet, pobierz dane i wyślij klasyfikację.")
