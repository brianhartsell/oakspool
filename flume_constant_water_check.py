import os
import json
import base64
import requests
import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# === Config ===
SILENT_MODE = False  # Set to False to send alerts to Slack

# === Load .env
load_dotenv()
USERNAME = os.getenv("FLUME_USERNAME")
PASSWORD = os.getenv("FLUME_PASSWORD")
CLIENT_ID = os.getenv("FLUME_CLIENT_ID")
CLIENT_SECRET = os.getenv("FLUME_CLIENT_SECRET")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
CCF_CONVERSION = 748.05
HEARTBEAT_LOG = "heartbeats/flume_heartbeat_constant.log"

# === Local time and query range (NO UTC conversion)
local_tz = ZoneInfo("America/Chicago")
now = datetime.datetime.now(local_tz)
since_dt = now - datetime.timedelta(hours=4)
today_str = now.date().isoformat()

since = since_dt.strftime('%Y-%m-%dT%H:%M:%S')
until = now.strftime('%Y-%m-%dT%H:%M:%S')

# === Visual confirmation of query window
print("Local range:", since_dt.strftime('%Y-%m-%d %H:%M:%S'), "→", now.strftime('%Y-%m-%d %H:%M:%S'))
print("Formatted for Flume:", since, "→", until)

# === Heartbeat (log once per day)
already_sent = os.path.exists(HEARTBEAT_LOG) and today_str in open(HEARTBEAT_LOG).read()
if not already_sent:
    msg = f"❤️ Constant water check is running on {today_str} from GitHub."
    if not SILENT_MODE:
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

# === Flume auth
auth = requests.post("https://api.flumetech.com/oauth/token", data={
    "grant_type": "password",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "username": USERNAME,
    "password": PASSWORD,
})
access_token = auth.json()["data"][0]["access_token"]
headers = {"Authorization": f"Bearer {access_token}"}
user_id = json.loads(base64.urlsafe_b64decode(access_token.split('.')[1] + "=="))["user_id"]

# === Device ID (type 2)
devices = requests.get(f"https://api.flumetech.com/users/{user_id}/devices", headers=headers).json()
device_id = [d for d in devices["data"] if d["type"] == 2][0]["id"]
query_url = f"https://api.flumetech.com/users/{user_id}/devices/{device_id}/query"

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

total_minutes = len(minute_values)
zero_count = sum(v == 0 for v in minute_values)

print(f"🧮 Minute readings received: {total_minutes}")
print(f"🕳️ Zero-flow minutes: {zero_count}")

min_nonzero = all(v > 0 for v in minute_values)
hour_total = sum(hour_values)

# === Alert logic
if not SILENT_MODE and min_nonzero:
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

