import os
import csv
import shutil
import datetime
import requests
import base64
from pathlib import Path
from dotenv import load_dotenv
import time

# === Load config from .env ===
load_dotenv()
REPO = os.getenv("GH_REPO")
TOKEN = os.getenv("GH_TOKEN")
BRANCH = os.getenv("GH_BRANCH", "main")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
TODAY = datetime.date.today()

# === File paths (all local)
CSV_LOG = "flume_usage_log.csv"
CHART_PATH = "flume_usage_chart.png"
SEASON_PATH = "flume_season_comparison.png"
OUTPUT_DIR = "docs"
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "index.html")

# === Ensure docs folder exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === Copy charts to docs/
for img in [CHART_PATH, SEASON_PATH]:
    target = os.path.join(OUTPUT_DIR, os.path.basename(img))
    shutil.copyfile(img, target)

# === Load and filter usage data
rows = []
with open(CSV_LOG, newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        date_obj = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
        if 0 <= (TODAY - date_obj).days < 30:
            rows.append({
                "date": row["date"],
                "ccf": float(row["ccf"]),
                "rate": None,
                "cost": 0.0
            })

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

# === Enrich rows with rate and cost
for r in rows:
    r["rate"] = get_rate(r["date"])
    r["cost"] = round(r["ccf"] * r["rate"], 2)

# === Build usage table HTML
table_rows = "\n".join([
    f"<tr><td>{r['date']}</td><td>{r['ccf']:.2f}</td><td>${r['cost']:.2f}</td></tr>" for r in rows
])
usage_table_html = f"""
<h3>📅 Last 30 Days of Use</h3>
<table border="1" cellpadding="6" cellspacing="0">
    <thead><tr><th>Date</th><th>Usage (CCF)</th><th>Cost ($)</th></tr></thead>
    <tbody>{table_rows}</tbody>
</table>
"""

# === Generate season summary
season = next((s for s in SEASONS if s["open"] <= TODAY <= s["close"]), None)
projection_html = ""
if season:
    used = [r["ccf"] for r in rows if season["open"].isoformat() <= r["date"] <= TODAY.isoformat()]
    days_left = (season["close"] - TODAY).days + 1
    recent_avg = sum([r["ccf"] for r in rows]) / len(rows)
    cost_so_far = sum(used) * season["rate"]
    projected = recent_avg * days_left * season["rate"]
    projection_html = f"""
    <h3>💰 Season Usage Summary</h3>
    <ul>
        <li><strong>Cost so far:</strong> ${cost_so_far:,.2f}</li>
        <li><strong>Projected remaining cost:</strong> ${projected:,.2f}</li>
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

# === GitHub upload helper
def push_to_github(filepath):
    url = f"https://api.github.com/repos/{REPO}/contents/{filepath}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    content = Path(filepath).read_bytes()
    b64 = base64.b64encode(content).decode("utf-8")

    # Check for existing file
    sha = None
    res = requests.get(url, headers=headers)
    if res.status_code == 200: sha = res.json().get("sha")

    payload = {
        "message": f"Update {filepath} on {TODAY.isoformat()}",
        "content": b64,
        "branch": BRANCH
    }
    if sha: payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    status = "✅" if r.status_code in [200, 201] else f"⚠️ {r.json()}"
    print(f"{status} pushed {filepath}")

# === Push dashboard files
for fname in [os.path.basename(OUTPUT_HTML), os.path.basename(CHART_PATH), os.path.basename(SEASON_PATH)]:
    push_to_github(f"{OUTPUT_DIR}/{fname}")
    time.sleep(300)  # quick hack to stagger builds

# === Slack notification
def post_slack_heartbeat():
    if not SLACK_TOKEN or not SLACK_CHANNEL:
        print("ℹ️ Slack config missing, skipping post.")
        return

    text = (
        f"💧 Dashboard updated for {TODAY.strftime('%B %d')}\n"
        f"🌐 https://brianhartsell.github.io/oakspool/\n\n"
    )

    headers = {
        "Authorization": f"Bearer {SLACK_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": SLACK_CHANNEL,
        "text": text
    }

    r = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
    if r.ok and r.json().get("ok"):
        print("📣 Slack heartbeat sent.")
    else:
        print(f"⚠️ Slack post failed: {r.status_code} {r.text}")

# === Fire off Slack ping
post_slack_heartbeat()