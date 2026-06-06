# RESTRUCTURING.md

Restructuring is complete. See `AGENTS.md` for the current file layout and operational notes.

The old monolith scripts (`flume_water_use.py`, `leslies-log-and-plot.py`, `dashboard_update.py`,
`pumphouse.py`, `api.py`, `common_defines.py`) and the old workflows (`telemetry.yml`,
`medium_checks.yml`) are retained on `main` until the new scripts are validated on the feature
branch. Delete them after confirming the new workflows run cleanly.
