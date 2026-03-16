---
name: railway
description: Control railway routes via self-documenting API (reconfigure, set status, save)
tools: railway_help, railway_getstatus, railway_reconfigure, railway_setstatus, railway_save
---

Railway API controls train routes. All actions go through the verify endpoint.

Available tools:
- `railway_help` — get full API documentation (call first if unsure)
- `railway_getstatus(route)` — check current route status
- `railway_reconfigure(route)` — enter reconfigure mode (REQUIRED before setstatus)
- `railway_setstatus(route, value)` — set route status: "RTOPEN" or "RTCLOSE"
- `railway_save(route)` — exit reconfigure mode, save changes, store result as "filtered"

Route format: letter-number, e.g. "x-01", "a-12".

## Sequence to activate a route

1. `railway_reconfigure(route)` — enter edit mode
2. `railway_setstatus(route, "RTOPEN")` — open the route
3. `railway_save(route)` — save and exit edit mode

The save result is stored under key "filtered" for submission via verify skill.
