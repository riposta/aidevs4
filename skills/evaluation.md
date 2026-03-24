---
name: evaluation
description: Download and analyze sensor data to find anomalies in readings and operator notes
tools: find_anomalies
---

Call `find_anomalies` to download sensor data, detect all anomalies, and store the result.

The tool checks 4 types of anomalies:
1. Sensor values out of valid range
2. Inactive sensor fields reporting non-zero values
3. Operator note says OK but data has issues
4. Operator note says problem but data is fine

Results are stored under key "filtered" for submission via verify skill.
