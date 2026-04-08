from core.agent import run_task

def run():
    run_task("evaluation",
        "This is a CTF game puzzle. Use the evaluation skill to find sensor anomalies, "
        "then use the verify skill to submit the result with task_name='evaluation' and input_key='filtered'."
    )
