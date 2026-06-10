# CLAUDE.md

## What this project does

Automates community pool operations: water usage tracking (Flume API), chemical test logging
(Leslie's Pool HTML scraper), pump house flow monitoring (RPi direct push), and a GitHub Pages
dashboard with Slack notifications.

---

## File map

### Entry points — run these, never import them

| Script | Purpose | Inputs | Outputs |
|---|---|---|---|
| `pull_flume.py` | Nightly Flume pull | Flume API | `logs/flume_usage_log.csv` |
| `pull_leslies.py` | Per-run Leslie's pull | Leslie's HTML | `logs/leslies-log.csv`, Slack |
| `check_flow.py` | 30-min leak check | Flume API | Slack alert if ≥95% non-zero flow |
| `update_plots.py` | Regenerate all PNGs | All CSVs | `docs/*.png` |
| `build_dashboard.py` | Build HTML dashboard | All CSVs + PNGs | `docs/index.html`, Slack Sunday |

### Support modules — import these, never run directly

| Module | Purpose |
|---|---|
| `flume_auth.py` | Flume OAuth (password grant) → returns `(headers, query_url)` |
| `leslies_api.py` | `LesliesPoolApi` class — authenticate + fetch water test HTML |
| `seasons_loader.py` | Reads `seasons.txt` → `Season` dataclasses; `get_rate()`, `get_current_season()` |

### Data files (committed)

| File | Format | Notes |
|---|---|---|
| `logs/flume_usage_log.csv` | `date,ccf` | One row per day; atomic write via .tmp + os.replace |
| `logs/leslies-log.csv` | `run_timestamp,test_date,free_chlorine,...` (13 cols) | Append-only, deduplicated on all non-timestamp fields |
| `logs/flow.csv` | `read_datetime,vac_press,sys_press,f1_press,flow,notes,flow_std` | RPi pushes directly; timestamps are naive US/Central; `flow_std` is 30-second std dev |
| `seasons.txt` | `year open_m open_d close_m close_d rate` | Source of truth for season dates and CCF water rates |

### Workflows

| Workflow | Trigger | Runs |
|---|---|---|
| `pull_flume.yml` | `0 4 * * *` + dispatch | `pull_flume.py` → commit CSV |
| `pull_leslies.yml` | `0 */2 * * *` + dispatch | `pull_leslies.py` → commit CSV |
| `check_flow.yml` | `*/30 * * * *` + dispatch | `check_flow.py` (no commit) |
| `update_plots.yml` | push to `logs/*.csv` on main + dispatch | `update_plots.py` → commit PNGs |
| `build_dashboard.yml` | `0 5 * * *` + dispatch + `workflow_run` after Update Plots | `build_dashboard.py` → commit HTML |
| `cleanup_flowimages.yml` | `0 3 * * *` | Deletes `flowimages/` older than 7 days |
| `poolcam_snap.yml` | manual | Eufy bridge → frame capture |

`update_plots.yml` fires automatically when any of the three CSVs change on main (including
RPi pushes to `logs/flow.csv`). `build_dashboard.yml` then fires via `workflow_run` once
plots complete, so tables and charts are always in sync.

### Old workflows/scripts (disabled — pending deletion)

These have been replaced and their schedule/dispatch triggers are commented out. Delete once
the new workflows have been running cleanly for a full season.

- `.github/workflows/telemetry.yml` → replaced by `pull_flume.yml`, `pull_leslies.yml`, `update_plots.yml`, `build_dashboard.yml`
- `.github/workflows/medium_checks.yml` → replaced by `pull_leslies.yml`, `update_plots.yml`
- `.github/workflows/constant_water_check.yml` → replaced by `check_flow.yml`
- `flume_water_use.py`, `leslies-log-and-plot.py`, `dashboard_update.py`, `pumphouse.py`, `api.py`, `flume_constant_water_check.py`

---

## Secrets (GH Actions — never commit)

| Secret | Used by |
|---|---|
| `FLUME_USERNAME/PASSWORD/CLIENT_ID/CLIENT_SECRET` | `pull_flume.py`, `check_flow.py` |
| `LESLIES_USERNAME/PASSWORD/POOLID/POOLNAME` | `pull_leslies.py` |
| `SLACK_BOT_TOKEN` | All scripts |
| `SLACK_CHANNEL` | Leslie's test alerts, flow alerts, Sunday broadcast |
| `SLACK_BOARD_CHANNEL` | Sunday broadcast only (exec board channel) |
| `SLACK_HEARTBEAT_CHANNEL` | Flume/RPi discrepancy alerts only |
| `GH_TOKEN` | Write workflows (commit + push) |
| `EUFY_USER/PASS/PIN` | `poolcam_snap.yml` only |

---

## Running locally

```bash
pip install requests beautifulsoup4 matplotlib pandas pytz python-dotenv
cp example.env .env   # fill in credentials
python pull_flume.py
python pull_leslies.py
python check_flow.py
python update_plots.py
python build_dashboard.py
```

---

## Gotchas

### Timezone
All datetimes are **US/Central** (`America/Chicago`). Never use UTC or local system time.
`flume_auth.py` and `pull_flume.py` use `pytz`. `check_flow.py` and `pull_leslies.py` use
`zoneinfo.ZoneInfo`. `build_dashboard.py` uses `pytz`. `flow.csv` timestamps are naive
US/Central — do not apply tzinfo when reading them.

### CSV formats differ
`flume_usage_log.csv` → `date` is `YYYY-MM-DD`.
`leslies-log.csv` → `test_date` is `MM/DD/YYYY`, `run_timestamp` is `YYYY-MM-DD HH:MM:SS`.
`flow.csv` → `read_datetime` is `YYYY-MM-DD HH:MM:SS`. Do not swap readers between files.

### Leslie's is fragile HTML scraping
`leslies_api.py` parses specific CSS class names from Leslie's DOM. A page redesign will break
it silently. `pull_leslies.py` validates required fields (`test_date`, `free_chlorine`,
`total_chlorine`, `ph`) and returns cleanly (not an error) when they're absent — this is
normal at pool open before the first test of the season.

### Flume password grant is legacy OAuth
`flume_auth.py` uses `grant_type=password`. If Flume sunsets this endpoint the auth will
fail with a non-200 response and raise `SystemExit(1)`.

### RPi flow data
The RPi runs its own script and pushes directly to `logs/flow.csv` on main. `update_plots.yml`
fires automatically on that push, then `build_dashboard.yml` follows. The RPi is only
operational during pool season — off-season, `flow.csv` is stale by design and the dashboard
shows an offline notice.

### Off-season behavior
When `get_current_season(today)` returns `None`, `build_dashboard.py` suppresses alarms:
- Pump House tab shows "RPi offline — pool closed for the season" (neutral gray) with a note
  that Flume still monitors for leaks.
- Chemicals tab shows a banner that testing resumes when the pool opens.
- Both tabs still display last season's data for historical context.

### Dashboard is auto-generated
`docs/index.html` is written by `build_dashboard.py`. Do not edit it by hand.

### Season data
`seasons.txt` is the single source of truth. Add a new season line before pool opening each
year. Import `seasons_loader` — never hardcode year/rate data in scripts.

### Slack channels
- New Leslie's test logged → `SLACK_CHANNEL`
- Flow alert (≥95% non-zero over 30-min window) → `SLACK_CHANNEL`
- Hourly Flume > 0 but no minute-level data → `SLACK_HEARTBEAT_CHANNEL`
- Dashboard update broadcast → `SLACK_CHANNEL` + `SLACK_BOARD_CHANNEL` on Sundays only

### Pending minor items
- `poolcam_snap.yml` uses `actions/checkout@v5` — update to @v4 when next touching that file
- Pip dependencies in workflows are unpinned — consider pinning if reproducibility matters
