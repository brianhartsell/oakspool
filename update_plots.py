"""Regenerate all docs/*.png from current CSV logs.

Run after any data pull, or directly: python update_plots.py
"""
import csv
import datetime
import os

import matplotlib.pyplot as plt
import pandas as pd
import pytz

from seasons_loader import get_current_season, load

DOCS = "docs"
FLUME_CSV  = "logs/flume_usage_log.csv"
LESLIES_CSV = "logs/leslies-log.csv"
FLOW_CSV   = "logs/flow.csv"

FLOW_STD_SCALE = 10  # multiply σ for visibility — pure visual aid, not a confidence interval
GAP_THRESHOLD  = pd.Timedelta(hours=2)  # gaps wider than this break the line


def _insert_gap_breakers(df, time_col="read_datetime"):
    """Insert NaN rows where consecutive timestamps are >GAP_THRESHOLD apart.

    This breaks matplotlib's line so gaps don't get interpolated visually.
    Returns (df_with_breaks, list_of_(gap_start, gap_end) tuples).
    """
    df = df.sort_values(time_col).reset_index(drop=True)
    diffs = df[time_col].diff()
    gap_mask = diffs > GAP_THRESHOLD
    gaps = []
    nan_rows = []
    for idx in df.index[gap_mask]:
        gap_start = df.loc[idx - 1, time_col]
        gap_end = df.loc[idx, time_col]
        gaps.append((gap_start, gap_end))
        mid = gap_start + (gap_end - gap_start) / 2
        nan_row = {c: float("nan") if c != time_col else mid for c in df.columns}
        nan_rows.append(nan_row)
    if nan_rows:
        df = pd.concat([df, pd.DataFrame(nan_rows)], ignore_index=True)
        df = df.sort_values(time_col).reset_index(drop=True)
    return df, gaps


def _shade_gaps(ax, gaps):
    for start, end in gaps:
        ax.axvspan(start, end, alpha=0.15, color="lightsalmon", linewidth=0)


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


def _chem_bands(ax, key):
    """Draw green/yellow/red reference bands for a chemical parameter."""
    target = TARGET_RANGES.get(key)
    closure = CLOSURE_LIMITS.get(key)
    if not target:
        return
    INF = 1e6
    if closure:
        ax.axhspan(-INF,       closure[0], alpha=0.12, color="red",    linewidth=0)
        ax.axhspan(closure[0], target[0],  alpha=0.14, color="yellow", linewidth=0)
        ax.axhspan(target[0],  target[1],  alpha=0.18, color="green",  linewidth=0)
        ax.axhspan(target[1],  closure[1], alpha=0.14, color="yellow", linewidth=0)
        ax.axhspan(closure[1], INF,        alpha=0.12, color="red",    linewidth=0)
    else:
        ax.axhspan(target[0], target[1], alpha=0.18, color="green", linewidth=0)


def _season_range():
    """Return (start, end) dates for the plot window: current season, or most recent past season."""
    central = pytz.timezone("US/Central")
    today = datetime.datetime.now(pytz.utc).astimezone(central).date()
    current = get_current_season(today)
    if current:
        return current.open, today
    seasons = load()
    if seasons:
        last = max(seasons, key=lambda s: s.close)
        return last.open, last.close
    return None, None


def _load_leslies():
    if not os.path.exists(LESLIES_CSV):
        return pd.DataFrame()
    start, end = _season_range()
    rows = []
    with open(LESLIES_CSV, newline="") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.datetime.strptime(r["test_date"], "%m/%d/%Y").date()
            except ValueError:
                continue
            if start and (d < start or d > end):
                continue
            row = {"test_date": d}
            for key in TARGET_RANGES:
                try:
                    v = float(r.get(key) or "nan")
                    # 0 is below every target range minimum — treat as missing data
                    # (legacy N/A entries were normalized to 0 before this was fixed)
                    if v == 0 and TARGET_RANGES[key][0] > 0:
                        v = float("nan")
                    row[key] = v
                except ValueError:
                    row[key] = float("nan")
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("test_date").reset_index(drop=True)


def _ylim_for(key, col):
    """Return (y_lo, y_hi) that includes both the data range and the reference bands."""
    target = TARGET_RANGES.get(key)
    closure = CLOSURE_LIMITS.get(key)
    data_min = col.min() if not col.empty else 0
    data_max = col.max() if not col.empty else 1
    ref_lo = (closure or target or (data_min, data_max))[0]
    ref_hi = (closure or target or (data_min, data_max))[1]
    span = max(ref_hi - ref_lo, data_max - data_min, 1)
    y_lo = max(0, min(data_min, ref_lo) - span * 0.1)
    y_hi = max(data_max, ref_hi) + span * 0.1
    return y_lo, y_hi


def plot_chlorine(df, out_path):
    if df.empty:
        return
    fc = df["free_chlorine"].dropna() if "free_chlorine" in df.columns else pd.Series([], dtype=float)
    tc = df["total_chlorine"].dropna() if "total_chlorine" in df.columns else pd.Series([], dtype=float)
    combined = pd.concat([fc, tc])
    if combined.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 4))
    _chem_bands(ax, "total_chlorine")
    if not fc.empty:
        ax.plot(df["test_date"], df["free_chlorine"],
                marker="o", color="teal", linewidth=1.5, markersize=5, label="Free Chlorine")
    if not tc.empty:
        ax.plot(df["test_date"], df["total_chlorine"],
                marker="s", color="steelblue", linewidth=1.5, markersize=5,
                linestyle="--", label="Total Chlorine")
    ax.set_ylim(*_ylim_for("free_chlorine", combined))
    ax.set_xlabel("Test Date")
    ax.set_ylabel("Chlorine (ppm)")
    ax.set_title("Chlorine Levels")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  ✅ {os.path.basename(out_path)}")


def plot_chemical(df, key, out_path):
    if df.empty or key not in df.columns or df[key].dropna().empty:
        print(f"  ⚠️  {key}: no data, skipping")
        return
    label, unit = LABELS_AND_UNITS.get(key, (key.replace("_", " ").title(), ""))
    ylabel = f"{label} ({unit})" if unit else label
    col = df[key].dropna()
    fig, ax = plt.subplots(figsize=(10, 4))
    _chem_bands(ax, key)
    ax.plot(df["test_date"], df[key], marker="o", color="navy", linewidth=1.5, markersize=5)
    ax.set_ylim(*_ylim_for(key, col))
    ax.set_xlabel("Test Date")
    ax.set_ylabel(ylabel)
    ax.set_title(label)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  ✅ {os.path.basename(out_path)}")


def plot_flume_usage(out_path):
    if not os.path.exists(FLUME_CSV):
        print("  ⚠️  flume_usage_log.csv missing, skipping usage chart")
        return
    central = pytz.timezone("US/Central")
    today = datetime.datetime.now(pytz.utc).astimezone(central).date()
    cutoff = today - datetime.timedelta(days=30)
    dates, values = [], []
    with open(FLUME_CSV, newline="") as f:
        for row in csv.DictReader(f):
            d = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
            if d >= cutoff:
                dates.append(row["date"])
                values.append(float(row["ccf"]))
    if not dates:
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(dates, values, marker="o", color="teal")
    ax.set_ylabel("Usage [CCF]")
    ax.set_title("Daily Water Usage – Last 30 Days")
    ax.grid(True)
    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  ✅ {os.path.basename(out_path)}")


def plot_season_comparison(out_path):
    if not os.path.exists(FLUME_CSV):
        return
    central = pytz.timezone("US/Central")
    today = datetime.datetime.now(pytz.utc).astimezone(central).date()
    df_rows = []
    with open(FLUME_CSV, newline="") as f:
        for row in csv.DictReader(f):
            d = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
            df_rows.append({"date": d, "year": d.year, "ccf": float(row["ccf"])})
    if not df_rows:
        return
    df = pd.DataFrame(df_rows)
    current = get_current_season(today)
    records = []
    for season in load():
        year = season.year
        end = today if (current and year == current.year) else season.close
        sub = df[(df["year"] == year) & (df["date"] >= season.open) & (df["date"] <= end)].copy()
        if sub.empty:
            continue
        sub["date"] = pd.to_datetime(sub["date"])
        sub["days_since_open"] = (sub["date"] - pd.to_datetime(season.open)).dt.days
        sub = sub.sort_values("date")
        sub["rolling_avg"] = sub["ccf"].rolling(window=14, min_periods=1).mean()
        sub["label"] = str(year)
        records.append(sub[["days_since_open", "rolling_avg", "label"]])
    if not records:
        return
    combined = pd.concat(records)
    fig, ax = plt.subplots(figsize=(10, 6))
    for label, group in combined.groupby("label"):
        ax.plot(group["days_since_open"], group["rolling_avg"], label=label)
    ax.set_xlabel("Days Since Pool Open")
    ax.set_ylabel("Water Usage (CCF)")
    ax.set_title("Pool Season Comparison – 14-Day Rolling Average")
    ax.grid(True)
    ax.legend(title="Year")
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  ✅ {os.path.basename(out_path)}")


def plot_flow(days, out_path):
    if not os.path.exists(FLOW_CSV):
        print(f"  ⚠️  flow.csv missing, skipping flow_{days}d chart")
        return
    df = pd.read_csv(FLOW_CSV, parse_dates=["read_datetime"])
    df = df.sort_values("read_datetime")
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    df = df[df["read_datetime"] >= cutoff].copy()
    df["flow"] = pd.to_numeric(df["flow"], errors="coerce")
    if df.empty:
        print(f"  ⚠️  No flow data in last {days} days")
        return
    df, gaps = _insert_gap_breakers(df)
    fig, ax = plt.subplots(figsize=(10, 4))
    _shade_gaps(ax, gaps)
    if "flow_std" in df.columns:
        df["flow_std"] = pd.to_numeric(df["flow_std"], errors="coerce")
        mask = df["flow"].notna() & df["flow_std"].notna()
        if mask.any():
            ax.fill_between(
                df["read_datetime"],
                df["flow"] - df["flow_std"] * FLOW_STD_SCALE,
                df["flow"] + df["flow_std"] * FLOW_STD_SCALE,
                where=mask, alpha=0.35, color="hotpink",
                label=f"±{FLOW_STD_SCALE}σ", interpolate=False,
            )
    ax.plot(df["read_datetime"], df["flow"], color="royalblue", linewidth=1.2, label="Flow")
    ax.set_xlabel("Date")
    ax.set_ylabel("Flow Rate [gpm]")
    ax.set_title(f"Flow Rate – Last {days} Days")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.4)
    fig.autofmt_xdate(rotation=60)
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  ✅ {os.path.basename(out_path)}")


def plot_pressure(out_path):
    if not os.path.exists(FLOW_CSV):
        print("  ⚠️  flow.csv missing, skipping pressure chart")
        return
    df = pd.read_csv(FLOW_CSV, parse_dates=["read_datetime"])
    df = df.sort_values("read_datetime")
    cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
    df = df[df["read_datetime"] >= cutoff].copy()
    df["flow"] = pd.to_numeric(df["flow"], errors="coerce")
    df["combined_press"] = df["vac_press"] + df["sys_press"]
    if df.empty:
        return
    df, gaps = _insert_gap_breakers(df)
    fig, ax1 = plt.subplots(figsize=(10, 4))
    _shade_gaps(ax1, gaps)
    ax1.plot(df["read_datetime"], df["combined_press"],
             color="red", linewidth=1, label="Vac + Sys Pressure")
    ax1.scatter(df["read_datetime"], df["combined_press"], color="red", s=15)
    ax1.plot(df["read_datetime"], df["f1_press"],
             color="green", linewidth=1, label="F1 Pressure")
    ax1.scatter(df["read_datetime"], df["f1_press"], color="green", s=15)
    ax1.set_ylabel("Pressure [psi]")
    ax1.grid(True, alpha=0.4)
    ax2 = ax1.twinx()
    ax2.plot(df["read_datetime"], df["flow"],
             color="royalblue", linestyle="--", linewidth=1, label="Flow Rate")
    ax2.scatter(df["read_datetime"], df["flow"], color="royalblue", s=15, marker="x")
    ax2.set_ylabel("Flow Rate [gpm]")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    plt.title("Pressures and Flow – Last 30 Days")
    fig.autofmt_xdate(rotation=60)
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  ✅ {os.path.basename(out_path)}")


def main():
    os.makedirs(DOCS, exist_ok=True)

    print("Flume plots:")
    plot_flume_usage(os.path.join(DOCS, "flume_usage_chart.png"))
    plot_season_comparison(os.path.join(DOCS, "flume_season_comparison.png"))

    print("Chemical plots:")
    df_chem = _load_leslies()
    plot_chlorine(df_chem, os.path.join(DOCS, "chlorine.png"))
    for key in ["ph", "alkalinity", "calcium", "cyanuric_acid", "iron", "copper", "phosphates"]:
        plot_chemical(df_chem, key, os.path.join(DOCS, f"{key}.png"))

    print("Flow/pressure plots:")
    plot_flow(7,  os.path.join(DOCS, "flow_7d.png"))
    plot_flow(30, os.path.join(DOCS, "flow_30d.png"))
    plot_pressure(os.path.join(DOCS, "press.png"))

    print("✅ All plots complete.")


if __name__ == "__main__":
    main()
