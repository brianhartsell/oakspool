import os
import csv
from datetime import datetime, timedelta

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

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

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
        "phosphates":    ["phosphates"],
        "salt":          ["salt"],
        "in_store":      ["in_store"]
    }

    TARGET_RANGES = {
        "free_chlorine": (1, 4),
        "total_chlorine": (1, 4),
        "ph": (7.2, 7.8),
        "alkalinity": (80, 120),
        "calcium": (200, 400),
        "cyanuric_acid": (30, 100),
        "iron": (0, 0.2),
        "copper": (0, 0.2),
        "phosphates": (0, 100),
        "salt": (2500, 3500)
    }

    for name, cols in plots.items():
        plt.figure(figsize=(10, 4))

        # Draw target bands for each field
        for col in cols:
            if col in TARGET_RANGES:
                low, high = TARGET_RANGES[col]
                plt.axhspan(low, high, color="green", alpha=0.1, label=f"{col} target")

        # Plot actual data
        for col in cols:
            if col in recent.columns:
                y = pd.to_numeric(recent[col], errors="coerce")
                plt.plot(recent["test_date"], y, marker="o", label=col)

        plt.xlabel("Date")
        plt.xticks(rotation=30)
        plt.ylabel(f"{name.replace('_', ' ').title()}")
        plt.legend()
        plt.grid(alpha=0.3)
        plt.tight_layout()

        out_path = os.path.join(DOCS_DIR, f"{name}.png")
        plt.savefig(out_path)
        plt.close()
        print(f"  • Saved plot: {out_path}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    # 1) Fetch & log new data
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

    # 2) Plot last 30 days
    print("📊 Generating 30-day plots…")
    plot_last_30_days(CSV_FILE)

if __name__ == "__main__":

    main()
