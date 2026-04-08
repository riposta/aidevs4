import json
import math

import requests

from core import http
from core.config import API_KEY, HUB_URL
from core.log import get_logger
from core.store import store_get, store_put

log = get_logger("tools.geo")

LOCATION_URL = f"{HUB_URL}/api/location"
ACCESS_LEVEL_URL = f"{HUB_URL}/api/accesslevel"
LOCATIONS_URL = f"{HUB_URL}/data/{API_KEY}/findhim_locations.json"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _geocode_city(city_name: str) -> tuple[float, float] | None:
    """Geocode a Polish city using Nominatim."""
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{city_name}, Poland", "format": "json", "limit": 1},
        headers={"User-Agent": "aidevs-task/1.0"},
    )
    resp.raise_for_status()
    results = resp.json()
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None


def fetch_all_locations(input_key: str, output_key: str, plants_key: str) -> str:
    """Fetch GPS locations for all candidates and power plant data. One API round. Stores candidate locations under output_key, power plants under plants_key."""
    raw = store_get(input_key)
    if raw is None:
        return f"Error: no data found under '{input_key}'."

    candidates = json.loads(raw)
    log.info("Fetching locations for %d candidates", len(candidates))

    # Fetch power plants (once)
    resp = http.get(LOCATIONS_URL)
    resp.raise_for_status()
    plants = resp.json()["power_plants"]
    store_put(plants_key, json.dumps(plants, ensure_ascii=False))
    log.info("Fetched %d power plants into '%s'", len(plants), plants_key)

    # Fetch candidate locations
    results = []
    for person in candidates:
        name = person.get("name", "").strip()
        surname = person.get("surname", "").strip()
        if not name or not surname:
            continue

        payload = {"apikey": API_KEY, "name": name, "surname": surname}
        try:
            r = http.post(LOCATION_URL, json=payload)
            r.raise_for_status()
            data = r.json()
            locations = data if isinstance(data, list) else data.get("locations", data.get("message", []))
            if isinstance(locations, list):
                results.append({"person": person, "locations": locations})
                log.info("Got %d locations for %s %s", len(locations), name, surname)
        except Exception as e:
            log.error("Failed for %s %s: %s", name, surname, e)

    store_put(output_key, json.dumps(results, ensure_ascii=False))
    city_names = list(plants.keys())
    return f"Fetched locations for {len(results)} candidates into '{output_key}', {len(plants)} plants into '{plants_key}'. Power plant cities: {', '.join(city_names)}. Now provide GPS coordinates for these cities to find_nearest_powerplant."


def find_nearest_powerplant(input_key: str, plants_key: str, output_key: str) -> str:
    """Compare candidate locations with power plant coordinates using Haversine. Geocodes cities via Nominatim for precise coordinates."""
    raw = store_get(input_key)
    if raw is None:
        return f"Error: no data found under '{input_key}'."
    plants_raw = store_get(plants_key)
    if plants_raw is None:
        return f"Error: no data found under '{plants_key}'."

    entries = json.loads(raw)
    plants = json.loads(plants_raw)

    # Geocode all plant cities
    city_coords = {}
    for city in plants.keys():
        coords = _geocode_city(city)
        if coords:
            city_coords[city] = {"lat": coords[0], "lon": coords[1]}
            log.info("Geocoded %s: %s", city, coords)
        else:
            log.warning("Failed to geocode %s", city)

    log.info("Power plants: %s, geocoded: %s", list(plants.keys()), list(city_coords.keys()))

    # Collect best match per person (closest plant)
    person_matches = {}

    for entry in entries:
        person = entry["person"]
        pkey = f"{person.get('name', '').strip()} {person.get('surname', '').strip()}"
        for loc in entry["locations"]:
            if isinstance(loc, dict):
                lat = loc.get("lat", loc.get("latitude", 0))
                lon = loc.get("lon", loc.get("lng", loc.get("longitude", 0)))
            elif isinstance(loc, (list, tuple)) and len(loc) >= 2:
                lat, lon = loc[0], loc[1]
            else:
                continue

            for city, coord in city_coords.items():
                clat = coord.get("lat", 0)
                clon = coord.get("lon", 0)
                dist = _haversine_km(lat, lon, clat, clon)
                if dist < 50:
                    prev = person_matches.get(pkey)
                    if prev is None or dist < prev["distance_km"]:
                        birth_year = None
                        bd = person.get("born", "") or person.get("birthDate", "") or person.get("birth_date", "")
                        if not bd:
                            log.warning("No birth date for %s, keys: %s", pkey, list(person.keys()))
                        if bd:
                            try:
                                birth_year = int(bd.split("-")[0])
                            except ValueError:
                                pass
                        person_matches[pkey] = {
                            "name": person.get("name", "").strip(),
                            "surname": person.get("surname", "").strip(),
                            "birthYear": birth_year,
                            "powerPlant": plants.get(city, {}).get("code", "UNKNOWN"),
                            "city": city,
                            "distance_km": round(dist, 2),
                        }
                        log.info("Match: %s near %s (%s), %.2f km", pkey, city,
                                 person_matches[pkey]["powerPlant"], dist)

    if not person_matches:
        return "No candidates found near any power plant."

    matches = sorted(person_matches.values(), key=lambda m: m["distance_km"])
    store_put(output_key, json.dumps(matches, ensure_ascii=False))
    summary = "; ".join(f"{m['name']} {m['surname']} near {m['city']} ({m['powerPlant']}, {m['distance_km']}km)" for m in matches)
    return f"Found {len(matches)} candidates near power plants, stored in '{output_key}': {summary}"


def fetch_access_levels(input_key: str, output_key: str) -> str:
    """Fetch access levels for all matched candidates. Reads match list from input_key, stores enriched list under output_key."""
    raw = store_get(input_key)
    if raw is None:
        return f"Error: no data found under '{input_key}'."

    matches = json.loads(raw)
    results = []
    for match in matches:
        payload = {
            "apikey": API_KEY,
            "name": match["name"],
            "surname": match["surname"],
            "birthYear": match["birthYear"],
        }
        try:
            log.info("Requesting access level, payload: %s", payload)
            resp = http.post(ACCESS_LEVEL_URL, json=payload)
            log.info("Response %d: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
            data = resp.json()
            log.info("Access level for %s %s: %s", match["name"], match["surname"], data)

            access_level = data if isinstance(data, (int, str)) else data.get("accessLevel", data.get("access_level", data.get("message", data)))
            try:
                access_level = int(access_level)
            except (ValueError, TypeError):
                pass
        except Exception as e:
            log.error("Failed access level for %s %s: %s", match["name"], match["surname"], e)
            access_level = "unknown"

        results.append({
            "name": match["name"],
            "surname": match["surname"],
            "accessLevel": access_level,
            "powerPlant": match["powerPlant"],
            "city": match["city"],
            "distance_km": match["distance_km"],
        })

    store_put(output_key, json.dumps(results, ensure_ascii=False))
    summary = "; ".join(f"{r['name']} {r['surname']}: accessLevel={r['accessLevel']}, {r['powerPlant']} ({r['city']}, {r['distance_km']}km)" for r in results)
    return f"Access levels for {len(results)} candidates stored in '{output_key}': {summary}"


def select_answer(input_key: str, index: int, output_key: str) -> str:
    """Select one candidate from the enriched list by index and store as final answer."""
    raw = store_get(input_key)
    if raw is None:
        return f"Error: no data found under '{input_key}'."

    candidates = json.loads(raw)
    if index < 0 or index >= len(candidates):
        return f"Error: index {index} out of range (0-{len(candidates)-1})."

    selected = candidates[index]
    answer = {
        "name": selected["name"],
        "surname": selected["surname"],
        "accessLevel": selected["accessLevel"],
        "powerPlant": selected["powerPlant"],
    }
    store_put(output_key, json.dumps(answer, ensure_ascii=False))
    return f"Selected answer stored in '{output_key}': {json.dumps(answer, ensure_ascii=False)}"
