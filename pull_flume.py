import csv
import datetime
import os

import pytz
import requests

from flume_auth import get_flume_connection

CSV_FILE = "logs/flume_usage_log.csv"
CCF_CONVERSION = 748.05


def main():
    central = pytz.timezone("US/Central")
    now = datetime.datetime.now(pytz.utc).astimezone(central)

    headers, query_url = get_flume_connection()

    payload = {
        "queries": [{
            "request_id": "usage",
            "bucket": "DAY",
            "since_datetime": (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z"),
            "until_datetime": now.strftime("%Y-%m-%dT23:59:59Z"),
        }]
    }
    resp = requests.post(query_url, headers=headers, json=payload)
    resp_json = resp.json()
    if resp.status_code != 200 or not resp_json.get("data"):
        print(f"❌ Flume query failed ({resp.status_code}): {resp_json}")
        raise SystemExit(1)

    raw = resp_json["data"][0]["usage"]

    existing = {}
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, newline="") as f:
            for row in csv.DictReader(f):
                existing[row["date"]] = float(row["ccf"])

    # Re-accept last 3 days — Flume sometimes corrects recent readings retroactively
    cutoff = (now - datetime.timedelta(days=3)).date()
    merged = dict(existing)
    for entry in raw:
        date_str = entry["datetime"][:10]
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        value = round(entry["value"] / CCF_CONVERSION, 4)
        if date_str not in merged or date_obj >= cutoff:
            merged[date_str] = value

    tmp = CSV_FILE + ".tmp"
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
    with open(tmp, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ccf"])
        for d in sorted(merged):
            writer.writerow([d, merged[d]])
    os.replace(tmp, CSV_FILE)
    print(f"✅ Flume log updated — {len(merged)} entries, latest: {max(merged)}")


if __name__ == "__main__":
    main()
