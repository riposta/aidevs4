import json
import re

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.foodwarehouse")


def _api(answer) -> dict:
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "foodwarehouse", "answer": answer})
    return resp.json()


def build_orders() -> str:
    """Build all warehouse orders: reset, fetch data, create orders with signatures, append items, done."""

    # Reset
    r = _api({"tool": "reset"})
    log.info("Reset: %s", r.get("message"))

    # Fetch food4cities
    resp = http.get("https://hub.ag3nts.org/dane/food4cities.json")
    cities_needs = resp.json()
    log.info("Cities: %s", list(cities_needs.keys()))

    # Get destinations for our cities
    dest_map = {}
    for city in cities_needs:
        r = _api({"tool": "database", "query": f"select * from destinations where name = '{city.capitalize()}'"})
        rows = r.get("rows", [])
        if rows:
            dest_map[city] = str(rows[0]["destination_id"])
            log.info("Destination %s: %s", city, dest_map[city])
        else:
            # Try exact case
            r2 = _api({"tool": "database", "query": f"select * from destinations where lower(name) = '{city.lower()}'"})
            rows2 = r2.get("rows", [])
            if rows2:
                dest_map[city] = str(rows2[0]["destination_id"])
                log.info("Destination %s: %s (fallback)", city, dest_map[city])
            else:
                log.error("No destination found for %s", city)

    # Get a transport user (role=2, active)
    r = _api({"tool": "database", "query": "select * from users where role = 2 and is_active = 1 limit 1"})
    user = r["rows"][0]
    user_id = user["user_id"]
    login = user["login"]
    birthday = user["birthday"]
    log.info("Creator: id=%d, login=%s, birthday=%s", user_id, login, birthday)

    # For each city: generate signature, create order, append items
    for city, needs in cities_needs.items():
        dest = dest_map.get(city)
        if not dest:
            log.error("Skipping %s - no destination", city)
            continue

        # Generate signature
        sig_r = _api({
            "tool": "signatureGenerator",
            "action": "generate",
            "login": login,
            "birthday": birthday,
            "destination": dest,
        })
        signature = sig_r.get("hash", "")
        log.info("%s: signature=%s", city, signature[:16])

        # Create order
        create_r = _api({
            "tool": "orders",
            "action": "create",
            "title": f"Dostawa dla {city.capitalize()}",
            "creatorID": user_id,
            "destination": dest,
            "signature": signature,
        })
        order_id = create_r.get("id") or create_r.get("orderID") or (create_r.get("order", {}) or {}).get("id")
        log.info("%s: order created id=%s code=%s", city, order_id, create_r.get("code"))

        if not order_id:
            log.error("Failed to create order for %s: %s", city, json.dumps(create_r)[:200])
            continue

        # Append items (batch)
        append_r = _api({
            "tool": "orders",
            "action": "append",
            "id": order_id,
            "items": needs,
        })
        log.info("%s: items appended code=%s", city, append_r.get("code"))

    # Verify
    done_r = _api({"tool": "done"})
    log.info("Done: %s", json.dumps(done_r, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(done_r))
    if flag_match:
        flag = flag_match.group(0)
        save_result("foodwarehouse", {"tool": "done"}, {"code": 0, "message": flag})
        return f"All orders created. Flag: {flag}"

    save_result("foodwarehouse", {"tool": "done"}, done_r)
    return f"Done: {json.dumps(done_r, ensure_ascii=False)[:400]}"
