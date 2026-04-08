import json

from core.log import get_logger
from core.verify import verify as _verify

log = get_logger("tools.shellaccess")


def run_shell_cmd(cmd: str) -> str:
    """Execute a shell command on the remote server and return the output."""
    log.info("Executing: %s", cmd)
    try:
        result = _verify("shellaccess", {"cmd": cmd})
        output = json.dumps(result, ensure_ascii=False)
        log.info("Output: %s", output[:500])
        return output
    except Exception as e:
        log.error("Command failed: %s", e)
        # Try to extract server error message from response body
        error_detail = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                body = e.response.json()
                error_detail = body.get("message", error_detail)
            except Exception:
                pass
        return f"Error: {error_detail}. Try a simpler command (e.g. fewer lines, pipe to head)."
