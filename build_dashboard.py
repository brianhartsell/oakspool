"""Build docs/index.html from current CSV logs and committed PNGs.

Run nightly after update_plots.py: python build_dashboard.py
"""
import csv
import datetime
import os

import pytz
import requests

from seasons_loader import get_current_season, get_rate

DOCS = "docs"
FLUME_CSV   = "logs/flume_usage_log.csv"
LESLIES_CSV = "logs/leslies-log.csv"
FLOW_CSV    = "logs/flow.csv"

SLACK_TOKEN       = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL     = os.getenv("SLACK_CHANNEL")
SLACK_BOARD_CH    = os.getenv("SLACK_BOARD_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")

# How many raw flow readings to show in the Pump House table
FLOW_TABLE_ROWS = 96

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f4f6f8; color: #333; }
h1 { background: #1a6b6c; color: white; padding: 16px 24px; font-size: 1.5rem; }
.tabs { background: #e8ecef; padding: 0 16px; display: flex; flex-wrap: wrap; gap: 4px;
        border-bottom: 2px solid #1a6b6c; }
.tab-btn { padding: 10px 22px; border: none; background: transparent; cursor: pointer;
           font-size: 14px; border-radius: 4px 4px 0 0; margin-top: 6px;
           color: #555; transition: background 0.15s; }
.tab-btn:hover { background: #d0d8de; }
.tab-btn.active { background: white; border: 1px solid #ccc; border-bottom: 2px solid white;
                  margin-bottom: -2px; font-weight: 600; color: #1a6b6c; }
.tab-pane { display: none; padding: 24px; background: white; min-height: 400px; }
.tab-pane.active { display: block; }
img { max-width: 100%; height: auto; margin: 8px 0 20px; display: block;
      border: 1px solid #e0e0e0; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0 20px; font-size: 13px; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: right; }
th { background: #f0f4f5; font-weight: 600; text-align: center; }
td:first-child, th:first-child { text-align: left; }
tr:nth-child(even) { background: #fafbfc; }
h3 { margin: 22px 0 8px; color: #1a6b6c; font-size: 1rem; }
p.note { color: #777; font-size: 12px; font-style: italic; margin: 6px 0 14px; }
ul { margin: 6px 0 14px 20px; }
li { margin: 4px 0; line-height: 1.5; }
.status { display: inline-block; padding: 8px 16px; border-radius: 6px;
          font-weight: 500; margin-bottom: 16px; font-size: 14px; }
.status.ok   { background: #d4edda; color: #155724; }
.status.warn { background: #fff3cd; color: #856404; }
.status.err  { background: #f8d7da; color: #721c24; }
.stats { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 20px; }
.stat { background: #f4f6f8; border: 1px solid #dde; border-radius: 6px;
        padding: 10px 16px; min-width: 110px; text-align: center; }
.stat-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.4px; }
.stat-val { font-size: 22px; font-weight: 700; color: #1a6b6c; margin-top: 3px; }
.updated { color: #888; font-size: 12px; margin-top: 20px; }
@media (max-width: 500px) {
  .tab-btn { padding: 8px 10px; font-size: 12px; }
}
.status.off  { background: #e9ecef; color: #495057; }
.notice { background: #e9ecef; border-left: 3px solid #aaa; padding: 8px 14px;
          margin: 0 0 16px; border-radius: 3px; font-size: 13px; color: #495057; }
"""

JS = """
function showTab(id) {
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    document.getElementById('btn-' + id).classList.add('active');
}
window.onload = function() { showTab('summary'); };
"""


# ── helpers ──────────────────────────────────────────────────────────────────

def _post_slack(channel, text):
    if not SLACK_TOKEN or not channel:
        return
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json={"channel": channel, "text": text},
    )
    status = "ok" if r.ok and r.json().get("ok") else f"failed {r.status_code}"
    print(f"  Slack → {status}")


def _td(val, fmt=None):
    if val is None or val == "":
        return "<td>—</td>"
    return f"<td>{fmt % val if fmt else val}</td>"


# ── data loading ──────────────────────────────────────────────────────────────

def _load_flume(today):
    rows = []
    if not os.path.exists(FLUME_CSV):
        return rows
    with open(FLUME_CSV, newline="") as f:
        for r in csv.DictReader(f):
            d = datetime.datetime.strptime(r["date"], "%Y-%m-%d").date()
            ccf = float(r["ccf"])
            rate = get_rate(r["date"])
            rows.append({"date": r["date"], "date_obj": d, "ccf": ccf,
                          "rate": rate, "cost": round(ccf * rate, 2)})
    return rows


def _load_leslies(cutoff):
    rows = []
    if not os.path.exists(LESLIES_CSV):
        return rows
    with open(LESLIES_CSV, newline="") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.datetime.strptime(r["test_date"], "%m/%d/%Y").date()
            except ValueError:
                continue
            if d >= cutoff:
                rows.append(r | {"date_obj": d})
    return rows


def _load_flow(cutoff_dt=None):
    """Return list of dicts sorted by read_datetime ascending."""
    rows = []
    if not os.path.exists(FLOW_CSV):
        return rows
    with open(FLOW_CSV, newline="") as f:
        for r in csv.DictReader(f):
            try:
                dt = datetime.datetime.strptime(r["read_datetime"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if cutoff_dt and dt < cutoff_dt:
                continue
            rows.append({
                "dt":       dt,
                "flow":     _safe_float(r.get("flow")),
                "flow_std": _safe_float(r.get("flow_std")),
                "vac":      _safe_float(r.get("vac_press")),
                "sys":      _safe_float(r.get("sys_press")),
                "f1":       _safe_float(r.get("f1_press")),
            })
    return sorted(rows, key=lambda x: x["dt"])


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v, spec):
    return f"{v:{spec}}" if v is not None else "—"


# ── section builders ──────────────────────────────────────────────────────────

def _summary_tab(current_season=None):
    chem_notice = "" if current_season else (
        '<p class="note">Pool is closed — chemical plots reflect last season\'s data.</p>'
    )
    return f"""
<h3>Flow – Last 7 Days</h3>
<img src="flow_7d.png" alt="7-day flow rate">
<h3>Season Water Use Comparison</h3>
<img src="flume_season_comparison.png" alt="Season comparison">
<h3>pH</h3>
{chem_notice}<img src="ph.png" alt="pH">
<h3>Chlorine</h3>
<img src="chlorine.png" alt="Chlorine">
"""


def _water_tab(all_flume, today):
    recent = [r for r in all_flume if 0 <= (today - r["date_obj"]).days < 30]
    table_rows = "\n".join(
        f"<tr><td>{r['date']}</td><td>{r['ccf']:.3f}</td><td>${r['cost']:.2f}</td></tr>"
        for r in reversed(recent)
    )
    usage_table = f"""
<h3>Last 30 Days of Use</h3>
<table>
  <thead><tr><th>Date</th><th>Usage (CCF)</th><th>Cost ($)</th></tr></thead>
  <tbody>{table_rows}</tbody>
</table>"""

    projection = ""
    current = get_current_season(today)
    if current:
        season_rows = [r for r in all_flume if current.open <= r["date_obj"] <= today]
        used_ccf    = sum(r["ccf"] for r in season_rows)
        cost_so_far = used_ccf * current.rate
        days_left   = max((current.close - today).days + 1, 0)
        recent_avg  = (sum(r["ccf"] for r in recent) / len(recent)) if recent else 0.0
        proj_cost   = recent_avg * days_left * current.rate
        projection  = f"""
<h3>Season Usage Summary</h3>
<ul>
  <li><strong>Cost so far:</strong> ${cost_so_far:,.2f}
      ({used_ccf:.1f} CCF @ ${current.rate:.2f}/CCF)</li>
  <li><strong>Projected remaining:</strong> ${proj_cost:,.2f}
      ({recent_avg:.2f} CCF/day × {days_left} days remaining)</li>
</ul>"""

    return f"""
<h3>Daily Usage – Last 30 Days</h3>
<img src="flume_usage_chart.png" alt="30-day usage chart">
<h3>Season Comparison (14-Day Rolling Average)</h3>
<img src="flume_season_comparison.png" alt="Season comparison chart">
{usage_table}
{projection}
<p class="updated">Dashboard updated {today.isoformat()}</p>
"""


def _chemicals_tab(current_season=None):
    off_banner = "" if current_season else (
        '<div class="notice">Pool is closed for the season — chemical testing will resume when the pool opens. '
        'Plots below reflect last season\'s data.</div>'
    )
    return f"""
<h3>Chemical History</h3>
{off_banner}<p class="note">Green band = Leslie's recommended range. Yellow = caution. Red = state closure limit.</p>
<p class="note">Leslie's tests are not state-certified and are run off-hours.
   Out-of-limit readings may not reflect real pool conditions.</p>
<img src="ph.png"           alt="pH">
<img src="chlorine.png"     alt="Chlorine">
<img src="alkalinity.png"   alt="Alkalinity">
<img src="cyanuric_acid.png" alt="Cyanuric Acid">
<img src="phosphates.png"   alt="Phosphates">
<img src="calcium.png"      alt="Calcium">
<img src="copper.png"       alt="Copper">
<img src="iron.png"         alt="Iron">
"""


def _pumphouse_tab(now_ct, current_season=None):
    all_flow = _load_flow()

    if not all_flow:
        if not current_season:
            return (
                '<div class="status off">RPi offline — pool closed for the season</div>'
                '<p class="note">Water flow is still monitored via Flume for leak detection.</p>'
                "<p>No flow data on file from the previous season.</p>"
            )
        return "<p>No flow data available.</p>"

    last = all_flow[-1]
    age_h = (now_ct.replace(tzinfo=None) - last["dt"]).total_seconds() / 3600

    if not current_season:
        age_days = age_h / 24
        age_str = f"{age_days:.0f} day{'s' if age_days >= 2 else ''} ago"
        status_html = (
            f'<div class="status off">RPi offline — last active {age_str}</div>\n'
            '<div class="notice">Pool is closed for the season. The RPi is not operational until '
            'the pool opens. Water flow is still monitored via Flume for leak detection — '
            'if you receive a flow alert, check the Flume app. '
            'Flow data and plots below are from the previous season.</div>'
        )
    else:
        if age_h < 2:
            age_str = f"{int(age_h * 60)} min ago"
            status_cls = "ok"
        elif age_h < 24:
            age_str = f"{age_h:.1f} h ago"
            status_cls = "warn"
        else:
            age_str = f"{age_h:.0f} h ago"
            status_cls = "err"
        status_html = f'<div class="status {status_cls}">RPi last seen: {age_str}</div>'

    # 24-h average flow
    cutoff_24h = now_ct.replace(tzinfo=None) - datetime.timedelta(hours=24)
    recent_24h = [r for r in all_flow if r["dt"] >= cutoff_24h and r["flow"] is not None]
    avg_flow = (sum(r["flow"] for r in recent_24h) / len(recent_24h)) if recent_24h else None

    stats_html = f"""
<div class="stats">
  <div class="stat"><div class="stat-label">Flow (gpm)</div>
    <div class="stat-val">{_fmt(last['flow'], '.1f')}</div></div>
  <div class="stat"><div class="stat-label">24h Avg Flow</div>
    <div class="stat-val">{_fmt(avg_flow, '.1f')}</div></div>
</div>"""

    # Recent readings table (last N rows, newest first)
    table_rows_data = all_flow[-FLOW_TABLE_ROWS:][::-1]
    table_rows_html = "\n".join(
        f"<tr><td>{r['dt'].strftime('%m/%d %H:%M')}</td>"
        f"{_td(r['flow'], '%.2f')}{_td(r['flow_std'], '%.2f')}"
        f"{_td(r['vac'], '%.1f')}"
        f"{_td(r['sys'], '%.1f')}{_td(r['f1'], '%.1f')}</tr>"
        for r in table_rows_data
    )

    return f"""
{status_html}
{stats_html}
<h3>Flow – Last 7 Days</h3>
<img src="flow_7d.png" alt="7-day flow rate">
<h3>Flow – Last 30 Days</h3>
<img src="flow_30d.png" alt="30-day flow rate">
<h3>Pressures and Flow – Last 30 Days</h3>
<img src="press.png" alt="Pressure and flow">
<h3>Recent Readings (last {len(table_rows_data)} entries)</h3>
<table>
  <thead><tr><th>Time (CT)</th><th>Flow (gpm)</th><th>σ (gpm)</th><th>Vac (psi)</th>
             <th>Sys (psi)</th><th>F1 (psi)</th></tr></thead>
  <tbody>{table_rows_html}</tbody>
</table>
"""


def _raw_tab(today):
    current = get_current_season(today)
    if current:
        season_start = current.open
        season_label = f"{current.year} season ({season_start} – {current.close})"
    else:
        season_start = today - datetime.timedelta(days=90)
        season_label = "last 90 days (no active season)"

    sections = []

    # --- Water usage (current season, newest first) ---
    flume_rows = []
    if os.path.exists(FLUME_CSV):
        with open(FLUME_CSV, newline="") as f:
            for r in csv.DictReader(f):
                d = datetime.datetime.strptime(r["date"], "%Y-%m-%d").date()
                if d >= season_start:
                    ccf = float(r["ccf"])
                    rate = get_rate(r["date"])
                    flume_rows.append((r["date"], ccf, ccf * rate))
    flume_rows.sort(reverse=True)
    flume_html = "\n".join(
        f"<tr><td>{d}</td><td>{ccf:.3f}</td><td>${cost:.2f}</td></tr>"
        for d, ccf, cost in flume_rows
    )
    sections.append(f"""
<h3>Water Usage — {season_label} ({len(flume_rows)} days)</h3>
<table>
  <thead><tr><th>Date</th><th>Usage (CCF)</th><th>Cost ($)</th></tr></thead>
  <tbody>{flume_html}</tbody>
</table>""")

    # --- Leslie's tests (current season, newest first) ---
    CHEM_COLS = [
        "free_chlorine", "total_chlorine", "ph", "alkalinity", "calcium",
        "cyanuric_acid", "iron", "copper", "phosphates", "salt", "in_store",
    ]
    les_rows = []
    if os.path.exists(LESLIES_CSV):
        with open(LESLIES_CSV, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    d = datetime.datetime.strptime(r["test_date"], "%m/%d/%Y").date()
                except ValueError:
                    continue
                if d >= season_start:
                    les_rows.append(r)
    les_html = "\n".join(
        "<tr>"
        f"<td>{r.get('run_timestamp','')}</td><td>{r.get('test_date','')}</td>"
        + "".join(f"<td>{r.get(c, '')}</td>" for c in CHEM_COLS)
        + "</tr>"
        for r in reversed(les_rows)
    )
    sections.append(f"""
<h3>Water Chemistry (Leslie's) — {season_label} ({len(les_rows)} tests)</h3>
<div style="overflow-x:auto">
<table>
  <thead>
    <tr><th>Run Timestamp</th><th>Test Date</th>
        <th>Free Cl</th><th>Total Cl</th><th>pH</th><th>Alk</th><th>Ca</th>
        <th>CYA</th><th>Fe</th><th>Cu</th><th>Phos</th><th>Salt</th><th>In-Store</th></tr>
  </thead>
  <tbody>{les_html}</tbody>
</table>
</div>""")

    # --- Flow/pressure (last 7 days, newest first) ---
    flow_cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    flow_rows = _load_flow(cutoff_dt=flow_cutoff)
    flow_html = "\n".join(
        f"<tr><td>{r['dt'].strftime('%Y-%m-%d %H:%M:%S')}</td>"
        f"{_td(r['flow'], '%.2f')}{_td(r['flow_std'], '%.2f')}"
        f"{_td(r['vac'], '%.1f')}"
        f"{_td(r['sys'], '%.1f')}{_td(r['f1'], '%.1f')}</tr>"
        for r in reversed(flow_rows)
    )
    sections.append(f"""
<h3>Pump House / Flow — last 7 days ({len(flow_rows)} readings)</h3>
<table>
  <thead>
    <tr><th>Timestamp (CT)</th><th>Flow (gpm)</th><th>σ (gpm)</th>
        <th>Vac Press (psi)</th><th>Sys Press (psi)</th><th>F1 Press (psi)</th></tr>
  </thead>
  <tbody>{flow_html}</tbody>
</table>""")

    return "\n".join(sections)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DOCS, exist_ok=True)
    central = pytz.timezone("US/Central")
    now_ct = datetime.datetime.now(pytz.utc).astimezone(central)
    today = now_ct.date()

    all_flume = _load_flume(today)
    current_season = get_current_season(today)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Oaks Pool Dashboard</title>
  <style>{CSS}</style>
  <script>{JS}</script>
</head>
<body>
<h1>Oaks Pool Dashboard</h1>
<div class="tabs">
  <button class="tab-btn" id="btn-summary"   onclick="showTab('summary')">Summary</button>
  <button class="tab-btn" id="btn-water"     onclick="showTab('water')">Water</button>
  <button class="tab-btn" id="btn-chemicals" onclick="showTab('chemicals')">Chemicals</button>
  <button class="tab-btn" id="btn-pumphouse" onclick="showTab('pumphouse')">Pump</button>
  <button class="tab-btn" id="btn-raw"       onclick="showTab('raw')">Raw</button>
</div>
<div id="summary"   class="tab-pane">{_summary_tab(current_season)}</div>
<div id="water"     class="tab-pane">{_water_tab(all_flume, today)}</div>
<div id="chemicals" class="tab-pane">{_chemicals_tab(current_season)}</div>
<div id="pumphouse" class="tab-pane">{_pumphouse_tab(now_ct, current_season)}</div>
<div id="raw"       class="tab-pane">{_raw_tab(today)}</div>
</body>
</html>"""

    out = os.path.join(DOCS, "index.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"✅ Dashboard written to {out}")

    if today.weekday() == 6:  # Sunday only — post to both channels
        # Only notify on the scheduled run, not every workflow_run trigger
        if os.getenv("GITHUB_EVENT_NAME") == "schedule":
            msg = "Dashboard updated: https://brianhartsell.github.io/oakspool/"
            for ch in [SLACK_CHANNEL, SLACK_BOARD_CH]:
                _post_slack(ch, msg)


if __name__ == "__main__":
    main()
