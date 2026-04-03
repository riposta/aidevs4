import json
import re

import requests

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.okoeditor")

OKO_URL = "https://oko.ag3nts.org"

# Known IDs from OKO system
SKOLWIN_ID = "380792b2c86d9c5be670b3bde48e187b"
PMR_ID = "351c0d9c90d66b4c040fff1259dd191d"


def _oko_update(page: str, entry_id: str, **kwargs) -> dict:
    """Send an update command to the OKO API."""
    answer = {
        "page": page,
        "id": entry_id,
        "action": "update",
        **kwargs,
    }
    payload = {"apikey": API_KEY, "task": "okoeditor", "answer": answer}
    log.info("Updating %s/%s: %s", page, entry_id, json.dumps(kwargs, ensure_ascii=False)[:200])
    resp = http.post(VERIFY_URL, json=payload)
    result = resp.json()
    log.info("Result: %s", json.dumps(result, ensure_ascii=False)[:300])
    return result


def _browse_oko():
    """Login and browse OKO to find current state and IDs."""
    session = requests.Session()
    session.post(f"{OKO_URL}/", data={
        "action": "login",
        "login": "Zofia",
        "password": "Zofia2026!",
        "access_key": API_KEY,
    }, allow_redirects=True)

    info = {}
    for page in ["", "zadania", "notatki"]:
        url = f"{OKO_URL}/{page}" if page else f"{OKO_URL}/"
        resp = session.get(url)
        entries = re.findall(
            r'href="/' + (page or 'incydenty') + r'/([a-f0-9]+)".*?<strong>(.+?)</strong>',
            resp.text, re.DOTALL
        )
        info[page or "incydenty"] = entries

    return info


def execute_oko_edits() -> str:
    """Execute all required OKO system edits: reclassify Skolwin, mark task done, add Komarowo incident."""
    results = []

    # First browse to see current state
    info = _browse_oko()
    log.info("Current incydenty: %s", [(eid, t.strip()) for eid, t in info.get("incydenty", [])])
    log.info("Current zadania: %s", [(eid, t.strip()) for eid, t in info.get("zadania", [])])

    # Find Skolwin incident and task IDs
    skolwin_incident_id = None
    skolwin_task_id = None
    redirect_incident_id = None

    for eid, title in info.get("incydenty", []):
        t = title.strip()
        if "Skolwin" in t or "skolwin" in t.lower():
            skolwin_incident_id = eid
            log.info("Found Skolwin incident: %s - %s", eid, t)
        elif "PMR" in t or "emisja" in t.lower():
            redirect_incident_id = eid

    for eid, title in info.get("zadania", []):
        t = title.strip()
        if "Skolwin" in t.lower() or "skolwin" in t.lower():
            skolwin_task_id = eid
            log.info("Found Skolwin task: %s - %s", eid, t)

    if not skolwin_incident_id:
        skolwin_incident_id = SKOLWIN_ID
    if not skolwin_task_id:
        skolwin_task_id = SKOLWIN_ID
    if not redirect_incident_id:
        redirect_incident_id = PMR_ID

    # 1. Reclassify Skolwin incident from MOVE03 (vehicle+human) to MOVE04 (animals)
    r1 = _oko_update(
        "incydenty", skolwin_incident_id,
        title="MOVE04 Trudne do klasyfikacji ruchy nieopodal miasta Skolwin",
        content="Czujniki zarejestrowały szybko poruszające się obiekty w pobliżu rzeki nieopodal Skolwina. Po analizie nagrań ustalono, że ruch był powodowany przez dzikie zwierzęta, najprawdopodobniej bobry, które przemieszczały się wzdłuż brzegu rzeki. Nie stwierdzono obecności ludzi ani pojazdów w okolicy.",
    )
    results.append(f"1. Reclassify Skolwin: {r1.get('message', r1)}")

    # 2. Mark Skolwin task as done with animal content
    r2 = _oko_update(
        "zadania", skolwin_task_id,
        done="YES",
        content="Analiza nagrań z okolic Skolwina zakończona. Zarejestrowany ruch pochodził od zwierząt - widziano tam bobry poruszające się w pobliżu rzeki. Brak oznak obecności ludzi lub pojazdów.",
    )
    results.append(f"2. Skolwin task done: {r2.get('message', r2)}")

    # 3. Change an existing incident to be about Komarowo human movement
    r3 = _oko_update(
        "incydenty", redirect_incident_id,
        title="MOVE01 Wykryto ruch ludzi w okolicach miasta Komarowo",
        content="System wykrył ruch ludzi w okolicach niezamieszkałego miasta Komarowo. Czujniki zarejestrowały kilka postaci poruszających się w pobliżu opuszczonych budynków. Ruch miał charakter zorganizowany i wymaga dalszej obserwacji.",
    )
    results.append(f"3. Komarowo incident: {r3.get('message', r3)}")

    summary = "\n".join(results)
    log.info("All edits completed:\n%s", summary)
    store_put("oko_edits_done", "true")
    return f"All 3 edits completed:\n{summary}"


def finalize_oko() -> str:
    """Run the done action to verify all edits and get the flag."""
    payload = {
        "apikey": API_KEY,
        "task": "okoeditor",
        "answer": {"action": "done"},
    }
    resp = http.post(VERIFY_URL, json=payload)
    result = resp.json()
    log.info("Done result: %s", json.dumps(result, ensure_ascii=False))

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(result))
    if flag_match:
        flag = flag_match.group(0)
        save_result("okoeditor", {"action": "done"}, {"code": 0, "message": flag})
        return f"Flag: {flag}"

    save_result("okoeditor", {"action": "done"}, result)
    return f"Done result: {json.dumps(result, ensure_ascii=False)}"
