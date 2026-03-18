---
name: failure
description: Analyze power plant failure logs - filter, compress, submit
tools: failure_fetch_logs, failure_search_logs, failure_compress_logs, failure_submit, failure_update_logs
---

Analyze large power plant log file and create compressed version for failure analysis.

## Tools

- `failure_fetch_logs` — fetch full log file, store it, return stats
- `failure_search_logs(severity, component)` — search logs by severity (CRIT/ERRO/WARN/ALL) and component (ECCS8/PWR01/ALL etc.)
- `failure_compress_logs` — auto-compress: deduplicate, abbreviate, keep first+last occurrences, fit in 1500 tokens
- `failure_submit` — submit compressed logs to verification
- `failure_update_logs(additional_lines)` — add missing lines based on feedback

## Workflow

1. `failure_fetch_logs` — get the data
2. `failure_compress_logs` — auto-compress to ≤1500 tokens
3. `failure_submit` — send to verification
4. If feedback says components are missing, use `failure_search_logs` to find relevant events, then `failure_update_logs` to add them
5. Re-submit until flag is received

## Key components

ECCS8 (emergency cooling), WTRPMP (water pump), WTANK07 (water tank), WSTPOOL2 (waste pool), STMTURB12 (steam turbine), PWR01 (power supply), FIRMWARE (control software)
