import datetime
import os
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from flume_auth import get_flume_connection

load_dotenv()

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
HEARTBEAT_CHANNEL = os.getenv("SLACK_HEARTBEAT_CHANNEL")
CCF_CONVERSION = 748.05


def _post(channel, text):
    if not SLACK_TOKEN or not channel:
        return
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json={
            "channel": channel,
            "text": text,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        },
    )


def main():
    local_tz = ZoneInfo("America/Chicago")
    now = datetime.datetime.now(local_tz)
    since_dt = now - datetime.timedelta(hours=4)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    until = now.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Checking: {since} → {until}")

    headers, query_url = get_flume_connection()

    resp = requests.post(
        query_url,
        headers=headers,
        json={
            "queries": [
                {"request_id": "min_check", "bucket": "MIN", "since_datetime": since, "until_datetime": until},
                {"request_id": "hour_check", "bucket": "HR",  "since_datetime": since, "until_datetime": until},
            ]
        },
    ).json()

    results = {}
    for entry in resp.get("data", []):
        for key in entry:
            if key not in ("request_id", "success", "code", "message"):
                results[key] = entry[key]

    minute_values = [round(e["value"] / CCF_CONVERSION, 4) for e in results.get("min_check", [])]
    hour_values   = [round(e["value"] / CCF_CONVERSION, 4) for e in results.get("hour_check", [])]
    hour_total    = sum(hour_values)

    total_minutes = len(minute_values)
    zero_count    = sum(v == 0 for v in minute_values)
    nonzero_pct   = 100 * (1 - zero_count / total_minutes) if total_minutes else 0

    print(f"Readings: {total_minutes} min, {zero_count} zero, {nonzero_pct:.1f}% non-zero")

    if nonzero_pct >= 95:
        _post(SLACK_CHANNEL,
              f"🚰 *Water flow alert: 4 hours continuous*\nTotal use: `{hour_total:.2f} CCF`")
    elif hour_total > 0 and not minute_values:
        _post(HEARTBEAT_CHANNEL,
              f"🕵️ *Discrepancy: hourly > 0 but no minute-level data*\nHourly: `{hour_total:.2f} CCF`")
    else:
        print("Water quiet — no alert.")


if __name__ == "__main__":
    main()
