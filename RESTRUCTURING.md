# oakspool Restructuring Plan

## Goal

Break the 5 monolith scripts into thin entry points + reusable layers without adding ceremony. Keep it flat, just with clearer boundaries. Fixes: duplicate seasons, broken API callers, HTML string concatenation, import side-effects.

---

## File layout (current → target)

### Current
```
api.py                     # Leslie's scraping (234 lines, mixed auth/parsing/data)
flume_water_use.py         # Flume auth + data fetch + chart generation + CSV merge (189 lines)
flume_constant_water_check.py  # Flume auth + query + alert (137 lines, duplicates auth logic)
lelies-log-and-plot.py     # Leslie's + CSV logging + Slack + plotting (403 lines)
dashboard_update.py        # CSV reading + HTML string concat + Slack (291 lines)
pumphouse.py               # Chart generation only, but runs on import (80 lines)
common_defines.py          # SEASONS dict never imported anywhere (5 lines)
seasons.txt                # ✓ flat-text seasons (keep)
seasons_loader.py          # ✓ reads seasons.txt (keep)
```

### Target
```
# --- config ---
config.py              # env vars: FLUME creds, Leslie's creds, Slack, GH
                         load_dotenv()
                         FLUME = os.getenv(...)
                         SLACK_TOKEN = os.getenv(...)
                         # single point for all credential access

# --- external ---
flume_api.py           # all Flume API: auth token, device lookup, query
                         class FlumeClient:
                             def authenticate() → access_token
                             def get_device() → device_id
                             def query(since, until, bucket) → data

leslies_api.py         # all Leslie's scraping: auth, water test fetch, HTML parsing
                         class LesliesPoolApi:
                             def authenticate() → bool
                             def fetch_water_test() → dict
                             # extract HTML parsing to: def parse_water_test(html) → dict

# --- domain ---
data_store.py          # CSV read/write abstraction
                         class DataStore:
                             def load_flume_usage() → list[dict]   # date,ccf
                             def load_leslies_logs() → list[dict]  # 13 columns
                             def load_flow() → list[dict]         # flow, vac_press, etc.
                             def append_leslies_log(record)
                             def merge_flume_usage(new_data)      # safe merge, no truncation race
                             def write_flume_usage(data)

plots.py               # chart generation functions
                         def make_usage_chart(data) → Path   # flume_usage_chart.png
                         def make_season_comparison(data) → Path  # flume_season_comparison.png
                         def make_chemical_plot(data) → Path
                         def make_flow_plot(data) → Path
                         def make_pressure_plot(data) → Path
                         def make_sparkline(data) → str        # reused in Slack messages

dashboard.py           # HTML generation with Jinja2 template
                         def build_dashboard_html(data) → str
                         def write_dashboard(html) → Path

slack.py               # message building + posting + rate limiting
                         class SlackClient:
                             def __init__(token)
                             def post(channel, text) → bool
                             def post_test_summary(test_data) → str
                             def post_flume_summary(date, usage, cost) → str
                             def post_daily_heartbeat(today) → str
                         # rate limit: track response, back off if 429

# --- entry points (thin, ~20-30 lines each) ---
flume_water_use.py     # config → flume_api.query → data_store.merge → plots.make_usage_chart → plots.make_season_comparison → slack daily update
lelies-log-and-plot.py # config → leslies_api.authenticate → leslies_api.fetch → data_store.append → check duplicate → slack alert → plots.make_chemical_plot
dashboard_update.py    # config → data_store.load all → dashboard.build → plots.make_flow_plot + plots.make_pressure_plot → slack weekly
constant_water_check.py  # config → flume_api.authenticate → flume_api.query(min + hr) → evaluate flow threshold → slack alert if needed
pumphouse.py           # config → data_store.load_flow → plots.make_flow_plot → plots.make_pressure_plot

# --- kept as-is ---
seasons.txt            # ✓ flat-text format (year MM DD MM DD rate)
seasons_loader.py      # ✓ load() loads into list[Season]
```

---

## Implementation order

### Phase 1: Foundation (no behavior change)
1. Create `config.py` — move all `os.getenv()` calls here
2. Create `data_store.py` — CSV read/write abstraction
3. Extract `flume_api.py` from `flume_water_use.py` + `flume_constant_water_check.py`
4. Extract `leslies_api.py` (keep existing `api.py` class name but move to new file)

### Phase 2: Domain layer
5. Create `plots.py` — extract chart generation from all scripts
6. Create `dashboard.py` — replace 250-line f-string with Jinja2 template
7. Create `slack.py` — rate-limited post, message templates

### Phase 3: Wire up entry points
8. Rewrite `flume_water_use.py` — thin glue code
9. Rewrite `constant_water_check.py` — thin glue code
10. Rewrite `leslies-log-and-plot.py` — thin glue code
11. Rewrite `dashboard_update.py` — thin glue code
12. Rewrite `pumphouse.py` — thin glue code (keep `if __name__` guard)

### Phase 4: Cleanup
13. Delete `api.py` (moved to `leslies_api.py`)
14. Delete `common_defines.py` (replaced by `seasons_loader.py`)
15. Add `requirements.txt` to workflows
16. Update `AGENTS.md`
17. Create git commit

---

## Key fixes during restructuring (from TODO.md)

- [ ] CSV writing bug in `lelies-log-and-plot.py:93` (`append_to_csv`) — read, truncate, then append is a race condition. Fix in `data_store.append_leslies_log()` using atomic write or proper pandas append.
- [ ] `api.py:151` — `data` referenced outside retry loop — already fixed (was a bug)
- [ ] `is_duplicate_test()` — string comparison fragile with whitespace — fix in `data_store` with `.strip()` on all fields
- [ ] `lelies-log-and-plot.py:5` — duplicate `from datetime import datetime` — remove
- [ ] `lelies-log-and-plot.py:19` — `QUIET = 0` is hardcoded magic — make it env var or config
- [ ] `dashboard_update.py:22` — mutable global `broadcast=[...]` → constant or local
- [ ] `poolcam_snap.yml` uses `actions/checkout@v5` — fix to @v4
- [ ] `constant_water_check.yml` 30-min cron = 48 commits/day — consider batching to hourly
- [ ] `manual-promote.yml` hardcodes file list — add warning or automate

---

## Jinja2 dashboard template (draft)

```jinja2
<!DOCTYPE html>
<html><head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="style.css">
    <title>Oaks Pool Dashboard</title>
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(div => div.classList.remove('active'));
            document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            document.getElementById('btn-' + tabId).classList.add('active');
        }
        window.onload = function() { showTab('water'); };
    </script>
</head><body>
    <h1>Oaks Pool Dashboard</h1>
    <div class="tabs">
        <button class="tab-button" id="btn-water" onclick="showTab('water')">Water Use</button>
        <button class="tab-button" id="btn-chemicals" onclick="showTab('chemicals')">Chemicals</button>
        <button class="tab-button" id="btn-pumphouse" onclick="showTab('pumphouse')">Pump House</button>
        <button class="tab-button" id="btn-raw" onclick="showTab('raw')">Raw Data</button>
    </div>

    <div id="water" class="tab-content">
        <h3>Daily Usage – Last 30 Days</h3>
        <img src="flume_usage_chart.png" alt="Usage Chart">
        <h3>Pool Season Comparison</h3>
        <img src="flume_season_comparison.png" alt="Season Chart">
        <h3>📅 Last 30 Days of Use</h3>
        <table border="1" cellpadding="6" cellspacing="0">
            <thead><tr><th>Date</th><th>Usage (CCF)</th><th>Cost ($)</th></tr></thead>
            <tbody>
            {% for row in recent_rows %}
                <tr><td>{{row.date}}</td><td>{{'%.2f'|format(row.ccf)}}</td><td>${{'%.2f'|format(row.cost)}}</td></tr>
            {% endfor %}
            </tbody>
        </table>
        {% if season %}
        <h3>💰 Season Usage Summary</h3>
        <ul>
            <li><strong>Cost so far:</strong> ${{'%.2f'|format(season.used_cost)}}</li>
            <li><strong>Projected remaining cost:</strong> ${{'%.2f'|format(season.projected_cost)}}</li>
            <li>Based on {{'%.2f'|format(season.recent_avg)}} CCF/day × {{season.days_left}} days @ ${{'%.2f'|format(season.rate)}}/CCF</li>
        </ul>
        {% endif %}
        <p><em>Dashboard auto-updated on {{today}}</em></p>
    </div>

    <div id="chemicals" class="tab-content">
        <h3>Chemical History</h3>
        <p>Plots below are auto-generated from test logs. Green band is Leslie's recommended range, red indicates a state required limit, yellow is a caution area between the two.</p>
        <p>Note the Leslie's tester is not a state certified test, and tests are run off-hours.</p>
        <img src="ph.png" alt="pH Levels">
        <img src="chlorine.png" alt="Chlorine Levels">
        <img src="alkalinity.png" alt="Alkalinity">
        <img src="cyanuric_acid.png" alt="CYA Levels">
        <img src="phosphates.png" alt="Phosphate Levels">
        <img src="calcium.png" alt="Calcium Levels">
        <img src="copper.png" alt="Copper Levels">
        <img src="iron.png" alt="Iron Levels">
    </div>

    <div id="pumphouse" class="tab-content">
        <h3>🏠 Pump House</h3>
        <p>Coming soon: pump status, runtime logs, and filter pressure trends.</p>
        <img src="flow.png" alt="Flow Rate">
        <img src="press.png" alt="Pressures and Flow Rate">
    </div>

    <div id="raw" class="tab-content">
        <h3>Raw Output – Last 14 Days</h3>
        <table border="1" cellpadding="6" cellspacing="0">
            <thead>
                <tr><th>Date</th><th>CCF</th><th>Flow</th><th>Vac</th><th>Sys</th><th>F1</th>
                <th>Free Cl</th><th>Total Cl</th><th>pH</th><th>Alk</th><th>Ca</th><th>CYA</th>
                <th>Fe</th><th>Cu</th><th>Phos</th></tr>
            </thead>
            <tbody>
            {% for row in raw_rows %}
                <tr>
                    <td>{{row.date}}</td>
                    <td>{{'%.2f'|format(row.ccf)}}</td>
                    <td>{{row.flow or '—'}}</td><td>{{row.vac or '—'}}</td><td>{{row.sys or '—'}}</td>
                    <td>{{row.f1 or '—'}}</td>
                    <td>{{row.free_cl or '—'}}</td><td>{{row.total_cl or '—'}}</td>
                    <td>{{row.ph or '—'}}</td><td>{{row.alk or '—'}}</td><td>{{row.ca or '—'}}</td>
                    <td>{{row.cya or '—'}}</td><td>{{row.fe or '—'}}</td><td>{{row.cu or '—'}}</td>
                    <td>{{row.phos or '—'}}</td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
</body></html>
```

---

## Decisions to make when ready

- [ ] Jinja2 or a simpler template engine (Jinja2 requires adding `pip install jinja2` to workflows)
- [ ] `data_store.py` — should it return dataclasses or dicts? (Currently mixed)
- [ ] `slack.py` — should Slack be a module-level singleton or instantiated per-call? (Singleton is simpler)
- [ ] `flume_api.py` — reuse the existing FlumeToken data structure or define a new one?
- [ ] Where to store `requirements.txt` — in root alongside `seasons.txt` or alongside each script?
