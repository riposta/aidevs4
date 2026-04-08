---
name: people
description: Download, filter, tag and prepare people data for submission
tools: download_and_filter, tag_people, filter_by_tag
---

Complete people task in 3 steps:

1. Use `download_and_filter` with dataset="people", filters_json={"gender": "M", "birthPlace": "Grudziądz", "age_min": 20, "age_max": 40}, output_key="candidates"
2. Use `tag_people` with input_key="candidates", output_key="tagged"
3. Use `filter_by_tag` with tag="transport", input_key="tagged", output_key="filtered"

After step 3, the answer is ready in store key "filtered".
Then use verify skill: submit_answer(task_name="people", input_key="filtered")
