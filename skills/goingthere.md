---
name: goingthere
description: Navigate rocket through 3x12 grid to Grudziadz, avoiding rocks and radar traps
tools: navigate_rocket
---

Use `navigate_rocket` to play the goingthere game.

The tool handles the entire game loop:
1. Starts the game
2. Checks frequency scanner before each move
3. Disarms radar traps when detected
4. Gets radio hints about rock positions
5. Chooses safe movement commands
6. Retries if crashed

It will return the flag when the rocket reaches Grudziadz.
If it returns a flag, report it to the user.
