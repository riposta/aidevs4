---
name: findhim
description: Find which suspect was seen near a power plant — downloads data, locates candidates, finds nearest plant
tools: download_and_filter, fetch_all_locations, find_nearest_powerplant, fetch_access_levels, select_answer
---

Complete findhim task in 5 steps:

1. Use `download_and_filter` with dataset="people", filters_json={"gender": "M", "birthPlace": "Grudziądz", "age_min": 20, "age_max": 40}, output_key="candidates"
2. Use `fetch_all_locations` with input_key="candidates", output_key="locations", plants_key="plants"
3. Use `find_nearest_powerplant` with input_key="locations", plants_key="plants", output_key="matches"
   Geocodes cities automatically and returns all candidates within 50km, sorted by distance.
4. Use `fetch_access_levels` with input_key="matches", output_key="enriched"
5. Use `select_answer` with input_key="enriched", index=0, output_key="answer"
   (index 0 = closest candidate)

After step 5, the answer is ready in store key "answer".
Then use verify skill: submit_answer(task_name="findhim", input_key="answer")
