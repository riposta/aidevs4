---
name: findhim
description: Find which suspect was seen near a power plant and get their access level
tools: fetch_all_locations, find_nearest_powerplant, fetch_access_levels, select_answer
---

1. Use `fetch_all_locations` with input_key="candidates", output_key="locations", plants_key="plants"
2. Use `find_nearest_powerplant` with input_key="locations", plants_key="plants", output_key="matches"
   Geocodes cities automatically and returns all candidates within 50km, sorted by distance.
3. Use `fetch_access_levels` with input_key="matches", output_key="enriched"
4. Use `select_answer` with input_key="enriched", index=0, output_key="answer"
   (index 0 = closest candidate)