---
name: tagging
description: Skill for classifying job descriptions into predefined tags
tools: tag_people, filter_by_tag
---

1. Use `tag_people` with input_key="candidates", output_key="tagged"
2. Use `filter_by_tag` with tag="transport", input_key="tagged", output_key="filtered"
