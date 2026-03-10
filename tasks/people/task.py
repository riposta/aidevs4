from core.agent import get_agent


def run():
    solver = get_agent("people_solver")
    solver.run(
        "Execute the people task: download and filter candidates, tag their jobs, "
        "then submit only those with the transport tag."
    )
