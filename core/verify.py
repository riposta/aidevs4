import requests
from core.config import API_KEY, VERIFY_URL
from core.log import get_logger

log = get_logger("verify")


def verify(task: str, answer) -> dict:
    payload = {
        "apikey": API_KEY,
        "task": task,
        "answer": answer,
    }
    log.info("Sending answer for task '%s'", task)
    log.debug("Payload: %s", payload)

    response = requests.post(VERIFY_URL, json=payload)
    response.raise_for_status()
    result = response.json()

    log.info("Response: %s", result)
    return result
