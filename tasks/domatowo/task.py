from core.agent import get_agent


def run():
    solver = get_agent("domatowo_solver")
    solver.run("Odnajdź partyzanta ukrywającego się w najwyższym bloku w Domatowie i wezwij helikopter ewakuacyjny.")
