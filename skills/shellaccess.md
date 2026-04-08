---
name: shellaccess
description: Execute shell commands on remote server to explore logs and find information about Rafał
tools: run_shell_cmd
---

Use `run_shell_cmd` to execute Linux shell commands on the remote server.

## Data files

The server has 3 files in /data:
- **time_logs.csv** — historical events, format: `date;description;location;place` (4541 rows)
- **locations.json** — location names: `{"location_id": N, "name": "city"}`
- **gps.json** — GPS data: `{"latitude": N, "longitude": N, "type": "...", "location_id": N, "entry_id": N}`

## Step-by-step search strategy

ALWAYS add `| head -n 20` to every command — server max output is 4096 bytes!

### Step 1: Find the log entry about Rafał's body
```
run_shell_cmd(cmd="grep 'Rafał' /data/time_logs.csv | grep -i 'ciało\\|znalezione\\|martwy\\|zgon\\|jaskini' | head -n 20")
```
If no results, try broader: `grep -i 'ciało' /data/time_logs.csv | head -n 20`

Note the date, location_id (3rd column), and entry_id/place (4th column).

### Step 2: Find city name from location_id
```
run_shell_cmd(cmd="grep -A1 'location_id.*: LOCATION_ID' /data/locations.json | head -n 5")
```

### Step 3: Find GPS coordinates from gps.json
Use the entry_id (place column from CSV):
```
run_shell_cmd(cmd="grep -B3 -A3 'entry_id.*: ENTRY_ID' /data/gps.json | head -n 10")
```

### Step 4: Submit answer
Calculate date as ONE DAY BEFORE the found date. Echo JSON:
```
run_shell_cmd(cmd="echo '{\"date\":\"YYYY-MM-DD\",\"city\":\"CityName\",\"longitude\":LON,\"latitude\":LAT}'")
```

- longitude and latitude must be NUMBERS (floats), NOT strings
- The system auto-detects correctness and returns a flag
