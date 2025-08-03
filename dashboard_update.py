import os
import csv
import shutil
import datetime
import requests
import base64
from pathlib import Path
from dotenv import load_dotenv
import time
import pytz

# === Load config from .env ===
load_dotenv()
REPO = os.getenv("GH_REPO")
TOKEN = os.getenv("GH_TOKEN")
BRANCH = os.getenv("GH_BRANCH", "main")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")

# === File paths (all local)
CSV_LOG = "logs/flume_usage_log.csv"
OUTPUT_DIR = "docs"
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "index.html")
CHART_PATH = "flume_usage_chart.png"
SEASON_PATH = "flume_season_comparison.png"

# === Ensure docs folder exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === Set date, system is not UTC
central = pytz.timezone("US/Central")
TODAY = datetime.datetime.now(central).date()

# === Pool season rates
SEASONS = [
    {"year": 2023, "open": datetime.date(2023, 5, 26), "close": datetime.date(2023, 9, 3), "rate": 5.60},
    {"year": 2024, "open": datetime.date(2024, 5, 24), "close": datetime.date(2024, 9, 1), "rate": 6.15},
    {"year": 2025, "open": datetime.date(2025, 5, 23), "close": datetime.date(2025, 8, 31), "rate": 6.70},
]
def get_rate(date_str):
    year = int(date_str[:4])
    for s in SEASONS:
        if s["year"] == year:
            return s["rate"]
    return 0.0

# === Load full usage log
all_rows = []
with open(CSV_LOG, newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        date_str = row["date"]
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        ccf = float(row["ccf"])
        rate = get_rate(date_str)
        cost = round(ccf * rate, 2)
        all_rows.append({
            "date": date_str,
            "date_obj": date_obj,
            "ccf": ccf,
            "rate": rate,
            "cost": cost
        })

# === Slice for last 30 days only
recent_rows = [r for r in all_rows if 0 <= (TODAY - r["date_obj"]).days < 30]

# === Build usage table HTML from recent_rows
table_rows = "\n".join([
    f"<tr><td>{r['date']}</td><td>{r['ccf']:.2f}</td><td>${r['cost']:.2f}</td></tr>"
    for r in recent_rows
])
usage_table_html = f"""<h3>📅 Last 30 Days of Use</h3>
<table border="1" cellpadding="6" cellspacing="0">
    <thead><tr><th>Date</th><th>Usage (CCF)</th><th>Cost ($)</th></tr></thead>
    <tbody>{table_rows}</tbody>
</table>
"""

# === Generate season summary using full all_rows slice
season = next((s for s in SEASONS if s["open"] <= TODAY <= s["close"]), None)
projection_html = ""
if season:
    season_rows = [r for r in all_rows if season["open"] <= r["date_obj"] <= TODAY]
    used_ccf = sum(r["ccf"] for r in season_rows)
    days_left = (season["close"] - TODAY).days + 1
    recent_avg = sum(r["ccf"] for r in recent_rows) / len(recent_rows) if recent_rows else 0.0
    cost_so_far = used_ccf * season["rate"]
    projected_cost = recent_avg * days_left * season["rate"]
    projection_html = f"""
    <h3>💰 Season Usage Summary</h3>
    <ul>
        <li><strong>Cost so far:</strong> ${cost_so_far:,.2f}</li>
        <li><strong>Projected remaining cost:</strong> ${projected_cost:,.2f}</li>
        <li>Based on {recent_avg:.2f} CCF/day × {days_left} days @ ${season['rate']:.2f}/CCF</li>
    </ul>
    """

# === Compose HTML dashboard
html_content = f"""<!DOCTYPE html>
<html><head>
    <meta charset="UTF-8">
    <title>💧 Flume Water Dashboard</title>
    <style>
        body {{ font-family: sans-serif; padding: 2em; max-width: 900px; margin: auto; }}
        h1, h2, h3 {{ margin-top: 2em; }}
        img {{ max-width: 100%; border: 1px solid #ddd; margin-bottom: 1em; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ text-align: center; padding: 0.5em; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head><body>
    <h1>💧 Flume Water Dashboard</h1>
    <h3>📈 Daily Usage – Last 30 Days</h3>
    <img src="{os.path.basename(CHART_PATH)}" alt="Usage Chart">
    <h3>📊 Pool Season Comparison</h3>
    <img src="{os.path.basename(SEASON_PATH)}" alt="Season Chart">
    {usage_table_html}
    {projection_html}
    <p><em>Dashboard auto-updated on {TODAY.isoformat()}</em></p>
</body></html>
"""

# === Save HTML
with open(OUTPUT_HTML, "w") as f:
    f.write(html_content)

# === Slack notification
def post_slack_update(post_channel):
    if not SLACK_TOKEN or not SLACK_CHANNEL:
        print("ℹ️ Slack config missing, skipping post.")
        return

    text = (
        f"💧 Dashboard updated for {TODAY.strftime('%B %d')} from Github.\n"
        f"🌐 https://brianhartsell.github.io/oakspool/\n\n"
    )

    headers = {
        "Authorization": f"Bearer {SLACK_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": post_channel,
        "text": text
    }

    r = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
    if r.ok and r.json().get("ok"):
        print("📣 Slack update sent.")
    else:
        print(f"⚠️ Slack post failed: {r.status_code} {r.text}")

# === Fire off Slack ping on Sunday only:
if TODAY.weekday() == 6:
    post_slack_update(SLACK_CHANNEL)
else:
    post_slack_update(HEARTBEAT_CHANNEL)
