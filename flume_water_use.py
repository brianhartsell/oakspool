import os
import csv
import json
import base64
import requests
import datetime
import matplotlib.pyplot as plt
import pytz
import pandas as pd
import shutil
# from dotenv import load_dotenv

# === Load environment variables ===
# load_dotenv()
USERNAME = os.getenv("FLUME_USERNAME")
PASSWORD = os.getenv("FLUME_PASSWORD")
CLIENT_ID = os.getenv("FLUME_CLIENT_ID")
CLIENT_SECRET = os.getenv("FLUME_CLIENT_SECRET")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
CSV_FILENAME = 'logs/flume_usage_log.csv'
HEARTBEAT_LOG = "heartbeats/flume_heartbeat_usage.log"
CCF_CONVERSION = 748.05

central = pytz.timezone('US/Central')
now = datetime.datetime.now(pytz.utc).astimezone(central)

# === Pool seasons
POOL_SEASONS = [
    {"year": 2023, "open": datetime.date(2023, 5, 26), "close": datetime.date(2023, 9, 3), "rate": 5.60},
    {"year": 2024, "open": datetime.date(2024, 5, 24), "close": datetime.date(2024, 9, 1), "rate": 6.15},
    {"year": 2025, "open": datetime.date(2025, 5, 23), "close": datetime.date(2025, 8, 31), "rate": 6.70},
]

def get_rate_for_date(date_str):
    year = int(date_str[:4])
    for s in POOL_SEASONS:
        if s["year"] == year:
            return s["rate"]
    return 0

def generate_sparkline(values):
    bars = "▁▂▃▄▅▆▇█"
    min_v, max_v = min(values), max(values)
    span = max_v - min_v if max_v != min_v else 1
    return ''.join(bars[round((v - min_v) / span * (len(bars) - 1))] for v in values)

def format_usage_table(dates, values):
    rows = ["```", "📊 14-Day Water Usage Summary:", "Date       |  Usage (CCF)  |   Cost", "-----------|---------------|---------"]
    for d, v in zip(dates, values):
        rate = get_rate_for_date(d) or 0
        cost = v * rate
        rows.append(f"{d} |     {v:6.2f}     | ${cost:7.2f}")
    rows.append("```")
    return "\n".join(rows)

# === Load CSV log
updated_data = {}
with open(CSV_FILENAME, newline='') as f:
    for row in csv.DictReader(f):
        updated_data[row["date"]] = float(row["ccf"])

# === Heartbeat check and post (first run of the day)
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
today_str = now.date().isoformat()

already_sent = False
if os.path.exists(HEARTBEAT_LOG):
    with open(HEARTBEAT_LOG) as f:
        already_sent = today_str in f.read()

if not already_sent:
    msg = f"❤️ Flume Updater ran {today_str} from GitHub."
    payload = {
        "channel": HEARTBEAT_CHANNEL,
        "text": msg,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}]
    }
    response = requests.post("https://slack.com/api/chat.postMessage",
                             headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
                             json=payload)
    with open(HEARTBEAT_LOG, "a") as f:
        f.write(today_str + "\n")

# === Authenticate with Flume
auth = requests.post(
    "https://api.flumetech.com/oauth/token",
    data={
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": USERNAME,
        "password": PASSWORD,
    }
)
access_token = auth.json()["data"][0]["access_token"]
headers = {"Authorization": f"Bearer {access_token}"}
user_id = json.loads(base64.urlsafe_b64decode(access_token.split('.')[1] + "=="))["user_id"]

device = requests.get(f"https://api.flumetech.com/users/{user_id}/devices", headers=headers)
device_id = [d for d in device.json()["data"] if d["type"] == 2][0]["id"]
query_url = f"https://api.flumetech.com/users/{user_id}/devices/{device_id}/query"

# === Pull and plot 30-day usage
chart_payload = {
    "queries": [{
        "request_id": "chart",
        "bucket": "DAY",
        "since_datetime": (now - datetime.timedelta(days=30)).strftime('%Y-%m-%dT00:00:00Z'),
        "until_datetime": now.strftime('%Y-%m-%dT23:59:59Z'),
    }]
}
chart_resp = requests.post(query_url, headers=headers, json=chart_payload)
chart_data = chart_resp.json()["data"][0]["chart"]
chart_dates = [e["datetime"][:10] for e in chart_data]
chart_values = [round(e["value"] / CCF_CONVERSION, 4) for e in chart_data]

# Save chart
plt.figure(figsize=(10, 6))
plt.plot(chart_dates, chart_values, marker='o', color='teal')
plt.ylabel("Usage [CCF]")
plt.xticks(rotation=45)
plt.tight_layout()
plt.grid()
plt.savefig("docs/flume_usage_chart.png")
plt.close()

# === Safely update CSV log with recent values
csv_path = CSV_FILENAME
backup_dir = "flume_log_backup"
os.makedirs(backup_dir, exist_ok=True)
timestamp = now.strftime("%Y%m%d_%H%M%S")
backup_path = os.path.join(backup_dir, f"flume_usage_log.csv.{timestamp}.bak")
shutil.copyfile(csv_path, backup_path)

# === Read existing log
existing = {}
with open(csv_path, newline='') as f:
    for row in csv.DictReader(f):
        existing[row["date"]] = float(row["ccf"])

# === Only overwrite within last 3 days
cutoff = (now - datetime.timedelta(days=3)).date()
new_entries = {}
for entry in chart_data:
    date_str = entry["datetime"][:10]
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    value = round(entry["value"] / CCF_CONVERSION, 4)

    if date_str not in existing or date_obj >= cutoff:
        new_entries[date_str] = value
    else:
        new_entries[date_str] = existing[date_str]  # preserve old

# === Write merged log, sorted by date
merged = {**existing, **new_entries}
with open(csv_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["date", "ccf"])
    for d in sorted(merged):
        writer.writerow([d, merged[d]])

# === Pool season rolling average comparison
df_rows = []
with open(CSV_FILENAME, newline='') as f:
    for row in csv.DictReader(f):
        d = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
        df_rows.append({"date": d, "year": d.year, "ccf": float(row["ccf"])})
df = pd.DataFrame(df_rows)

records = []
for season in POOL_SEASONS:
    start = season["open"]
    year = season["year"]
    sub = df[(df["year"] == year) & (df["date"] >= start)].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    start_ts = pd.to_datetime(start)
    sub["days_since_open"] = (sub["date"] - start_ts).dt.days
    sub.sort_values("date", inplace=True)
    sub["rolling_avg"] = sub["ccf"].rolling(window=14).mean()
    sub["label"] = str(year)
    records.append(sub[["days_since_open", "rolling_avg", "label"]])

combined = pd.concat(records)
plt.figure(figsize=(10, 6))
for label, group in combined.groupby("label"):
    plt.plot(group["days_since_open"], group["rolling_avg"], label=label)
plt.xlabel("Days Since Pool Open")
plt.ylabel("Water Usage (CCF)")
plt.grid(True)
plt.legend(title="Year")
plt.tight_layout()
plt.savefig("docs/flume_season_comparison.png")
plt.close()
