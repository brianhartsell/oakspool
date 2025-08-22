import os
import csv
from datetime import datetime, timedelta
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import matplotlib.pyplot as plt

from api import LesliesPoolApi

# ─── CONFIG ───────────────────────────────────────────────────────────────────

LOG_DIR      = "logs"
CSV_FILE     = os.path.join(LOG_DIR, "leslies-log.csv")
DOCS_DIR     = "docs"

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
    "total_chlorine": (0.5, 5.5),
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
    return all(str(new_data.get(k)) == str(last_data.get(k)) for k in keys_to_compare)

def append_to_csv(data: dict):
    write_header = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            w.writeheader()
        w.writerow(data)
    print(f"✅ Logged new test for {data['test_date']} at {data['run_timestamp']}")

def build_test_summary(data: dict) -> str:
    keys = ["ph", "total_chlorine", "free_chlorine", "alkalinity", "cyanuric_acid"]
    lines = []
    for key in keys:
        val = data.get(key)
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

def plot_last_30_days(csv_path: str):
    df = pd.read_csv(csv_path, parse_dates=["test_date"])
    # Replace "N/A" strings with 0
    df.replace("N/A", 0, inplace=True)

    df["run_timestamp"] = pd.to_datetime(df["run_timestamp"], errors="coerce")
    df = df.sort_values("test_date")
    cutoff = datetime.now(ZoneInfo("America/Chicago")) - timedelta(days=30)
    recent = df[df["run_timestamp"] >= cutoff]

    plots = {
        "chlorine":      ["free_chlorine", "total_chlorine"],
        "ph":            ["ph"],
        "alkalinity":    ["alkalinity"],
        "calcium":       ["calcium"],
        "cyanuric_acid": ["cyanuric_acid"],
        "iron":          ["iron"],
        "copper":        ["copper"],
        "phosphates":    ["phosphates"],
        "salt":          ["salt"],
        "in_store":      ["in_store"]
    }

    for name, cols in plots.items():
        fig, ax = plt.subplots(figsize=(10, 4))
        y_all = pd.Series(dtype="float64")

        for col in cols:
            if col not in recent.columns:
                continue
            y = pd.to_numeric(recent[col], errors="coerce")
            if not y.dropna().empty:
                y_all = pd.concat([y_all, y.dropna()], ignore_index=True)

            # draw recommended band
            lo, hi = TARGET_RANGES.get(col, (None, None))
            if col in TARGET_RANGES:
                ax.axhspan(lo, hi, color="green", alpha=0.1)

            # highlight out‐of‐closure and draw caution/closure bands
            if col in CLOSURE_LIMITS:
                c_lo, c_hi = CLOSURE_LIMITS[col]
                mask = (y < c_lo) | (y > c_hi)
                if mask.any():
                    dates = recent.loc[mask, "run_timestamp"]
                    ax.scatter(dates, y[mask], color="red", edgecolor="black", zorder=5)
            
                # Always draw caution and closure bands
                if lo is not None and c_lo < lo:
                    ax.axhspan(c_lo, lo, color="yellow", alpha=0.1)
                if hi is not None and c_hi > hi:
                    ax.axhspan(hi, c_hi, color="yellow", alpha=0.1)
                y_max = y.max()
                if pd.notna(y_max):
                    ax.axhspan(0, c_lo, color="red", alpha=0.05)
                    ax.axhspan(c_hi, y_max, color="red", alpha=0.05)

            ax.plot(
                recent["run_timestamp"], y,
                marker="o", label=format_label(col)
            )

        # tighten Y axis
        y_clean = y_all.dropna()
        if not y_clean.empty:
            mn, mx = y_clean.min(), y_clean.max()
            if all(map(lambda v: isinstance(v, (int, float)) and not (v != v or v in (float("inf"), float("-inf"))), [mn, mx])):
                buf = (mx - mn) * 0.1 if mx > mn else 1
                ax.set_ylim(mn - buf, mx + buf)

        ax.set_xlabel("Date")
        
        ax.set_ylabel(format_label(name))
        fig.autofmt_xdate(rotation=30)
        # legend only for chlorine data series
        if name == "chlorine":
            h, l = ax.get_legend_handles_labels()
            allowed = {format_label("free_chlorine"), format_label("total_chlorine")}
            data_pairs = [
                (hndl, lbl)
                for hndl, lbl in zip(h, l)
                if lbl in allowed
            ]
            if data_pairs:
                handles, labels = zip(*data_pairs)
                ax.legend(handles, labels)


        ax.grid(alpha=0.3)
        fig.tight_layout()

        out_path = os.path.join(DOCS_DIR, f"{name}.png")
        fig.savefig(out_path)
        plt.close(fig)
        print(f"  • Saved plot: {out_path}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    api = LesliesPoolApi(
        username=USERNAME,
        password=PASSWORD,
        pool_profile_id=POOLID,
        pool_name=POOLNAME
    )
    if not api.authenticate():
        raise RuntimeError("⚠️ Leslie’s login failed")

    data = api.fetch_water_test_data()
    
    # Normalize "N/A" to 0
    for key, val in data.items():
        if isinstance(val, str) and val.strip().upper() == "N/A":
            data[key] = 0

    central_time = datetime.now(ZoneInfo("America/Chicago"))
    human_time = central_time.strftime("%B %d, %Y at %#I:%M %p")
    run_timestamp = central_time.isoformat()
    data["run_timestamp"] = run_timestamp

    last_logged = load_last_logged_test()

    print(data)
    if is_duplicate_test(data, last_logged):
        print(f"ℹ️ Already logged {data['test_date']}")
    else:
        print(f"Logging new test: {data['test_date']}")
        append_to_csv(data)
        summary = build_test_summary(data)

        post_slack_message(
            SLACK_CHANNEL,
            f"New water test logged on {human_time}:\n{summary}"
        )

        if "🚨" in summary:
            post_slack_message(
                SLACK_CHANNEL,
                "🚨 One or more readings are outside operating limits.\nFix immediately!"
            )

    print("📊 Generating 30-day plots…")
    plot_last_30_days(CSV_FILE)

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()

















