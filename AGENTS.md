# AGENTS.md

## What this project does

Automates community pool operations: water usage tracking (Flume API), chemical test logging
(Leslie's Pool HTML scraper), pump house flow/pressure monitoring (RPi push), and a GitHub
Pages dashboard with Slack notifications.

---

## File map

### Entry points — run these, never import them

| Script | Purpose | Inputs | Outputs |
|---|---|---|---|
| `pull_flume.py` | Nightly Flume pull | Flume API | `logs/flume_usage_log.csv` |
| `pull_leslies.py` | Per-run Leslie's pull | Leslie's HTML | `logs/leslies-log.csv`, Slack |
| `check_flow.py` | 30-min leak check | Flume API | Slack alert if ≥95% non-zero flow |
| `update_plots.py` | Regenerate all PNGs | All CSVs | `docs/*.png` |
| `build_dashboard.py` | Build HTML dashboard | All CSVs | `docs/index.html`, Slack heartbeat |

### Support modules — import these, never run directly

| Module | Purpose |
|---|---|
| `flume_auth.py` | Flume OAuth (password grant) → returns `(headers, query_url)` |
| `leslies_api.py` | `LesliesPoolApi` class — authenticate + fetch water test HTML |
| `seasons_loader.py` | Reads `seasons.txt` → `Season` dataclasses; `get_rate()`, `get_current_season()` |

### Data files (committed)

| File | Format | Notes |
|---|---|---|
| `logs/flume_usage_log.csv` | `date,ccf` | One row per day, atomic write via .tmp |
| `logs/leslies-log.csv` | `run_timestamp,test_date,free_chlorine,...` (13 cols) | Append-only, deduplicated |
| `logs/flow.csv` | `read_datetime,vac_press,sys_press,f1_press,flow` | RPi pushes directly |
| `seasons.txt` | `year open_m open_d close_m close_d rate` | Source of truth for season dates and CCF rates |

### Workflows

| Workflow | Trigger | Runs |
|---|---|---|
| `pull_flume.yml` | `0 4 * * *` + dispatch | `pull_flume.py` → commit CSV |
| `pull_leslies.yml` | `0 */2 * * *` + dispatch | `pull_leslies.py` → commit CSV |
| `check_flow.yml` | `*/30 * * * *` + dispatch | `check_flow.py` (no commit) |
| `update_plots.yml` | push to `logs/*.csv` on main + dispatch | `update_plots.py` → commit PNGs |
| `build_dashboard.yml` | `0 5 * * *` + dispatch | `build_dashboard.py` → commit HTML |
| `cleanup_flowimages.yml` | `0 3 * * *` | Deletes `flowimages/` older than 7 days |
| `poolcam_snap.yml` | manual | Eufy bridge → frame capture |

`update_plots.yml` fires automatically when any of the three CSVs change on main —
this includes RPi pushes to `logs/flow.csv`.

---

## Secrets (GH Actions — never commit)

| Secret | Used by |
|---|---|
| `FLUME_USERNAME/PASSWORD/CLIENT_ID/CLIENT_SECRET` | `pull_flume.py`, `check_flow.py` |
| `LESLIES_USERNAME/PASSWORD/POOLID/POOLNAME` | `pull_leslies.py` |
| `SLACK_BOT_TOKEN` | All scripts |
| `SLACK_CHANNEL` | Alerts + Sunday broadcast |
| `SLACK_BOARD_CHANNEL` | Sunday broadcast only |
| `SLACK_HEARTBEAT_CHANNEL` | Weekday dashboard heartbeat |
| `GH_TOKEN` | Write workflows (commit + push) |
| `EUFY_USER/PASS/PIN` | `poolcam_snap.yml` only |

---

## Running locally

```bash
# Install everything needed
pip install requests beautifulsoup4 matplotlib pandas pytz python-dotenv

# Copy and fill in credentials
cp example.env .env

# Run any entry point
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
`zoneinfo.ZoneInfo`. `build_dashboard.py` uses `pytz`.

### CSV formats differ
`flume_usage_log.csv` → `date` is `YYYY-MM-DD`.
`leslies-log.csv` → `test_date` is `MM/DD/YYYY`, `run_timestamp` is `YYYY-MM-DD HH:MM:SS`.
`flow.csv` → `read_datetime` is `YYYY-MM-DD HH:MM:SS`. Do not swap readers between files.

### Leslie's is fragile HTML scraping
`leslies_api.py` parses specific CSS class names from Leslie's DOM. A page redesign will
break it silently. `pull_leslies.py` validates required fields and exits non-zero if they're
missing — the workflow Slack failure alert covers this.

### Flume password grant is legacy OAuth
`flume_auth.py` uses `grant_type=password`. If Flume sunsets this endpoint the auth will
fail with a non-200 response and raise `SystemExit(1)`.

### RPi flow data
The RPi runs its own script and pushes directly to `logs/flow.csv` on main. `update_plots.yml`
fires automatically on that push. `build_dashboard.py` reads `flow.csv` assuming timestamps
are naive US/Central datetimes.

### Dashboard is auto-generated
`docs/index.html` is written by `build_dashboard.py`. Do not edit it by hand.

### Season data
`seasons.txt` is the single source of truth. Add a new season line before pool opening each
year. Import `seasons_loader` — never hardcode year/rate data in scripts.

### Slack channels
- New Leslie's test → `SLACK_CHANNEL`
- Flow alert (≥95% non-zero) → `SLACK_CHANNEL`
- Discrepancy (hourly > 0, no minute data) → `SLACK_HEARTBEAT_CHANNEL`
- Dashboard heartbeat → `SLACK_HEARTBEAT_CHANNEL` weekdays, both channels Sundays

### Testing new workflows on a branch
Scheduled triggers only fire on the default branch. Use `workflow_dispatch` to test any
workflow manually on a branch from the GitHub Actions tab. All workflows include dispatch.
