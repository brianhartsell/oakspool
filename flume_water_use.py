import os
import csv
import requests
import datetime
import matplotlib.pyplot as plt
import pytz
import pandas as pd
from seasons_loader import get_rate_for_date, get_season_by_year, load
from flume_auth import get_flume_connection

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

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
CSV_FILENAME = 'logs/flume_usage_log.csv'
HEARTBEAT_LOG = "heartbeats/flume_heartbeat_usage.log"
CCF_CONVERSION = 748.05

central = pytz.timezone('US/Central')
now = datetime.datetime.now(pytz.utc).astimezone(central)

# === Heartbeat check and post (first run of the day)
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
    requests.post("https://slack.com/api/chat.postMessage",
                  headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
                  json=payload)
    with open(HEARTBEAT_LOG, "a") as f:
        f.write(today_str + "\n")

# === Authenticate with Flume
headers, query_url = get_flume_connection()

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
chart_resp_json = chart_resp.json()
if chart_resp.status_code != 200 or not chart_resp_json.get("data"):
    print(f"❌ Flume usage query failed ({chart_resp.status_code}): {chart_resp_json}")
    raise SystemExit(1)
chart_data = chart_resp_json["data"][0]["chart"]
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

# === Read existing log
existing = {}
if os.path.exists(CSV_FILENAME):
    with open(CSV_FILENAME, newline='') as f:
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

# === Write merged log atomically, sorted by date
merged = {**existing, **new_entries}
tmp_path = CSV_FILENAME + ".tmp"
with open(tmp_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["date", "ccf"])
    for d in sorted(merged):
        writer.writerow([d, merged[d]])
os.replace(tmp_path, CSV_FILENAME)

# === Pool season rolling average comparison
df_rows = []
with open(CSV_FILENAME, newline='') as f:
    for row in csv.DictReader(f):
        d = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
        df_rows.append({"date": d, "year": d.year, "ccf": float(row["ccf"])})
df = pd.DataFrame(df_rows)

records = []
today_iso = now.date().isoformat()
current_season = get_season_by_year(int(today_iso[:4]))
for season in load(path=os.path.join(os.path.dirname(__file__), "seasons.txt")):
    start = season.open
    year = season.year
    if current_season is not None and year == current_season.year:
        # Current/open season: show data from open through today
        end = now.date()
    else:
        # Closed season: show only within the season dates
        end = season.close
    sub = df[(df["year"] == year) & (df["date"] >= start) & (df["date"] <= end)].copy()
    if sub.empty:
        continue
    sub["date"] = pd.to_datetime(sub["date"])
    start_ts = pd.to_datetime(start)
    sub["days_since_open"] = (sub["date"] - start_ts).dt.days
    sub.sort_values("date", inplace=True)
    sub["rolling_avg"] = sub["ccf"].rolling(window=14, min_periods=1).mean()
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
