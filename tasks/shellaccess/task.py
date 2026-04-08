from core.agent import run_task


def run():
    run_task("shellaccess",
        "Explore the remote server's /data directory using shell commands. "
        "Find logs mentioning Rafał — determine the date his body was found, the city, and GPS coordinates. "
        "The meeting date is ONE DAY BEFORE Rafał was found. "
        "When you have all info, print the JSON using echo with EXACT format: "
        '{"date":"YYYY-MM-DD","city":"name","longitude":float,"latitude":float}. '
        "longitude/latitude must be numbers, not strings. System auto-detects correctness."
    )
