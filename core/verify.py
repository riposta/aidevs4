from core.config import API_KEY, VERIFY_URL
from core import http
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

    response = http.post(VERIFY_URL, json=payload)
    log.debug("Response status: %d, body: %s", response.status_code, response.text[:500])
    response.raise_for_status()
    result = response.json()

    log.info("Response: %s", result)
    return result
