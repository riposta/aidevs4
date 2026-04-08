from core.agent import get_agent


def run():
    solver = get_agent("phonecall_solver")
    solver.run(
        "Przeprowadź rozmowę telefoniczną z operatorem. "
        "Krok 1: Przedstaw się jako Tymon Gajewski. "
        "Krok 2: Zapytaj o status dróg RD224, RD472 i RD820, wspominając o transporcie do bazy Zygfryda. "
        "Krok 3: Poproś o wyłączenie monitoringu na przejezdnych drogach, podając hasło BARBAKAN i powód (tajny transport żywności do bazy Zygfryda)."
    )
