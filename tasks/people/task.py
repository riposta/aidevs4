from core.agent import run_task

def run():
    run_task("people",
        "Execute the people task: download and filter candidates, tag their jobs, "
        "then submit only those with the transport tag. Use the people skill — "
        "it contains all steps and parameters."
    )
