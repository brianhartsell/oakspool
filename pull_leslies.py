import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from leslies_api import LesliesPoolApi

LOG_DIR = "logs"
CSV_FILE = os.path.join(LOG_DIR, "leslies-log.csv")

USERNAME = os.getenv("LESLIES_USERNAME")
PASSWORD = os.getenv("LESLIES_PASSWORD")
POOLID = os.getenv("LESLIES_POOLID")
POOLNAME = os.getenv("LESLIES_POOLNAME")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

FIELDNAMES = [
    "run_timestamp", "test_date", "free_chlorine", "total_chlorine", "ph", "alkalinity",
    "calcium", "cyanuric_acid", "iron", "copper", "phosphates", "salt", "in_store",
]

TARGET_RANGES = {
    "free_chlorine":  (1, 4),
    "total_chlorine": (1, 4),
    "ph":             (7.2, 7.8),
    "alkalinity":     (80, 120),
    "calcium":        (200, 400),
    "cyanuric_acid":  (30, 50),
    "iron":           (0, 0.3),
    "copper":         (0, 0.3),
    "phosphates":     (0, 100),
    "salt":           (2500, 3500),
}

CLOSURE_LIMITS = {
    "total_chlorine": (0.5, 5.0),
    "ph":             (6.8, 8.2),
}

LABELS_AND_UNITS = {
    "ph":             ("pH", ""),
    "free_chlorine":  ("Free Chlorine", "ppm"),
    "total_chlorine": ("Total Chlorine", "ppm"),
    "alkalinity":     ("Alkalinity", "ppm"),
    "calcium":        ("Calcium Hardness", "ppm"),
    "cyanuric_acid":  ("Cyanuric Acid", "ppm"),
    "iron":           ("Iron", "ppm"),
    "copper":         ("Copper", "ppm"),
    "phosphates":     ("Phosphates", "ppb"),
    "salt":           ("Salt", "ppm"),
}


def _load_last_logged():
    if not os.path.exists(CSV_FILE):
        return {}
    with open(CSV_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-1] if rows else {}


def _is_duplicate(new, last):
    keys = [k for k in FIELDNAMES if k != "run_timestamp"]
    return all(str(new.get(k, "")).strip() == str(last.get(k, "")).strip() for k in keys)


def _append(data):
    row = {col: data.get(col, "") for col in FIELDNAMES}
    os.makedirs(LOG_DIR, exist_ok=True)
    write_header = not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _status_emoji(key, val):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "❓"
    lo, hi = TARGET_RANGES.get(key, (None, None))
    clo, chi = CLOSURE_LIMITS.get(key, (None, None))
    if clo is not None and (v < clo or v > chi):
        return "🚨"
    if lo is not None and lo <= v <= hi:
        return "✅"
    return "❗️"


def _build_summary(data):
    keys = ["ph", "total_chlorine", "free_chlorine", "alkalinity", "cyanuric_acid"]
    lines = []
    for key in keys:
        val = data.get(key)
        if key == "free_chlorine":
            try:
                fc, tc = float(val), float(data.get("total_chlorine", 0))
                emoji = "⚠️" if tc - fc >= 0.2 else _status_emoji(key, val)
            except (TypeError, ValueError):
                emoji = "❓"
        else:
            emoji = _status_emoji(key, val)
        label, unit = LABELS_AND_UNITS.get(key, (key.replace("_", " ").title(), ""))
        label_str = f"{label} ({unit})" if unit else label
        lines.append(f"{emoji} {label_str}: {val}{' ' + unit if unit else ''}")
    return "\n".join(lines)


def _post_slack(channel, text):
    if not SLACK_TOKEN or not channel:
        print("ℹ️ Slack not configured, skipping.")
        return
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json={"channel": channel, "text": text},
    )
    if r.ok and r.json().get("ok"):
        print("📣 Slack update sent.")
    else:
        print(f"⚠️ Slack post failed: {r.status_code}")


def main():
    api = LesliesPoolApi(
        username=USERNAME, password=PASSWORD,
        pool_profile_id=POOLID, pool_name=POOLNAME,
    )
    if not api.authenticate():
        print("⚠️ Leslie's login failed.")
        raise SystemExit(1)

    data = api.fetch_water_test_data()

    for k, v in data.items():
        if isinstance(v, str) and v.strip().upper() == "N/A":
            data[k] = 0

    required = ["test_date", "free_chlorine", "total_chlorine", "ph"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        print(f"❌ Leslie's returned incomplete data — missing: {missing}")
        raise SystemExit(1)

    central = ZoneInfo("America/Chicago")
    now = datetime.now(central)
    data["run_timestamp"] = now.strftime("%Y-%m-%d %H:%M:%S")

    last = _load_last_logged()
    if _is_duplicate(data, last):
        print(f"ℹ️ Already logged test for {data['test_date']}, nothing new.")
        return

    _append(data)
    print(f"✅ Logged new test: {data['test_date']}")

    summary = _build_summary(data)
    hour = now.strftime("%I").lstrip("0") or "12"
    human_time = now.strftime(f"%B %d, %Y at {hour}:%M %p")
    _post_slack(SLACK_CHANNEL, f"New water test logged {human_time}:\n{summary}")

    if "🚨" in summary:
        _post_slack(SLACK_CHANNEL, "🚨 One or more readings are outside operating limits. Fix immediately!")


if __name__ == "__main__":
    main()
