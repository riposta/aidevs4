import time
import requests
from core.log import get_logger

log = get_logger("http")

MAX_RETRIES = 10


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """HTTP request with exponential backoff for 429/5xx responses. Retries up to 10 times."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code == 429:
            if attempt == MAX_RETRIES:
                resp.raise_for_status()
            wait = 2 ** (attempt - 1)  # 1, 2, 4, 8, 16, 32, 64, 128, 256, 512
            log.warning("HTTP %d from %s, retry %d/%d in %ds", resp.status_code, url, attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            continue
        return resp
    return resp


def get(url: str, **kwargs) -> requests.Response:
    return request_with_retry("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request_with_retry("POST", url, **kwargs)
