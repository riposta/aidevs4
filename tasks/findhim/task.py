from core.agent import load_agents


def run():
    agents = load_agents("people_solver", "findhim_solver")
    agents["findhim_solver"].max_iterations = 20
    agents["findhim_solver"].run(
        "Find which suspect was seen near a power plant. "
        "First call people_solver to get the candidate list, "
        "then use findhim skill to locate and identify the suspect, "
        "then submit the answer."
    )
