---
name: verify
description: Submit answers and load results from previous tasks
tools: submit_answer, load_result
---

Use `submit_answer` with the task name and input_key pointing to the store key with the answer.

Use `load_result` with task_name and output_key to load a previous task's answer into the store.
Example: `load_result(task_name="people", output_key="candidates")` loads the answer from `results/people.json` into store key "candidates".
