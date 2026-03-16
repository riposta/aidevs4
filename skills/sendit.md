---
name: sendit
description: Fetch SPK documentation and build transport declarations
tools: fetch_spk_doc, fetch_spk_image, build_declaration
---

Documentation base URL: https://hub.ag3nts.org/dane/doc/

Start by fetching `index.md` — it references other files via `[include file="..."]`.

Key files to fetch:
- `index.md` — main documentation (categories, routes, fees, rules)
- `zalacznik-E.md` — declaration template (CRITICAL)
- `zalacznik-G.md` — abbreviations glossary (explains WDP, PP, etc.)
- `dodatkowe-wagony.md` — extra wagon pricing
- `trasy-wylaczone.png` — blocked routes table (IMAGE - use fetch_spk_image)

Use `fetch_spk_doc` with filename for text files.
Use `fetch_spk_image` with filename for image files — returns text description of image content.

After gathering all data, use `build_declaration` to construct the final declaration string.
Pass all field values and it will format them according to the template.
The result is stored under key "filtered" for submission via verify skill.
