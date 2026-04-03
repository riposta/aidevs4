---
name: savethem
description: Zbiera dane i planuje optymalną trasę do miasta Skolwin
tools: gather_intel, plan_route
---

## Zbieranie danych

Use `gather_intel` to fetch the map for Skolwin, all vehicle specifications, and terrain rules from the API. Call this first.

## Planowanie trasy

Use `plan_route` to compute the optimal route using BFS pathfinding and resource optimization. This requires gathered intel data in the store. The tool returns the answer ready to submit.
