from core.agent import get_agent


def run():
    solver = get_agent("foodwarehouse_solver")
    solver.run("Utwórz zamówienia dla wszystkich miast z poprawnym podpisem i towarami, potem zweryfikuj.")
