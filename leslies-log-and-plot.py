import os
import csv
from datetime import datetime, timedelta
import requests

import pandas as pd
import matplotlib.pyplot as plt

from api import LesliesPoolApi

# ─── CONFIG ───────────────────────────────────────────────────────────────────

LOG_DIR    = "logs"
CSV_FILE   = os.path.join(LOG_DIR, "leslies-log.csv")
DOCS_DIR   = "docs"

USERNAME = os.getenv("LESLIES_USERNAME")
PASSWORD = os.getenv("LESLIES_PASSWORD")
POOLID = os.getenv("LESLIES_POOLID")
POOLNAME = os.getenv("LESLIES_POOLNAME")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

FIELDNAMES = [
    "test_date", "free_chlorine", "total_chlorine", "ph", "alkalinity",
    "calcium", "cyanuric_acid", "iron", "copper", "phosphates", "salt", "in_store"
]

TARGET_RANGES = {
    "free_chlorine": (1, 4),
    "total_chlorine": (1, 4),
    "ph": (7.2, 7.8),
    "alkalinity": (80, 120),
    "calcium": (200, 400),
    "cyanuric_acid": (30, 50),
    "iron": (0, 0.3),
    "copper": (0, 0.3),
    "phosphates": (0, 100),
    "salt": (2500, 3500)
}

CLOSURE_LIMITS = {
    "total_chlorine": (0.5, 5),
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
    "in_store": ("In-Store Treatment", ""),
}

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def format_label(key: str) -> str:
    label, unit = LABELS_AND_UNITS.get(key, (key.replace('_', ' ').title(), ''))
    return f"{label} ({unit})" if unit else label

def format_value(key: str, val: float | str) -> str:
    _, unit = LABELS_AND_UNITS.get(key, ('', ''))
    return f"{val} {unit}" if unit else str(val)

def already_logged(test_date: str) -> bool:
    if not os.path.exists(CSV_FILE):
        return False
    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)
        return any(row["test_date"] == test_date for row in reader)

def append_to_csv(data: dict):
    write_header = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(data)
    print(f"✅ Logged new test for {data['test_date']}")

def plot_last_30_days(csv_path: str):
    df = pd.read_csv(csv_path, parse_dates=["test_date"])
    df["test_date"] = pd.to_datetime(df["test_date"], format="%m/%d/%Y", errors="coerce")
    df = df.sort_values("test_date")
    cutoff = datetime.now() - timedelta(days=30)
    recent = df[df["test_date"] >= cutoff]

    plots = {
        "chlorine":      ["free_chlorine", "total_chlorine"],
        "ph":            ["ph"],
        "alkalinity":    ["alkalinity"],
        "calcium":       ["calcium"],
        "cyanuric_acid": ["cyanuric_acid"],
        "iron":          ["iron"],
        "copper":        ["copper"],
        "phosphates":    ["phosphates"]
    }

    for name, cols in plots.items():
        plt.figure(figsize=(10, 4))

        for col in cols:
            if col in TARGET_RANGES:
                low, high = TARGET_RANGES[col]
                plt.axhspan(low, high, color="green", alpha=0.1, label=f"{format_label(col)} recommended")

                if col in CLOSURE_LIMITS:
                    c_low, c_high = CLOSURE_LIMITS[col]
                    if c_low < low:
                        plt.axhspan(c_low, low, color="yellow", alpha=0.1, label=f"{format_label(col)} caution (low)")
                    if c_high > high:
                        plt.axhspan(high, c_high, color="yellow", alpha=0.1, label=f"{format_label(col)} caution (high)")
                    plt.axhspan(0, c_low, color="red", alpha=0.05, label=f"{format_label(col)} closure (low)")
                    plt.axhspan(c_high, recent[col].max(), color="red", alpha=0.05, label=f"{format_label(col)} closure (high)")

        for col in cols:
            if col in recent.columns:
                y = pd.to_numeric(recent[col], errors="coerce")
                plt.plot(recent["test_date"], y, marker="o", label=format_label(col))

        if col in CLOSURE_LIMITS:
            c_low, c_high = CLOSURE_LIMITS[col]
            mask = (y < c_low) | (y > c_high)
            out_of_bounds = y[mask]
        
            if not out_of_bounds.empty:
                # Highlight closure points
                plt.scatter(recent["test_date"][mask], y[mask], color="red", edgecolor="black", zorder=5)
        
                # Add caution and closure zones
                if c_low < low:
                    plt.axhspan(c_low, low, color="yellow", alpha=0.1, label=f"{format_label(col)} caution (low)")
                if c_high > high:
                    plt.axhspan(high, c_high, color="yellow", alpha=0.1, label=f"{format_label(col)} caution (high)")
                plt.axhspan(0, c_low, color="red", alpha=0.05, label=f"{format_label(col)} closure (low)")
                plt.axhspan(c_high, y.max(), color="red", alpha=0.05, label=f"{format_label(col)} closure (high)")
        
                plt.xlabel("Date")
                plt.xticks(rotation=30)
                plt.ylabel(format_label(name))
                if name == "ph":
                    handles, labels = plt.gca().get_legend_handles_labels()
                    data_labels = [lbl for lbl in labels if not any(zone in lbl.lower() for zone in ["recommended", "caution", "closure"])]
                    data_handles = [h for h, lbl in zip(handles, labels) if lbl in data_labels]
                    if data_handles:
                        plt.legend(data_handles, data_labels)

                plt.grid(alpha=0.3)
                plt.tight_layout()

                # Set Y-axis limits with buffer
                y_all = pd.concat([pd.to_numeric(recent[c], errors="coerce") for c in cols])
                y_min, y_max = y_all.min(), y_all.max()
                buffer = (y_max - y_min) * 0.1 if y_max > y_min else 1
                plt.ylim(y_min - buffer, y_max + buffer)
        
                out_path = os.path.join(DOCS_DIR, f"{name}.png")
                plt.savefig(out_path)
                plt.close()
                print(f"  • Saved plot: {out_path}")

def build_test_summary(data):
    keys = ["ph", "total_chlorine", "free_chlorine", "alkalinity", "cyanuric_acid"]
    lines = []

    for key in keys:
        val = data.get(key)
        try:
            val_float = float(val)
            low, high = TARGET_RANGES.get(key, (None, None))
            c_low, c_high = CLOSURE_LIMITS.get(key, (None, None))

            if c_low is not None and (val_float < c_low or val_float > c_high):
                emoji = "🚨"
            elif low is not None and low <= val_float <= high:
                emoji = "✅"
            else:
                emoji = "❗️"

            label = format_label(key)
            value_str = format_value(key, val)
            lines.append(f"{emoji} {label}: {value_str}")
        except (TypeError, ValueError):
            label = format_label(key)
            lines.append(f"❓ {label}: {val}")

    return "\n".join(lines)

def post_slack_message(channel, text):
    if not SLACK_TOKEN or not channel:
        print("ℹ️ Slack config missing, skipping post.")
        return

    headers = {
        "Authorization": f"Bearer {SLACK_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": channel,
        "text": text
    }

    r = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
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
        raise RuntimeError("⚠️ Leslie’s login failed")

    data = api.fetch_water_test_data()
    if already_logged(data["test_date"]):
        print(f"ℹ️  Already logged {data['test_date']}")
    else:
        append_to_csv(data)
        summary = build_test_summary(data)

        slack_text = f"New water test logged on {data['test_date']}:\n{summary}"
        post_slack_message(SLACK_CHANNEL, slack_text)

        if "🚨" in summary:
           
