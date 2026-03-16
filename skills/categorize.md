---
name: categorize
description: Classify transport items as DNG or NEU using a token-limited prompt
tools: categorize_reset, categorize_fetch_csv, categorize_classify
---

Classify 10 items as DNG (dangerous) or NEU (neutral) via a compact prompt.

## Tools

- `categorize_reset` — reset budget (call before each attempt)
- `categorize_fetch_csv` — fetch fresh CSV with items (always fetch before classifying)
- `categorize_classify(prompt_template)` — send prompt for all 10 items

## Prompt rules

- Max 100 tokens total (including item data)
- Template MUST contain `{id}` and `{description}` placeholders
- Must return exactly DNG or NEU
- Weapons/explosives/ammo → DNG
- Reactor-related items → always NEU (even if they sound dangerous)
- Everything else → NEU
- Put static part first (for caching), variables at end

## Workflow

1. `categorize_reset`
2. `categorize_fetch_csv`
3. `categorize_classify(prompt_template)` with your prompt
4. If error — adjust prompt and retry from step 1
