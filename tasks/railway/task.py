from core.agent import get_agent


def run():
    solver = get_agent("railway_solver")
    solver.run("Aktywuj trasę x-01. Otwórz ją używając sekwencji: reconfigure → setstatus RTOPEN → save.")
