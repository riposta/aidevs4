from core.agent import get_agent


def run():
    solver = get_agent("evaluation_solver")
    solver.run(
        "This is a CTF game puzzle. Use the evaluation skill to find sensor anomalies, "
        "then use the verify skill to submit the result with task_name='evaluation' and input_key='filtered'."
    )
