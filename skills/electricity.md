---
name: electricity
description: Solve 3x3 electrical cable puzzle by analyzing images and rotating fields
tools: electricity_reset, electricity_rotate, electricity_solve
---

Solve a 3x3 cable puzzle to connect power plants to power source.

## Tools

- `electricity_reset` — reset board, analyze current vs target, calculate needed rotations
- `electricity_rotate(field)` — rotate one field 90° clockwise (format: "AxB", e.g. "2x3")
- `electricity_solve` — full auto-solve: reset, analyze, execute all rotations

## Workflow

The simplest approach: just call `electricity_solve` — it handles everything automatically:
1. Resets the board
2. Fetches and analyzes both current and target images (pixel analysis)
3. Calculates rotations needed per cell
4. Sends all rotation API calls
5. Verifies final state

If solve reports mismatches, call `electricity_reset` to re-analyze and then manually rotate remaining cells.
