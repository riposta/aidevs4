---
name: drone
description: Control DRN-BMB7 combat drone via zmail API - send flight instructions
tools: drone_submit
---

Send drone flight instructions using `drone_submit(instructions)`.

The `instructions` parameter is a JSON array of command strings. The correct sequence to bomb the dam:

```json
[
  "hardReset",
  "setDestinationObject(PWR6132PL)",
  "set(2,4)",
  "set(engineON)",
  "set(100%)",
  "set(50m)",
  "set(destroy)",
  "set(return)",
  "flyToLocation"
]
```

The API returns error messages if something is wrong - read them and adjust.

If the response contains `{FLG:...}`, store the flag and submit via verify skill.
