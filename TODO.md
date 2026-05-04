# TODO.md

## Open issues

### API fragility
- [ ] `api.py` — HTML scraping fails silently when Leslie's changes page structure. Add error detection / alert when parsing returns no results
- [ ] Flume password grant is legacy API — consider checking if there's a newer auth endpoint

### Duplicate data
- [ ] `leslies-log-and-plot.py` has no SEASONS data but references TARGET_RANGES in its config

### CSV writing bug
- [ ] `leslies-log-and-plot.py:123-125` — reads CSV then overwrites-truncates it before appending; if two runs overlap this corrupts data. Fix to atomic write or use proper append

### Workflow / infra
- [ ] No `requirements.txt` — workflows install deps with unpinned versions. One bad dep update breaks everything
- [ ] `poolcam_snap.yml` uses `actions/checkout@v5` (doesn't exist yet, should be @v4)
- [ ] `constant_water_check.yml` fires every 30 min = 48 commits/day to heartbeat files. Consider batching
- [ ] `manual-promote.yml` hardcodes file list — silently drops new files

### Low-value cleanup
- [ ] `leslies-log-and-plot.py:5` — duplicate `from datetime import datetime` (line 3 already imports it)
- [ ] `leslies-log-and-plot.py:19` — `QUIET = 0` is hardcoded magic, never changed
- [ ] `dashboard_update.py:22` — mutable global `broadcast=[...]` should be a constant or local
- [ ] `leslies-log-and-plot.py:93` — `is_duplicate_test` string comparison is fragile (whitespace issues)
- [ ] `dashboard_update.py` — 250-line string concatenation for HTML is unmaintainable. Even a simple template would help
- [ ] `leslies-log-and-plot.py` — `append_to_csv` has broken logic (reads, truncates, appends all in one function)

## Architecture notes for future work

- Season data lives in `seasons.txt`, loaded via `seasons_loader.py`
- All secrets are GH secrets only — never commit `.env`
- All scripts use US/Central timezone, not UTC
- CSV formats do NOT match: `flume_usage_log.csv` has `date,ccf`; `leslies-log.csv` has 13 columns; `flow.csv` has `read_datetime,vac_press,sys_press,f1_press,flow`
- `api.py` is ONLY used by `leslies-log-and-plot.py`
