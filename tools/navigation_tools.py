import json
import time
from heapq import heappush, heappop

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put, store_get
from core.result import save_result
from core import http, event_log

log = get_logger("tools.navigation")

BASE_URL = "https://hub.ag3nts.org/api"

VEHICLES = {
    "rocket": {"fuel": 1.0, "food": 0.1, "water": False},
    "car": {"fuel": 0.7, "food": 1.0, "water": False},
    "horse": {"fuel": 0.0, "food": 1.6, "water": True},
    "walk": {"fuel": 0.0, "food": 2.5, "water": True},
}

TREE_FUEL_PENALTY = 0.2


# === Reactor functions ===


def _send_command(command: str) -> dict:
    """Send a command to the reactor API and return the response."""
    payload = {
        "apikey": API_KEY,
        "task": "reactor",
        "answer": {"command": command},
    }
    resp = http.post(VERIFY_URL, json=payload)
    return resp.json()


def _simulate_block(block: dict) -> dict:
    """Simulate one step of block movement."""
    top = block["top_row"]
    bottom = block["bottom_row"]
    direction = block["direction"]

    if direction == "up":
        if top - 1 < 1:
            return {"col": block["col"], "top_row": top + 1, "bottom_row": bottom + 1, "direction": "down"}
        return {"col": block["col"], "top_row": top - 1, "bottom_row": bottom - 1, "direction": "up"}
    else:
        if bottom + 1 > 5:
            return {"col": block["col"], "top_row": top - 1, "bottom_row": bottom - 1, "direction": "up"}
        return {"col": block["col"], "top_row": top + 1, "bottom_row": bottom + 1, "direction": "down"}


def _is_col_safe(blocks: list, col: int) -> bool:
    """Check if a column is safe for the robot at row 5."""
    for b in blocks:
        if b["col"] == col and b["bottom_row"] == 5:
            return False
    return True


def _format_board(state: dict) -> str:
    """Format board state for logging."""
    board = state.get("board", [])
    lines = []
    for row in board:
        lines.append(" ".join(row))
    return "\n".join(lines)


def navigate_reactor() -> str:
    """Navigate the robot through the reactor to the goal position using an algorithmic approach."""
    # Start the game
    state = _send_command("start")
    log.info("Game started. Board:\n%s", _format_board(state))
    event_log.emit("system", agent="reactor", content="Game started")

    max_steps = 200
    steps = 0
    commands_log = []

    retries = 0
    max_retries = 10

    while not state.get("reached_goal", False) and steps < max_steps:
        # Check for success (code=0 with flag)
        if state.get("code") == 0 and "player" not in state:
            flag_msg = state.get("message", "")
            log.info("Goal reached in %d steps! Flag: %s", steps, flag_msg)
            event_log.emit("system", agent="reactor", content=f"Goal reached! {flag_msg}")
            save_result("reactor", {"commands": commands_log}, {"code": 0, "message": flag_msg})
            store_put("reactor_result", json.dumps(flag_msg, ensure_ascii=False))
            return f"Robot reached the goal in {steps} steps. Commands: {', '.join(commands_log)}. Result: {flag_msg}"

        # Check for crash/invalid state
        if "player" not in state or "blocks" not in state:
            msg = state.get("message", "Unknown error")
            log.error("Crash at step %d: %s | Full response: %s", steps, msg, json.dumps(state)[:300])
            event_log.emit("error", agent="reactor", content=f"Step {steps}: {msg}")
            retries += 1
            if retries > max_retries:
                return f"Failed after {max_retries} retries"
            state = _send_command("start")
            commands_log = []
            steps = 0
            continue

        player_col = state["player"]["col"]
        blocks = state["blocks"]

        # Simulate next state of blocks (they move with every command)
        next_blocks = [_simulate_block(b) for b in blocks]

        # Decision logic
        target_col = player_col + 1  # we want to move right

        right_safe = _is_col_safe(next_blocks, target_col)
        current_safe = _is_col_safe(next_blocks, player_col)

        # Also check 2 steps ahead for right move - will the target col be safe to stay in?
        next_next_blocks = [_simulate_block(b) for b in next_blocks]
        right_safe_next = _is_col_safe(next_next_blocks, target_col)

        if right_safe and right_safe_next:
            command = "right"
        elif right_safe and not right_safe_next:
            # Moving right lands in danger next step - only do it if we can move right again from there
            next_next_next = [_simulate_block(b) for b in next_next_blocks]
            right_right_safe = _is_col_safe(next_next_next, target_col + 1)
            if right_right_safe:
                command = "right"
            elif current_safe:
                command = "wait"
            else:
                command = "right"  # forced - current col also unsafe
        elif current_safe:
            command = "wait"
        else:
            command = "left"

        log.info("Step %d: player at col %d, command=%s (right_safe=%s, current_safe=%s, right_safe_next=%s)",
                 steps + 1, player_col, command, right_safe, current_safe, right_safe_next)

        state = _send_command(command)
        commands_log.append(command)
        steps += 1

        log.info("Response code=%s, reached_goal=%s, board:\n%s",
                 state.get("code"), state.get("reached_goal"), _format_board(state))

    if state.get("reached_goal", False):
        flag_msg = state.get("message", "")
        log.info("Goal reached in %d steps! Message: %s", steps, flag_msg)
        event_log.emit("system", agent="reactor", content=f"Goal reached! {flag_msg}")
        save_result("reactor", {"commands": commands_log}, {"code": 0, "message": flag_msg})
        store_put("reactor_result", json.dumps(flag_msg, ensure_ascii=False))
        return f"Robot reached the goal in {steps} steps. Commands: {', '.join(commands_log)}. Result: {flag_msg}"
    else:
        return f"Failed to reach goal after {steps} steps. Last commands: {', '.join(commands_log[-20:])}"


# === Savethem functions ===


def _query_api(endpoint: str, query: str) -> dict:
    resp = http.post(f"{BASE_URL}/{endpoint}", json={"apikey": API_KEY, "query": query})
    return resp.json()


def gather_intel() -> str:
    """Fetch map, vehicle info, and terrain rules from the API."""
    # Get map
    map_data = _query_api("maps", "Skolwin")
    grid = map_data.get("map", [])

    # Get vehicle details
    vehicles = {}
    for v in ["rocket", "horse", "walk", "car"]:
        vdata = _query_api("wehicles", v)
        vehicles[v] = {
            "fuel": vdata["consumption"]["fuel"],
            "food": vdata["consumption"]["food"],
            "note": vdata.get("note", ""),
        }

    # Get terrain rules
    books_terrain = _query_api("books", "terrain types obstacles rocks trees water")
    books_water = _query_api("books", "water crossing walking swimming")
    books_fuel = _query_api("books", "trees fuel burn penalty")

    # Store data
    intel = {
        "grid": grid,
        "vehicles": vehicles,
        "terrain_notes": [n["content"] for n in books_terrain.get("notes", [])],
        "water_notes": [n["content"] for n in books_water.get("notes", [])],
        "fuel_notes": [n["content"] for n in books_fuel.get("notes", [])],
    }
    store_put("savethem_intel", json.dumps(intel, ensure_ascii=False))

    # Find S and G
    start = goal = None
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell == "S":
                start = (r, c)
            elif cell == "G":
                goal = (r, c)

    text_map = map_data.get("text", "")
    log.info("Map:\n%s", text_map)
    log.info("Start: %s, Goal: %s", start, goal)
    log.info("Vehicles: %s", {k: {kk: vv for kk, vv in v.items() if kk != 'note'} for k, v in vehicles.items()})

    return (f"Intel gathered. Map 10x10, Start={start}, Goal={goal}. "
            f"Vehicles: rocket(fuel=1.0,food=0.1,no water), car(fuel=0.7,food=1.0,no water), "
            f"horse(fuel=0,food=1.6,can water), walk(fuel=0,food=2.5,can water). "
            f"Trees(T): +0.2 fuel penalty. Rocks(R): impassable. Water(W): only horse/walk.")


def plan_route() -> str:
    """Compute optimal route using pathfinding and resource optimization."""
    raw = store_get("savethem_intel")
    if not raw:
        return "Error: no intel data. Call gather_intel first."

    intel = json.loads(raw)
    grid = intel["grid"]
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0

    # Find S and G
    start = goal = None
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == "S":
                start = (r, c)
            elif grid[r][c] == "G":
                goal = (r, c)

    if not start or not goal:
        return "Error: could not find S or G on map"

    log.info("Planning route from %s to %s", start, goal)

    # Directions
    DIRS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}

    # Strategy: try all combinations of vehicle + dismount point
    # State: (row, col, mode) where mode is "vehicle" or "walk"
    # Resources: fuel and food, both start at 10

    best_route = None
    best_cost = float("inf")  # total resource usage

    for vehicle_name in ["rocket", "car", "horse", "walk"]:
        v = VEHICLES[vehicle_name]
        can_water_v = v["water"]

        # BFS/Dijkstra over states: (row, col, is_walking)
        # Cost: (fuel_used, food_used)
        # State: (fuel_used, food_used, row, col, is_walking, path)

        # Use priority queue with total_cost = fuel + food as priority
        # State: (total_cost, fuel_used, food_used, row, col, is_walking, path)
        pq = []
        visited = {}  # (row, col, is_walking) -> best (fuel, food)

        initial_walking = vehicle_name == "walk"
        heappush(pq, (0.0, 0.0, 0.0, start[0], start[1], initial_walking, [vehicle_name]))

        while pq:
            total_cost, fuel_used, food_used, r, c, walking, path = heappop(pq)

            if fuel_used > 10.0001 or food_used > 10.0001:
                continue

            state_key = (r, c, walking)
            if state_key in visited:
                prev_f, prev_fd = visited[state_key]
                if fuel_used >= prev_f and food_used >= prev_fd:
                    continue
            visited[state_key] = (fuel_used, food_used)

            # Goal reached
            if (r, c) == goal:
                if total_cost < best_cost:
                    best_cost = total_cost
                    best_route = path
                    log.info("Found route with %s: %d steps, fuel=%.1f, food=%.1f",
                             vehicle_name, len(path) - 1, fuel_used, food_used)
                continue

            # Try dismount (if in vehicle and not already walking)
            if not walking and vehicle_name != "walk":
                new_path = path + ["dismount"]
                st = (r, c, True)
                new_fuel = fuel_used
                new_food = food_used
                if st not in visited or new_fuel < visited[st][0] or new_food < visited[st][1]:
                    heappush(pq, (new_fuel + new_food, new_fuel, new_food, r, c, True, new_path))

            # Try moves
            for dir_name, (dr, dc) in DIRS.items():
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    cell = grid[nr][nc]

                    # Check passability
                    if cell == "R":
                        continue

                    if cell == "W":
                        if walking:
                            pass  # walk can cross water
                        elif can_water_v and not walking:
                            pass  # horse can cross water
                        else:
                            continue  # vehicle can't cross water

                    # Calculate costs
                    if walking:
                        move_fuel = 0.0
                        move_food = 2.5
                    else:
                        move_fuel = v["fuel"]
                        move_food = v["food"]
                        if cell == "T":
                            move_fuel += TREE_FUEL_PENALTY

                    new_fuel = fuel_used + move_fuel
                    new_food = food_used + move_food

                    if new_fuel > 10.0001 or new_food > 10.0001:
                        continue

                    new_path = path + [dir_name]
                    new_total = new_fuel + new_food
                    heappush(pq, (new_total, new_fuel, new_food, nr, nc, walking, new_path))

    if best_route:
        store_put("savethem_answer", json.dumps(best_route, ensure_ascii=False))
        log.info("Optimal route: %s", best_route)
        return f"Optimal route found ({len(best_route)-1} moves): {best_route}. Stored as 'savethem_answer'."
    else:
        return "Error: no valid route found within resource constraints"
