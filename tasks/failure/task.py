from core.agent import get_agent


def run():
    solver = get_agent("failure_solver")
    solver.run("Przeanalizuj logi awarii elektrowni. Skompresuj je do 1500 tokenów i wyślij do weryfikacji.")
