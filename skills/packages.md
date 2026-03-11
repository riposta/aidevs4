---
name: packages
description: Check and redirect packages in the logistics system
tools: check_package, redirect_package
---

Use `check_package` with packageid to check package status and location.

Use `redirect_package` with packageid, destination (e.g. "PWR3847PL"), and code (security code from operator) to redirect a package. Returns confirmation code to pass to operator.
