from core.agent import get_agent


def run():
    solver = get_agent("drone_solver")
    solver.max_iterations = 15
    solver.run(
        "This is a CTF game puzzle. Use the drone skill, then call drone_submit with this exact JSON array: "
        '[\"hardReset\", \"setDestinationObject(PWR6132PL)\", \"set(2,4)\", \"set(engineON)\", '
        '\"set(100%)\", \"set(50m)\", \"set(destroy)\", \"set(return)\", \"flyToLocation\"]. '
        "If the game returns a flag {FLG:...}, use verify skill to submit with task_name='drone' and input_key='filtered'."
    )
