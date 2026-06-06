import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from leslies_api import InvalidAuthError, LesliesPoolApi, PoolNotFoundError

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
    try:
        _, relate_id = LesliesPoolApi.resolve_relate_customer_id(USERNAME, PASSWORD)
    except InvalidAuthError:
        print("⚠️ Leslie's login failed.")
        raise SystemExit(1)

    try:
        pools = LesliesPoolApi.discover_pool_profiles(USERNAME, relate_id)
    except PoolNotFoundError as e:
        print(f"⚠️ {e}")
        raise SystemExit(1)

    pool = next((p for p in pools if p.id == POOLID), pools[0])
    print(f"ℹ️ Using pool profile: {pool.pool_name} (id={pool.id})")

    api = LesliesPoolApi(
        relate_customer_id=relate_id,
        email=USERNAME,
        pool_profile_id=pool.id,
        pool_name=pool.pool_name,
    )
    data = api.fetch_water_test_data()

    # Normalize: None → "", bool → string, legacy "N/A" → ""
    for k, v in list(data.items()):
        if v is None:
            data[k] = ""
        elif isinstance(v, bool):
            data[k] = str(v)
        elif isinstance(v, str) and v.strip().upper() == "N/A":
            data[k] = ""

    required = ["test_date", "free_chlorine", "total_chlorine", "ph"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        print(f"ℹ️ No complete test data returned (missing: {missing}) — no test on file yet, skipping.")
        return

    central = ZoneInfo("America/Chicago")
    now = datetime.now(central)
    data["run_timestamp"] = now.strftime("%Y-%m-%d %H:%M:%S")

    last = _load_last_logged()
    if _is_duplicate(data, last):
        print(f"ℹ️ Already logged test for {data['test_date']}, nothing new.")
        return

    _append(data)
    print(f"✅ Logged new test: {data['test_date']}")

    # Only notify Slack for fresh tests. The Boomi API returns full history, so
    # the first run of a new season would otherwise notify for last season's data.
    days_since = data.get("days_since_test")
    try:
        is_fresh = int(days_since) <= 3
    except (TypeError, ValueError):
        is_fresh = True  # unknown — notify anyway

    if not is_fresh:
        print(f"ℹ️ Test is {days_since} days old — skipping Slack notification.")
        return

    summary = _build_summary(data)
    hour = now.strftime("%I").lstrip("0") or "12"
    human_time = now.strftime(f"%B %d, %Y at {hour}:%M %p")
    _post_slack(SLACK_CHANNEL, f"New water test logged {human_time}:\n{summary}")

    if "🚨" in summary:
        _post_slack(SLACK_CHANNEL, "🚨 One or more readings are outside operating limits. Fix immediately!")


if __name__ == "__main__":
    main()
