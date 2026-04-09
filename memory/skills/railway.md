---
name: railway
description: Manage train route status using the Railway API.
tools: railway_help, railway_getstatus, railway_reconfigure, railway_setstatus, railway_save
---

Step-by-step instructions:
1. **Check Available Actions**: 
   - Call `railway_help` to get full API documentation.
   - Expected output: List of available actions and parameters.

2. **Enable Reconfigure Mode**:
   - Call `railway_reconfigure` with the exact route you wish to manage.
   - Command: `railway_reconfigure(route="X-01")`
   - Expected output: 
     ```json
     {"ok": true, "route": "X-01", "mode": "reconfigure", "status": "close", "message": "Reconfigure mode enabled for this route."}
     ```

3. **Check Current Route Status**:
   - Call `railway_getstatus` with the same route to check its current status.
   - Command: `railway_getstatus(route="X-01")`
   - Expected output: Current status of the route. (e.g. `{"ok": true, "route": "X-01", "status": "open"}`)

4. **Set Route Status**:
   - Call `railway_setstatus` with the chosen status for the route.
   - To set the route to open: 
     - Command: `railway_setstatus(route="X-01", value="RTOPEN")`
   - Expected output:
     ```json
     {"ok": true, "route": "X-01", "mode": "reconfigure", "status": "open", "message": "Status updated."}
     ```
   - Or, to close the route:
     - Command: `railway_setstatus(route="X-01", value="RTCLOSE")`
   - Expected output: 
     ```json
     {"ok": true, "route": "X-01", "mode": "reconfigure", "status": "close", "message": "Status updated."}
     ```

5. **Save Changes**:
   - After setting the status, exit reconfigure mode by saving the changes.
   - Command: `railway_save(route="X-01")`
   - Expected output: 
     ```json
     {"ok": true, "route": "X-01", "message": "Changes saved."}
     ```

6. **Load Result**: 
   - To access the details of the changes made, load the result into a designated store key.
   - Command: `load_result(task_name="railway", output_key="filtered")`
   - Expected output: Loaded result for 'railway' into 'filtered', preview: `{'route': 'X-01'}`.

By following these exact steps, an agent can effectively manage the railway route status through the Railway API.