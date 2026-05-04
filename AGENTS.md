# AGENTS.md

## Repo overview

`oakspool` is a Python 3.11 project for automating community pool water tracking. Currently one monolith of 5 scripts (see below), but restructuring is planned — see `RESTRUCTURING.md` for the target layout and priority order.

Current state: 6 flat .py files + `seasons.txt` + flat text documentation. No framework, no tests, no `requirements.txt`.

## Sources of truth

| File | What it is | Used for |
|---|---|---|
| `seasons.txt` | Flat text, one season per line | **New source of truth** for pool seasons and rates |
| `seasons_loader.py` | Reads `seasons.txt` into `Season` dataclasses | Any script needs season data — import this |
| `RESTRUCTURING.md` | Future layout + implementation phases | Read before doing any major rewrite |
| `TODO.md` | Unfixed issues + pending decisions | Track what was identified but not yet resolved |
| `leslies-log-and-plot.py` | Leslie's API client + main workflow | Contains `LesliesPoolApi` class for parsing water test HTML |
| `api.py` | **Legacy** — the same `LesliesPoolApi` class before restructuring | Delete during Phase 2 — will be replaced by `leslies_api.py` |
| `common_defines.py` | Old season definitions, never imported | Delete — replaced by `seasons_loader.py` |

### Future layout (from `RESTRUCTURING.md`) — do NOT write to these yet

Files in `RESTRUCTURING.md` `### Target` section. Implement only in the phase order listed there. Do NOT deviate from the planned file layout.

## File reference map (current)

| Script | Role | Key inputs | Key outputs |
|---|---|---|---|
| `flume_water_use.py` | Nightly water usage fetch | Flume API, `logs/flume_usage_log.csv` | `docs/flume_usage_chart.png`, `docs/flume_season_comparison.png`, `logs/flume_usage_log.csv` |
| `flume_constant_water_check.py` | 30-min continuous flow alert | Flume API, minutes+hourly buckets | Slack alert, `heartbeats/flume_heartbeat_constant.log` |
| `leslies-log-and-plot.py` | Chemical test fetch + log + plot | Leslie's HTML scraping, `logs/leslies-log.csv` | `docs/{ph,chlorine,alkalinity,cyanuric_acid,phosphates,calcium,copper,iron}.png` |
| `dashboard_update.py` | HTML dashboard build + weekly Slack | All three CSVs | `docs/index.html`, Slack post (Sundays) |
| `pumphouse.py` | Flow/pressure plots | `logs/flow.csv` | `docs/flow.png`, `docs/press.png` |

### CSV formats (they do NOT match)

| File | Columns | Notes |
|---|---|---|
| `logs/flume_usage_log.csv` | `date,ccf` | One row per day |
| `logs/leslies-log.csv` | `run_timestamp,test_date,free_chlorine,total_chlorine,ph,alkalinity,calcium,cyanuric_acid,iron,copper,phosphates,salt,in_store` | One row per test |
| `logs/flow.csv` | `read_datetime,vac_press,sys_press,f1_press,flow` | One row per sensor reading |

### Secrets (GH secrets, NOT committed)

| Secret | Used by |
|---|---|
| `FLUME_USERNAME` / `FLUME_PASSWORD` / `FLUME_CLIENT_ID` / `FLUME_CLIENT_SECRET` | `flume_water_use.py`, `flume_constant_water_check.py` |
| `LESLIES_USERNAME` / `LESLIES_PASSWORD` / `LESLIES_POOLID` / `LESLIES_POOLNAME` | `leslies-log-and-plot.py` |
| `SLACK_BOT_TOKEN` / `SLACK_CHANNEL` / `SLACK_BOARD_CHANNEL` / `SLACK_HEARTBEAT_CHANNEL` | All notification scripts |
| `GH_TOKEN` | All workflows (git push) |
| `EUFY_USER` / `EUFY_PASS` / `EUFY_PIN` | `poolcam_snap.yml` |

`example.env` has placeholder values — never commit with real values.

## Running scripts

The workflows install deps inline; there is no `pip freeze` or `requirements.txt`.

```
# All telemetry + dashboard
pip install beautifulsoup4 matplotlib pandas requests python-dotenv pytz

# Constant water check
pip install requests python-dotenv tzlocal

# PoolCam
pip install websockets python-ffmpeg
```

To run locally (requires `.env` + above deps):
```
python flume_water_use.py
python flume_constant_water_check.py
python leslies-log-and-plot.py
python dashboard_update.py
python pumphouse.py
```

## Workflow schedule

| Workflow | Schedule | Key steps |
|---|---|---|
| `telemetry.yml` (Nightly) | `0 4 * * *` UTC (11 PM CDT) | flume_water_use → leslies-log → dashboard_update → commit CSVs+PNGs+HTML → push |
| `medium_checks.yml` | Manual | leslies-log → pumphouse → commit CSVs+PNGs → push |
| `constant_water_check.yml` | `*/30 * * * *` UTC | flume hourly+minute query → alert if ≥95% non-zero flow → commit heartbeat |
| `poolcam_snap.yml` | Manual | Eufy bridge Docker container → poolcam image → upload artifact |
| `manual-promote.yml` | Manual | `git checkout origin/dev -- dashboard_update.py flume_constant_water_check.py flume_water_use.py` → commit → push |

## Season data

```
# seasons.txt format (flat text):
year open_month open_day close_month close_day rate
2023 5 26 9 3 5.60
2024 5 24 9 1 6.15
2025 5 23 8 31 6.70
2026 5 25 9 7 7.20   # Memorial Day → Labor Day
```

Load via: `from seasons_loader import load, get_rate, get_current_season, get_season_by_year`

During restructuring, seasons remain in `seasons.txt` — no `json` or `pydantic`.

## Gotchas

### Time and timezone
- All datetime handling uses **US/Central** (`America/Chicago`). Don't rely on local tz.
- `leslies-log-and-plot.py` parses `test_date` as `mm/dd/yyyy` but `run_timestamp` as `yyyy-mm-dd hh:mm:ss`.
- `dashboard_update.py:88` only considers dates from `season["open"]` through `TODAY` for season projection — does NOT cap at the season close date.

### CSV quirks
- CSV formats do NOT match each other. Each script has its own `csv.DictReader` logic.
- `leslies-log-and-plot.py:123-125` reads CSV, then truncates and re-appends it in the same function — a race condition if two runs overlap.
- Heartbeat logs (`.log` extension) are committed even though `.log` is in `.gitignore`.

### API fragility
- **`api.py` scrapes Leslie's HTML** — `soup.find()` on specific CSS classes. If Leslie's changes their DOM, the entire chemical pipeline fails silently.
- **Flume password grant** is a legacy OAuth endpoint (`POST /oauth/token` with `grant_type=password`). They may sunset this.
- There is no error detection when Leslie's returns no usable HTML table. You won't know until Slack stops arriving.

### Import side-effects
- `pumphouse.py` (and all other scripts) runs immediately at import time. Importing it from another script runs the entire chart.
- The `__name__ == "__main__"` guard is now present in `pumphouse.py` but not in others.

### Slack specifics
- `dashboard_update.py:284-289`: Sundays send to `SLACK_CHANNEL` + `SLACK_BOARD_CHANNEL` (broadcast). Other days send only to `SLACK_HEARTBEAT_CHANNEL`.
- Both Flume scripts use file-based daily heartbeat dedup (`heartbeats/flume_heartbeat_*.log`).
- Slack has zero rate-limit handling. Burst runs will get silently dropped.

### Dashboard
- `docs/index.html` is auto-generated by `dashboard_update.py` and is NOT hand-edited.
- Dashboard is served at `https://brianhartsell.github.io/oakspool/` (GitHub Pages).
- HTML is built via 250 lines of string concatenation — adding/removing a chart or section requires editing the HTML template embedded in a string.

### Git flow
- Primary branch: `main`. `dev` branch exists for staged changes.
- `manual-promote.yml` is the mechanism to move scripts from `dev` → `main`. It hardcodes the file list — silently drops new scripts not listed.
- All write workflows use `git fetch origin main; git pull --rebase origin main; git push`.
- `.gitignore` tracks `__pycache__/`, `*.pyc`, `*.log` — but heartbeat logs are committed.

### Season comparison chart
- `flume_water_use.py:144-172` generates the yearly pool season comparison chart.
- CLOSED seasons cap at their close date. OPEN/current season caps at TODAY.
- Only shows data within the season window, NOT the continuous "season has been running" view.

## Restructuring (in-progress)

See `RESTRUCTURING.md` for:
- Target file layout (Phase 1-4)
- Jinja2 dashboard template
- Implementation order
- Decisions to make

See `TODO.md` for unfixed bugs and items identified but not yet resolved.

## What an agent needs to know before making changes

1. **Season data lives in `seasons.txt`** — never duplicate it. Import `seasons_loader.py`.
2. **No `.env` commit** — all secrets are GH secrets.
3. **CSV formats differ** — never swap readers between files.
4. **All scripts run at module level** — importing any script executes it.
5. **Flat-text formats everywhere** — prefer plain text over JSON/YAML for config.
6. **US/Central timezone** — always.
7. **Leslie's API is HTML scraping** — fragile, add error detection when changing things.
8. **Flume password grant is legacy** — don't assume the endpoint is eternal.
9. **Refer to `RESTRUCTURING.md` + `TODO.md` before rewriting** — know the planned direction.
10. **Dashboard is auto-generated** — edit `dashboard_update.py`, not `docs/index.html`.
