import json
import time

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.reactor")


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
