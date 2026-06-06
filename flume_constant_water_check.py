import os
import requests
import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flume_auth import get_flume_connection

# === Config ===
SILENT_MODE = False

# === Load .env
load_dotenv()
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
CCF_CONVERSION = 748.05

# === Local time and query range (NO UTC conversion)
local_tz = ZoneInfo("America/Chicago")
now = datetime.datetime.now(local_tz)
since_dt = now - datetime.timedelta(hours=4)

since = since_dt.strftime('%Y-%m-%dT%H:%M:%S')
until = now.strftime('%Y-%m-%dT%H:%M:%S')

print("Local range:", since_dt.strftime('%Y-%m-%d %H:%M:%S'), "→", now.strftime('%Y-%m-%d %H:%M:%S'))
print("Formatted for Flume:", since, "→", until)

# === Flume auth
headers, query_url = get_flume_connection()

# === Query both MIN and HR buckets
payload = {
    "queries": [
        {"request_id": "min_check", "bucket": "MIN", "since_datetime": since, "until_datetime": until},
        {"request_id": "hour_check", "bucket": "HR",  "since_datetime": since, "until_datetime": until},
    ]
}
resp = requests.post(query_url, headers=headers, json=payload).json()

# === Parse response safely
results = {}
for entry in resp.get("data", []):
    for key in entry:
        if key not in ["request_id", "success", "code", "message"]:
            results[key] = entry[key]

minute_values = [round(e["value"] / CCF_CONVERSION, 4) for e in results.get("min_check", [])]
hour_values = [round(e["value"] / CCF_CONVERSION, 4) for e in results.get("hour_check", [])]
hour_total = sum(hour_values)

total_minutes = len(minute_values)
zero_count = sum(v == 0 for v in minute_values)
nonzero_pct = 100 * (1 - zero_count / total_minutes) if total_minutes else 0

print(f"🧮 Minute readings received: {total_minutes}")
print(f"🕳️ Zero-flow minutes: {zero_count}")
print(f"Non-zero percentage: {nonzero_pct:.2f}%")

# === Alert logic
if not SILENT_MODE and nonzero_pct >= 95:
    msg = (
        f"🚰 *Water flow alert: 4 hours continuous*\n"
        f"Total use: `{hour_total:.2f} CCF`"
    )
    payload = {
        "channel": SLACK_CHANNEL,
        "text": msg,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}]
    }
    requests.post("https://slack.com/api/chat.postMessage",
                  headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
                  json=payload)
elif not SILENT_MODE and hour_total > 0 and not minute_values:
    debug_msg = (
        f"🕵️ *Discrepancy detected: Hourly > 0 but minute-level missing or blank*\n"
        f"Hourly usage: `{hour_total:.2f} CCF`\n"
        f"Minute readings: none returned"
    )
    payload = {
        "channel": HEARTBEAT_CHANNEL,
        "text": debug_msg,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": debug_msg}}]
    }
    requests.post("https://slack.com/api/chat.postMessage",
                  headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
                  json=payload)
else:
    print("Water quiet or silent mode active — no alert sent.")
