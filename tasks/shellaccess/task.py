from core.agent import get_agent


def run():
    solver = get_agent("shellaccess_solver")
    solver.max_iterations = 25
    solver.run(
        "Explore the remote server's /data directory using shell commands. "
        "Find logs mentioning Rafał — determine the date his body was found, the city, and GPS coordinates. "
        "The meeting date is ONE DAY BEFORE Rafał was found. "
        "When you have all info, print the JSON using echo with EXACT format: "
        '{"date":"YYYY-MM-DD","city":"name","longitude":float,"latitude":float}. '
        "longitude/latitude must be numbers, not strings. System auto-detects correctness."
    )
