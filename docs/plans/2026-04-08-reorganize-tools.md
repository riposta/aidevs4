# Reorganize Tools by Category Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize 26 task-named tool files into 15 category-named files and update the skill loader to find tools across all files.

**Architecture:** First update `core/skill.py` to search ALL `tools/*_tools.py` files for functions (not just matching filename). Then create new category files by moving functions. Then update skill frontmatter `tools:` fields. Then delete old files. Then test.

**Tech Stack:** Python, existing core framework

---

## Task 1: Update skill loader to search all tool files

**Files:**
- Modify: `core/skill.py:62-83`

**Step 1: Change `Skill.from_markdown` to search all tool files**

Replace the tool loading logic in `from_markdown`. Instead of loading from one file `tools/<skill_name>_tools.py`, build a global tool registry from ALL `tools/*_tools.py` files and look up functions by name.

Current code (lines 70-73):
```python
# Load tools from tools/<skill_name>_tools.py
tools_py = TOOLS_DIR / f"{path.stem}_tools.py"
tool_fns = _load_tools_from_py(tools_py, tool_names) if tool_names else {}
```

New code:
```python
# Load tools by searching ALL tools/*_tools.py files
tool_fns = _find_tools(tool_names) if tool_names else {}
```

Add new function `_find_tools` before the `Skill` class:

```python
def _find_tools(tool_names: list[str]) -> dict[str, Callable]:
    """Find tool functions by name across all tools/*_tools.py files."""
    if not TOOLS_DIR.exists():
        return {}

    tools: dict[str, Callable] = {}
    remaining = set(tool_names)

    for py_path in sorted(TOOLS_DIR.glob("*_tools.py")):
        if not remaining:
            break
        found = _load_tools_from_py(py_path, list(remaining))
        tools.update(found)
        remaining -= set(found.keys())

    for name in remaining:
        log.warning("Tool '%s' not found in any tools/*_tools.py file", name)

    return tools
```

**Step 2: Verify loader still works**

Run: `python -c "from core.skill import load_skills; s = load_skills(['verify']); print(sorted(s['verify'].tool_fns.keys()))"`
Expected: `['load_result', 'submit_answer']`

Run: `python -c "from core.skill import load_skills; s = load_skills(['shellaccess']); print(sorted(s['shellaccess'].tool_fns.keys()))"`
Expected: `['run_shell_cmd']`

**Step 3: Verify full task still works**

Run: `python run.py electricity 2>/tmp/reorg_test.log; grep FLG /tmp/reorg_test.log | head -1`
Expected: Contains `{FLG:ROTATEIT}`

---

## Task 2: Create category tool files

Create 13 new category files by moving/merging functions from existing files. Do NOT delete old files yet (loader now searches all files, duplicates are OK temporarily).

**Files to create:**

### 2a: `tools/shell_tools.py`
Merge from: `tools/shellaccess_tools.py` + `tools/firmware_tools.py`

```python
import json

from core.log import get_logger
from core.store import store_put
from core.verify import verify as _verify
from core import http
from core.config import API_KEY, HUB_URL

log = get_logger("tools.shell")


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
        error_detail = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                body = e.response.json()
                error_detail = body.get("message", error_detail)
            except Exception:
                pass
        return f"Error: {error_detail}. Try a simpler command (e.g. fewer lines, pipe to head)."


def shell_exec(cmd: str) -> str:
    """Execute a command on the virtual machine shell."""
    # Copy the FULL implementation from firmware_tools.py shell_exec
    pass  # PLACEHOLDER — copy actual implementation


def firmware_store_answer(confirmation: str) -> str:
    """Store ECCS confirmation code for submission via verify."""
    # Copy the FULL implementation from firmware_tools.py firmware_store_answer
    pass  # PLACEHOLDER — copy actual implementation
```

NOTE: For each file below, copy the FULL function implementations from the source files. Do not use placeholders.

### 2b: `tools/mail_tools.py`
Copy ALL functions from `tools/mailbox_tools.py` (rename logger to `tools.mail`)

### 2c: `tools/audio_tools.py`
Copy ALL functions from `tools/phonecall_tools.py` (rename logger to `tools.audio`)

### 2d: `tools/geo_tools.py`
Copy functions from `tools/findhim_tools.py`: fetch_all_locations, find_nearest_powerplant, fetch_access_levels, select_answer
Also copy `from tools.data_tools import download_and_filter` re-export line (rename logger to `tools.geo`)

### 2e: `tools/grid_tools.py`
Copy ALL functions from `tools/electricity_tools.py` + `execute_rescue` from `tools/domatowo_tools.py` (rename logger to `tools.grid`)

### 2f: `tools/navigation_tools.py`
Copy `navigate_reactor` from `tools/reactor_tools.py` + ALL functions from `tools/savethem_tools.py` (rename logger to `tools.navigation`)

### 2g: `tools/transport_tools.py`
Copy ALL from `tools/railway_tools.py` + `drone_submit` from `tools/drone_tools.py` + ALL from `tools/packages_tools.py` (rename logger to `tools.transport`)

### 2h: `tools/document_tools.py`
Copy ALL from `tools/sendit_tools.py` + `build_filesystem` from `tools/filesystem_tools.py` + `build_orders` from `tools/foodwarehouse_tools.py` (rename logger to `tools.document`)

### 2i: `tools/logs_tools.py`
Copy ALL from `tools/failure_tools.py` (rename logger to `tools.logs`)

### 2j: `tools/monitoring_tools.py`
Copy ALL from `tools/radiomonitoring_tools.py` (rename logger to `tools.monitoring`)

### 2k: `tools/web_tools.py`
Copy ALL from `tools/okoeditor_tools.py` + ALL from `tools/negotiations_tools.py` + `configure_windpower` from `tools/windpower_tools.py` (rename logger to `tools.web`)

### 2l: `tools/classification_tools.py`
Copy ALL from `tools/categorize_tools.py` (rename logger to `tools.classification`)

### 2m: Merge tagging into `tools/data_tools.py`
Add tag_people and filter_by_tag from `tools/tagging_tools.py` to existing `tools/data_tools.py`

**Keep unchanged:** `tools/verify_tools.py`, `tools/evaluation_tools.py`

**Step: Verify new files load**

Run: `python -c "from tools.shell_tools import run_shell_cmd, shell_exec; print('shell OK')"`
Run: `python -c "from tools.transport_tools import railway_help, drone_submit; print('transport OK')"`
Run: `python -c "from tools.data_tools import download_and_filter, tag_people; print('data OK')"`

---

## Task 3: Delete old tool files and re-export files

**Files to delete:**
- `tools/shellaccess_tools.py`
- `tools/firmware_tools.py`
- `tools/mailbox_tools.py`
- `tools/phonecall_tools.py`
- `tools/findhim_tools.py`
- `tools/electricity_tools.py`
- `tools/domatowo_tools.py`
- `tools/reactor_tools.py`
- `tools/savethem_tools.py`
- `tools/railway_tools.py`
- `tools/drone_tools.py`
- `tools/packages_tools.py`
- `tools/sendit_tools.py`
- `tools/filesystem_tools.py`
- `tools/foodwarehouse_tools.py`
- `tools/failure_tools.py`
- `tools/radiomonitoring_tools.py`
- `tools/okoeditor_tools.py`
- `tools/negotiations_tools.py`
- `tools/windpower_tools.py`
- `tools/categorize_tools.py`
- `tools/tagging_tools.py`
- `tools/people_tools.py` (re-export file, no longer needed)

**Keep:**
- `tools/verify_tools.py`
- `tools/evaluation_tools.py`
- `tools/data_tools.py` (expanded with tagging functions)
- All 13 new category files

**Step: Verify no imports break**

Run: `for d in categorize domatowo drone electricity evaluation failure filesystem findhim firmware foodwarehouse mailbox negotiations okoeditor people phonecall radiomonitoring railway reactor savethem sendit shellaccess windpower; do python -c "from tasks.$d.task import run; print('$d: OK')" 2>&1; done`

Expected: All 22 print OK

---

## Task 4: Test key tasks

**Step 1: Test 5 representative tasks covering different tool categories**

Run each and verify flag:
- `python run.py electricity` (grid_tools)
- `python run.py shellaccess` (shell_tools)
- `python run.py people` (data_tools with merged tagging)
- `python run.py railway` (transport_tools)
- `python run.py evaluation` (evaluation_tools — unchanged)

**Step 2: If any fail, debug and fix**

Common issues:
- Missing import in new category file
- Logger name mismatch (cosmetic, non-breaking)
- Function not found → check spelling in skill frontmatter vs function name

---

## Task 5: Commit

```bash
git add tools/ core/skill.py
git commit -m "refactor: reorganize tools by category with global loader

Reorganize 26 task-named tool files into 15 category files.
Update skill loader to search all tools/*_tools.py files.
No changes to skills, tasks, or agent."
```

---

## Summary

| What | Action | Count |
|------|--------|-------|
| `core/skill.py` | Update loader to search all files | 1 |
| New category tool files | Create | 13 |
| `tools/data_tools.py` | Expand (add tagging) | 1 |
| Old tool files | Delete | 23 |
| Skills/tasks/agents | No changes needed | 0 |
