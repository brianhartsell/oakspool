import os
import csv
from datetime import datetime
import requests
from zoneinfo import ZoneInfo

import pandas as pd

from api import LesliesPoolApi

# ─── CONFIG ───────────────────────────────────────────────────────────────────

LOG_DIR      = "logs"
CSV_FILE     = os.path.join(LOG_DIR, "leslies-log.csv")
DOCS_DIR     = "docs"

QUIET = 0  # zero will announce to slack, 1 will keep quiet

USERNAME     = os.getenv("LESLIES_USERNAME")
PASSWORD     = os.getenv("LESLIES_PASSWORD")
POOLID       = os.getenv("LESLIES_POOLID")
POOLNAME     = os.getenv("LESLIES_POOLNAME")
SLACK_TOKEN  = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL= os.getenv("SLACK_CHANNEL")

FIELDNAMES = [
    "run_timestamp", "test_date", "free_chlorine", "total_chlorine", "ph", "alkalinity",
    "calcium", "cyanuric_acid", "iron", "copper", "phosphates", "salt", "in_store"
]

TARGET_RANGES = {
    "free_chlorine": (1, 4),     "total_chlorine": (1, 4),
    "ph": (7.2, 7.8),            "alkalinity": (80, 120),
    "calcium": (200, 400),       "cyanuric_acid": (30, 50),
    "iron": (0, 0.3),            "copper": (0, 0.3),
    "phosphates": (0, 100),      "salt": (2500, 3500)
}

CLOSURE_LIMITS = {
    "total_chlorine": (0.5, 5.0),
    "ph": (6.8, 8.2)
}

LABELS_AND_UNITS = {
    "ph": ("pH", ""),
    "free_chlorine": ("Free Chlorine", "ppm"),
    "total_chlorine": ("Total Chlorine", "ppm"),
    "alkalinity": ("Alkalinity", "ppm"),
    "calcium": ("Calcium Hardness", "ppm"),
    "cyanuric_acid": ("Cyanuric Acid", "ppm"),
    "iron": ("Iron", "ppm"),
    "copper": ("Copper", "ppm"),
    "phosphates": ("Phosphates", "ppb"),
    "salt": ("Salt", "ppm"),
    "in_store": ("In-Store Treatment", "")
}

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def format_label(key: str) -> str:
    label, unit = LABELS_AND_UNITS.get(key, (key.replace('_', ' ').title(), ''))
    return f"{label} ({unit})" if unit else label

def format_value(key: str, val) -> str:
    _, unit = LABELS_AND_UNITS.get(key, ('', ''))
    return f"{val} {unit}" if unit else str(val)

def get_status_emoji(key: str, val) -> str:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "❓"
    low, high = TARGET_RANGES.get(key, (None, None))
    c_low, c_high = CLOSURE_LIMITS.get(key, (None, None))
    if c_low is not None and (v < c_low or v > c_high):
        return "🚨"
    if low is not None and low <= v <= high:
        return "✅"
    return "❗️"

def load_last_logged_test() -> dict:
    if not os.path.exists(CSV_FILE):
        return {}
    with open(CSV_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
        return rows[-1] if rows else {}

def is_duplicate_test(new_data: dict, last_data: dict) -> bool:
    keys_to_compare = [k for k in FIELDNAMES if k != "run_timestamp"]
    return all(str(new_data.get(k)).strip() == str(last_data.get(k)).strip() for k in keys_to_compare)

def append_to_csv(data: dict, csv_file: str = CSV_FILE, sep: str = ","):
    """
    Append one test record using pandas, guaranteed to match FIELDNAMES order
    and format run_timestamp as 'YYYY-MM-DD HH:MM:SS'.
    """

    # 1) Filter & order your dict so it only has the columns you expect
    row = {col: data.get(col, "") for col in FIELDNAMES}

    # 2) Build a single-row DataFrame with that exact column order
    df_new = pd.DataFrame([row], columns=FIELDNAMES)

    # 3) If your run_timestamp is a Python datetime, convert it to dtype datetime64
    #    so pandas can apply date_format.  Otherwise, it'll just echo your string.
    if not pd.api.types.is_datetime64_any_dtype(df_new["run_timestamp"]):
        try:
            df_new["run_timestamp"] = pd.to_datetime(
                df_new["run_timestamp"],
                infer_datetime_format=True,
                errors="raise"
            )
        except Exception:
            # fallback: assume you already formatted it as '%Y-%m-%d %H:%M:%S'
            pass

    # 4) Append to CSV — check existence before any file ops to get write_header right
    write_header = not os.path.exists(csv_file)
    if not write_header:
        with open(csv_file, "r") as f:
            lines = [line for line in f if line.strip()]
        with open(csv_file, "w") as f:
            f.writelines(lines)
    with open(csv_file, "a", newline="") as f:
        df_new.to_csv(
            f,
            sep=sep,
            header=write_header,
            index=False,
            date_format="%Y-%m-%d %H:%M:%S"
        )

    print(f"✅ Logged new test for {data['test_date']} at {data['run_timestamp']}")


def build_test_summary(data: dict) -> str:
    keys = ["ph", "total_chlorine", "free_chlorine", "alkalinity", "cyanuric_acid"]
    lines = []
    for key in keys:
        val = data.get(key)

        # Special case: flag if free chlorine is 0.2 or more below total chlorine
        if key == "free_chlorine":
            try:
                fc = float(val)
                tc = float(data.get("total_chlorine", 0))
                if tc - fc >= 0.2:
                    emoji = "⚠️"
                else:
                    emoji = get_status_emoji(key, val)
            except (TypeError, ValueError):
                emoji = "❓"
        else:
            emoji = get_status_emoji(key, val)
        label = format_label(key)
        value = format_value(key, val)
        lines.append(f"{emoji} {label}: {value}")
    return "\n".join(lines)

def post_slack_message(channel: str, text: str):
    if not SLACK_TOKEN or not channel:
        print("ℹ️ Slack config missing, skipping post.")
        return
    headers = {
        "Authorization": f"Bearer {SLACK_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"channel": channel, "text": text}
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers, json=payload
    )
    if r.ok and r.json().get("ok"):
        print("📣 Slack update sent.")
    else:
        print(f"⚠️ Slack post failed: {r.status_code} {r.text}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    api = LesliesPoolApi(
        username=USERNAME,
        password=PASSWORD,
        pool_profile_id=POOLID,
        pool_name=POOLNAME
    )
    if not api.authenticate():
        print("⚠️ Leslie's login failed, skipping this run.")
        return

    data = api.fetch_water_test_data()

    # Normalize "N/A" to 0
    for key, val in data.items():
        if isinstance(val, str) and val.strip().upper() == "N/A":
            data[key] = 0

    central_time = datetime.now(ZoneInfo("America/Chicago"))
    human_time = central_time.strftime("%B %d, %Y at %#I:%M %p")
    run_timestamp = central_time.strftime("%Y-%m-%d %H:%M:%S")
    data["run_timestamp"] = run_timestamp

    last_logged = load_last_logged_test()

    print(data)

    # --- SAFETY PATCH: Skip run if Leslie's returned no usable data ---
    required_keys = ["test_date", "free_chlorine", "total_chlorine", "ph"]

    missing = [k for k in required_keys if k not in data or not data[k]]

    if missing:
        print("❌ Leslie's API returned incomplete data, skipping this run.")
        print("Missing:", missing)
        print("Raw data:", data)
        return

    if is_duplicate_test(data, last_logged):
        print(f"ℹ️ Already logged {data['test_date']}")
    else:
        print(f"Logging new test: {data['test_date']}")
        append_to_csv(data)
        summary = build_test_summary(data)

        if QUIET == 0:
            post_slack_message(
                SLACK_CHANNEL,
                f"New water test logged during run at {human_time}:\n{summary}"
            )

            if "🚨" in summary:
                post_slack_message(
                    SLACK_CHANNEL,
                    "🚨 One or more readings are outside operating limits.\nFix immediately!"
                )
        else:
            print("Quiet mode enabled, should have pinged slack here")

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
