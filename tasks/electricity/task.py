from core.agent import get_agent


def run():
    solver = get_agent("electricity_solver")
    solver.run("Rozwiąż puzzle elektryczne. Doprowadź prąd do wszystkich elektrowni.")
