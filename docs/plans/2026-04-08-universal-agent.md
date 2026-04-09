# Universal Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all 22 task-specific agents with one universal agent (`universal_solver`), keeping all domain logic in skills.

**Architecture:** One generic agent that receives `task_name` as input, activates the skill matching that name (convention: skill name == task name), follows skill instructions, and submits via verify. Tasks that currently use multiple skills (people=data+tagging, findhim=data+findhim) get consolidated into single skills. `proxy` stays untouched (custom Flask server). Task entry points become minimal stubs calling `get_agent("universal_solver")`.

**Tech Stack:** Python, OpenAI function calling, existing core framework (no changes to core/)

---

## Pre-work: Inventory

**Tasks to migrate (22):** categorize, domatowo, drone, electricity, evaluation, failure, filesystem, findhim, firmware, foodwarehouse, mailbox, negotiations, okoeditor, people, phonecall, radiomonitoring, railway, reactor, savethem, sendit, shellaccess, windpower

**Excluded:** proxy (custom HTTP server, keeps its own agent)

**Agents to delete after migration (22):** All `*_solver.md` files except `proxy_assistant.md`

**Agents to keep (3):** `compactor.md`, `summarizer.md`, `proxy_assistant.md`

**Skills needing consolidation:**
- `people` task: currently uses skills `data` + `tagging` + `verify` → merge into single `people` skill
- `findhim` task: currently uses agent delegation (calls `people_solver`) + skills `findhim` + `verify` → merge into single `findhim` skill that includes data-fetch step
- All other tasks: already have 1 task skill + `verify` → just add verify instructions into the task skill

**Skills that become orphaned after consolidation:** `data`, `tagging` (absorbed into `people` and `findhim`)

---

## Task 1: Create the universal agent

**Files:**
- Create: `agents/universal_solver.md`

**Step 1: Create agent file**

```markdown
---
name: universal_solver
description: Universal task solver — activates skill matching task name, follows instructions, submits answer
model: gpt-5-nano
skills: categorize, domatowo, drone, electricity, evaluation, failure, filesystem, findhim, firmware, foodwarehouse, mailbox, negotiations, okoeditor, people, phonecall, radiomonitoring, railway, reactor, savethem, sendit, shellaccess, windpower, verify
---

You are a universal task solver. You receive a task name and instructions.

## Process

1. Activate the skill matching the task name using use_skill
2. Follow the skill's instructions exactly — it contains all parameters, tool sequences, and domain logic
3. If the skill says to submit an answer, activate the "verify" skill and use submit_answer

## Rules

- ALWAYS activate the task skill FIRST before doing anything else
- Follow skill instructions step by step — do not skip or reorder steps
- If a tool returns an error, read the error message and adjust your approach
- When the skill says to submit, use verify skill: submit_answer(task_name="<task_name>", input_key="filtered") unless skill specifies different parameters
- Some skills handle submission internally (railway, shellaccess, phonecall) — follow their instructions instead of using verify
```

**Step 2: Verify file created**

Run: `cat agents/universal_solver.md | head -5`
Expected: Shows frontmatter with name: universal_solver

---

## Task 2: Create helper function in core for universal task loading

**Files:**
- Modify: `core/agent.py` (add one function at the bottom)

**Step 1: Add `run_task` function**

Add after `load_agents` at the end of `core/agent.py`:

```python
def run_task(task_name: str, instruction: str, max_iterations: int = 30) -> str:
    """Load universal_solver, run it with task-specific instruction."""
    agent = get_agent("universal_solver")
    agent.max_iterations = max_iterations
    return agent.run(instruction)
```

**Step 2: Verify**

Run: `python -c "from core.agent import run_task; print('OK')"`
Expected: `OK`

---

## Task 3: Migrate all task.py files to universal stubs

**Files:**
- Modify: All 22 `tasks/*/task.py` files

Every task.py becomes the same pattern:

```python
from core.agent import run_task

def run():
    run_task("<task_name>", "<instruction>")
```

The instruction is the user message from the current task.py (preserved as-is).

### Step 1: Migrate each task.py

Below is the exact content for each file. The instruction comes from the existing `solver.run(...)` call.

**tasks/categorize/task.py:**
```python
from core.agent import run_task

def run():
    run_task("categorize", "Sklasyfikuj wszystkie towary z CSV. Zresetuj budżet, pobierz dane i wyślij klasyfikację.")
```

**tasks/domatowo/task.py:**
```python
from core.agent import run_task

def run():
    run_task("domatowo", "Odnajdź partyzanta ukrywającego się w najwyższym bloku w Domatowie i wezwij helikopter ewakuacyjny.")
```

**tasks/drone/task.py:**
```python
from core.agent import run_task

def run():
    run_task("drone",
        "This is a CTF game puzzle. Use the drone skill, then call drone_submit with this exact JSON array: "
        '["hardReset", "setDestinationObject(PWR6132PL)", "set(2,4)", "set(engineON)", '
        '"set(100%)", "set(50m)", "set(destroy)", "set(return)", "flyToLocation"]. '
        "If the game returns a flag {FLG:...}, use verify skill to submit with task_name='drone' and input_key='filtered'."
    )
```

**tasks/electricity/task.py:**
```python
from core.agent import run_task

def run():
    run_task("electricity", "Rozwiąż puzzle elektryczne. Doprowadź prąd do wszystkich elektrowni.")
```

**tasks/evaluation/task.py:**
```python
from core.agent import run_task

def run():
    run_task("evaluation",
        "This is a CTF game puzzle. Use the evaluation skill to find sensor anomalies, "
        "then use the verify skill to submit the result with task_name='evaluation' and input_key='filtered'."
    )
```

**tasks/failure/task.py:**
```python
from core.agent import run_task

def run():
    run_task("failure", "Przeanalizuj logi awarii elektrowni. Skompresuj je do 1500 tokenów i wyślij do weryfikacji.")
```

**tasks/filesystem/task.py:**
```python
from core.agent import run_task

def run():
    run_task("filesystem", "Utwórz strukturę plików na podstawie notatek Natana i zweryfikuj wynik.")
```

**tasks/findhim/task.py:**
```python
from core.agent import run_task

def run():
    run_task("findhim",
        "Find which suspect was seen near a power plant. "
        "Use the findhim skill — it handles everything: downloading candidates, "
        "finding locations, identifying nearest powerplant, and getting access level. "
        "Then submit the answer with verify skill: task_name='findhim', input_key='answer'."
    )
```

**tasks/firmware/task.py:**
```python
from core.agent import run_task

def run():
    run_task("firmware",
        "Uruchom plik /opt/firmware/cooler/cooler.bin na maszynie wirtualnej.\n"
        "Krok po kroku:\n"
        "1. Aktywuj skill 'firmware', wykonaj 'help', potem 'reboot'\n"
        "2. Przeczytaj .gitignore żeby wiedzieć czego nie dotykać\n"
        "3. Przeczytaj settings.ini i spróbuj uruchomić binarke\n"
        "4. Znajdź hasło komendą 'find *pass*' i przeczytaj znaleziony plik\n"
        "5. Napraw settings.ini (editline) i uruchom binarke z hasłem\n"
        "6. Gdy uzyskasz kod ECCS-..., zapisz go firmware_store_answer i wyślij przez verify\n"
        "7. Po udanym submit ZAKOŃCZ — napisz końcową wiadomość tekstową"
    )
```

**tasks/foodwarehouse/task.py:**
```python
from core.agent import run_task

def run():
    run_task("foodwarehouse", "Utwórz zamówienia dla wszystkich miast z poprawnym podpisem i towarami, potem zweryfikuj.")
```

**tasks/mailbox/task.py:**
```python
from core.agent import run_task

def run():
    run_task("mailbox",
        "Przeszukaj skrzynkę mailową operatora. Znajdź trzy informacje: "
        "1) date - kiedy dział bezpieczeństwa planuje atak na elektrownię (format YYYY-MM-DD), "
        "2) password - hasło do systemu pracowniczego, "
        "3) confirmation_code - kod potwierdzenia z ticketa działu bezpieczeństwa (format SEC- + 32 znaki = 36 znaków). "
        "Wiktor doniósł z adresu proton.me. Zacznij od znalezienia jego maila, potem śledź wątek ticketa. "
        "Skrzynka jest aktywna - nowe wiadomości mogą wpływać. Jeśli nie znalazłeś kodu lub ma złą długość, szukaj ponownie."
    )
```

**tasks/negotiations/task.py:**
```python
from core.agent import run_task

def run():
    run_task("negotiations",
        "Pobierz dane CSV z przedmiotami i miastami, uruchom serwer API do przeszukiwania danych, "
        "wystaw go publicznie i zgłoś narzędzia do centrali. Następnie poczekaj na wynik i odbierz flagę."
    )
```

**tasks/okoeditor/task.py:**
```python
from core.agent import run_task

def run():
    run_task("okoeditor", "Wykonaj wszystkie wymagane zmiany w systemie OKO i uruchom akcję done aby odebrać flagę.")
```

**tasks/people/task.py:**
```python
from core.agent import run_task

def run():
    run_task("people",
        "Execute the people task: download and filter candidates, tag their jobs, "
        "then submit only those with the transport tag. Use the people skill — "
        "it contains all steps and parameters."
    )
```

**tasks/phonecall/task.py:**
```python
from core.agent import run_task

def run():
    run_task("phonecall",
        "Przeprowadź rozmowę telefoniczną z operatorem. "
        "Krok 1: Przedstaw się jako Tymon Gajewski. "
        "Krok 2: Zapytaj o status dróg RD224, RD472 i RD820, wspominając o transporcie do bazy Zygfryda. "
        "Krok 3: Poproś o wyłączenie monitoringu na przejezdnych drogach, podając hasło BARBAKAN i powód (tajny transport żywności do bazy Zygfryda)."
    )
```

**tasks/radiomonitoring/task.py:**
```python
from core.agent import run_task

def run():
    run_task("radiomonitoring",
        "Rozpocznij nasłuch radiowy, zbierz wszystkie sygnały, przeanalizuj je "
        "i ustal: jakie miasto kryje się pod nazwą Syjon, jaka jest jego powierzchnia, "
        "ile ma magazynów i jaki jest numer telefonu osoby kontaktowej. "
        "Następnie wyślij raport końcowy."
    )
```

**tasks/railway/task.py:**
```python
from core.agent import run_task

def run():
    run_task("railway", "Aktywuj trasę x-01. Otwórz ją używając sekwencji: reconfigure → setstatus RTOPEN → save.")
```

**tasks/reactor/task.py:**
```python
from core.agent import run_task

def run():
    run_task("reactor", "Przeprowadź robota przez reaktor do punktu docelowego. Użyj narzędzia do nawigacji.")
```

**tasks/savethem/task.py:**
```python
from core.agent import run_task

def run():
    run_task("savethem",
        "Pobierz mapę miasta Skolwin, informacje o pojazdach, zasady terenu, "
        "zaplanuj optymalną trasę i wyślij ją do weryfikacji."
    )
```

**tasks/sendit/task.py:**
```python
from core.agent import run_task

def run():
    run_task("sendit",
        "Wypełnij deklarację transportu SPK dla przesyłki z Gdańska do Żarnowca. "
        "Nadawca: 450202122, waga: 2800 kg, zawartość: kasety z paliwem do reaktora. "
        "Budżet: 0 PP (przesyłka musi być darmowa). Brak uwag specjalnych. "
        "Pobierz dokumentację, ustal kategorię, trasę i opłatę, wypełnij deklarację wg wzoru i wyślij."
    )
```

**tasks/shellaccess/task.py:**
```python
from core.agent import run_task

def run():
    run_task("shellaccess",
        "Explore the remote server's /data directory using shell commands. "
        "Find logs mentioning Rafał — determine the date his body was found, the city, and GPS coordinates. "
        "The meeting date is ONE DAY BEFORE Rafał was found. "
        "When you have all info, print the JSON using echo with EXACT format: "
        '{"date":"YYYY-MM-DD","city":"name","longitude":float,"latitude":float}. '
        "longitude/latitude must be numbers, not strings. System auto-detects correctness."
    )
```

**tasks/windpower/task.py:**
```python
from core.agent import run_task

def run():
    run_task("windpower", "Skonfiguruj turbinę wiatrową i zdobądź flagę. Użyj narzędzia do automatycznej konfiguracji.")
```

### Step 2: Verify all task files import correctly

Run: `for d in categorize domatowo drone electricity evaluation failure filesystem findhim firmware foodwarehouse mailbox negotiations okoeditor people phonecall radiomonitoring railway reactor savethem sendit shellaccess windpower; do python -c "from tasks.$d.task import run; print('$d: OK')"; done`

Expected: All 22 print OK

---

## Task 4: Consolidate people skill (merge data + tagging)

The `people` task currently requires 3 skills: `data`, `tagging`, `verify`. We need to merge `data` + `tagging` into a single `people` skill.

**Files:**
- Create: `skills/people.md`
- Keep: `skills/data.md`, `skills/tagging.md` (still used by `findhim` potentially — check after)

**Step 1: Create people skill**

```markdown
---
name: people
description: Download, filter, tag and prepare people data for submission
tools: download_and_filter, tag_people, filter_by_tag
---

Complete people task in 3 steps:

1. Use `download_and_filter` with dataset="people", filters_json={"gender": "M", "birthPlace": "Grudziądz", "age_min": 20, "age_max": 40}, output_key="candidates"
2. Use `tag_people` with input_key="candidates", output_key="tagged"
3. Use `filter_by_tag` with tag="transport", input_key="tagged", output_key="filtered"

After step 3, the answer is ready in store key "filtered".
Then use verify skill: submit_answer(task_name="people", input_key="filtered")
```

**Step 2: Verify skill loads**

Run: `python -c "from core.skill import load_skills; s = load_skills(['people']); print(s['people'].name, len(s['people'].tool_fns))"`
Expected: `people 3`

---

## Task 5: Consolidate findhim skill (add data download step)

The `findhim` task currently delegates to `people_solver` agent to get candidates, then uses `findhim` skill. We need to make `findhim` skill self-contained.

**Files:**
- Modify: `skills/findhim.md` (add data tools)

**Step 1: Update findhim skill to include data download**

Replace `skills/findhim.md` with:

```markdown
---
name: findhim
description: Find which suspect was seen near a power plant — downloads data, locates candidates, finds nearest plant
tools: download_and_filter, fetch_all_locations, find_nearest_powerplant, fetch_access_levels, select_answer
---

Complete findhim task in 5 steps:

1. Use `download_and_filter` with dataset="people", filters_json={"gender": "M", "birthPlace": "Grudziądz", "age_min": 20, "age_max": 40}, output_key="candidates"
2. Use `fetch_all_locations` with input_key="candidates", output_key="locations", plants_key="plants"
3. Use `find_nearest_powerplant` with input_key="locations", plants_key="plants", output_key="matches"
   Geocodes cities automatically and returns all candidates within 50km, sorted by distance.
4. Use `fetch_access_levels` with input_key="matches", output_key="enriched"
5. Use `select_answer` with input_key="enriched", index=0, output_key="answer"
   (index 0 = closest candidate)

After step 5, the answer is ready in store key "answer".
Then use verify skill: submit_answer(task_name="findhim", input_key="answer")
```

**Step 2: Verify tools load from correct files**

The `download_and_filter` tool lives in `tools/data_tools.py`. The findhim tools live in `tools/findhim_tools.py`.
The skill loader finds tools by searching ALL `tools/*_tools.py` files, so listing `download_and_filter` in tools should work.

Run: `python -c "from core.skill import load_skills; s = load_skills(['findhim']); print(sorted(s['findhim'].tool_fns.keys()))"`
Expected: `['download_and_filter', 'fetch_access_levels', 'fetch_all_locations', 'find_nearest_powerplant', 'select_answer']`

**If this fails:** Check how `core/skill.py` resolves tool functions — it may only search in the matching `tools/<skill_name>_tools.py` file.

---

## Task 6: Verify skill tool resolution works cross-file

**Files:**
- Read: `core/skill.py`

**Step 1: Check if skill tool loading is limited to matching file**

Run: `cat core/skill.py` and check how `load_skills` resolves tool functions.

**If tools are only loaded from `tools/<skill_name>_tools.py`:** We need to either:
- Option A: Add `download_and_filter` to `tools/findhim_tools.py` as a re-export/import
- Option B: Modify `core/skill.py` to search all tool files
- Option C: Add a `tool_sources` frontmatter field

Determine the current behavior and choose the simplest fix. Option A (re-export) is safest:

```python
# Add to tools/findhim_tools.py at the top:
from tools.data_tools import download_and_filter  # re-export for skill loader
```

Similarly for `tools/people_tools.py` (if it doesn't exist, create it with re-exports):

```python
# tools/people_tools.py
from tools.data_tools import download_and_filter
from tools.tagging_tools import tag_people, filter_by_tag
```

---

## Task 7: Add verify instructions to skills that need it

Most skills currently rely on the agent knowing to "use verify skill". With the universal agent, this still works because `verify` is in the agent's skill list. But we should make each skill's instructions explicit about submission.

**Skills that already handle submission internally (no verify needed):**
- `railway` — flag comes from save()
- `shellaccess` — flag comes from echo command
- `phonecall` — tool handles everything
- `electricity` — tool handles everything
- `categorize` — tool handles classification + submission

**Skills that need explicit verify step at the end (check each skill body — if it doesn't mention verify, add a note):**

For each skill that currently lacks submission instructions, append:

```
After completion, use verify skill: submit_answer(task_name="<task_name>", input_key="filtered")
```

Review each skill and add only where missing. Skills already containing "submit" or "verify" instructions can be left as-is.

---

## Task 8: Delete old agent files

**Files:**
- Delete: All `agents/*_solver.md` files (22 files)

**Step 1: Delete old agents**

Run:
```bash
cd agents && ls *_solver.md | grep -v proxy | while read f; do rm "$f"; done
```

**Step 2: Verify only correct agents remain**

Run: `ls agents/`
Expected: `compactor.md  proxy_assistant.md  summarizer.md  universal_solver.md`

---

## Task 9: Cleanup orphaned skills (optional)

After consolidation, `data.md` and `tagging.md` are no longer directly referenced by any agent. But they're still valid skills with useful tools.

**Decision:** Keep them — they don't hurt and may be useful for future tasks. The tools they provide are now imported via `people` and `findhim` skills anyway.

---

## Task 10: Test all tasks

Run each task and verify it still works.

**Step 1: Test one simple task first**

Run: `python run.py shellaccess`
Expected: Flag returned

**Step 2: Test a verify-based task**

Run: `python run.py electricity`
Expected: Flag returned

**Step 3: Test the consolidated people task**

Run: `python run.py people`
Expected: Flag returned

**Step 4: Test the consolidated findhim task**

Run: `python run.py findhim`
Expected: Flag returned

**Step 5: Test remaining tasks one by one**

Run each of the remaining 18 tasks and verify flags. Priority order (simplest first):
1. categorize, reactor, domatowo, okoeditor, foodwarehouse, filesystem (tool does everything)
2. railway, drone, windpower (simple tool sequences)
3. evaluation, failure, savethem, sendit (medium complexity)
4. mailbox, firmware, negotiations, phonecall, radiomonitoring (complex / long-running)

---

## Summary of changes

| What | Action | Count |
|------|--------|-------|
| `agents/universal_solver.md` | Create | 1 |
| `core/agent.py` | Add `run_task()` function | 1 |
| `tasks/*/task.py` | Replace with universal stub | 22 |
| `skills/people.md` | Create (consolidate data+tagging) | 1 |
| `skills/findhim.md` | Modify (add data download tools) | 1 |
| `tools/people_tools.py` | Create (re-export tools) | 1 |
| `tools/findhim_tools.py` | Modify (add re-export) | 1 |
| `agents/*_solver.md` | Delete | 22 |
| Skills with missing verify | Add submit instructions | ~5 |
| `proxy` task | No changes | 0 |
