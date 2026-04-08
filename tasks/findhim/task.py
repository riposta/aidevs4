from core.agent import run_task


def run():
    run_task("findhim",
        "Find which suspect was seen near a power plant. "
        "Use the findhim skill — it handles everything: downloading candidates, "
        "finding locations, identifying nearest powerplant, and getting access level. "
        "Then submit the answer with verify skill: task_name='findhim', input_key='answer'."
    )
