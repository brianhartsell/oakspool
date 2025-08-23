import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# --- Config ---
INPUT_FILE = "logs/flow.csv"
FLOW_PLOT = "docs/flow.png"
PRESSURE_PLOT = "docs/press.png"
DATE_COLUMN = "read_datetime"
DAYS_BACK = 30

# --- Load and preprocess ---
df = pd.read_csv(INPUT_FILE, parse_dates=[DATE_COLUMN])
df = df.sort_values(by=DATE_COLUMN)

# Filter last 30 days
cutoff = datetime.now() - timedelta(days=DAYS_BACK)
df_recent = df[df[DATE_COLUMN] >= cutoff].copy()

# Compute combined pressure
df_recent["combined_press"] = df_recent["vac_press"] + df_recent["sys_press"]

# Ensure missing values are NaN
df_recent["flow"] = pd.to_numeric(df_recent["flow"], errors="coerce")

df_recent.set_index(DATE_COLUMN, inplace=True)

# --- Plot 1: Flow rate ---
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(df_recent.index, df_recent["flow"], label="Flow Rate", color="blue")
ax.set_xlabel("Date")
ax.set_ylabel("Flow Rate [gpm]")
ax.set_title("Flow Rate Over Last 30 Days")
ax.grid(True)

# Rotate date labels
fig.autofmt_xdate(rotation=30)

plt.tight_layout()
print("Saving flow plot with", df_recent["flow"].notna().sum(), "valid points")
plt.savefig(FLOW_PLOT)
plt.close()

# --- Plot 2: Pressures + Flow (dual axis) ---
fig, ax1 = plt.subplots(figsize=(10, 4))

# Primary Y axis: pressures
ax1.plot(df_recent.index, df_recent["combined_press"], label="Vac + Sys Pressure", color="red", linewidth=1)
ax1.scatter(df_recent.index, df_recent["combined_press"], color="red", s=20)

ax1.plot(df_recent.index, df_recent["f1_press"], label="F1 Pressure", color="green", linewidth=1)
ax1.scatter(df_recent.index, df_recent["f1_press"], color="green", s=20)

ax1.set_xlabel("Date")
ax1.set_ylabel("Pressure [psi]")
ax1.tick_params(axis='y')
ax1.grid(True)


# Secondary Y axis: flow
ax2 = ax1.twinx()
ax2.plot(df_recent.index, df_recent["flow"], label="Flow Rate", color="blue", linestyle="--", linewidth=1)
ax2.scatter(df_recent.index, df_recent["flow"], color="blue", s=20, marker='x')
ax2.set_ylabel("Flow Rate [gpm]")
ax2.tick_params(axis='y')

# Legends
lines_1, labels_1 = ax1.get_legend_handles_labels()
lines_2, labels_2 = ax2.get_legend_handles_labels()
ax1.legend(lines_1 + lines_2, labels_1 + labels_2)

plt.title("Pressures and Flow Over Last 30 Days")

# Rotate date labels
fig.autofmt_xdate(rotation=30)

plt.tight_layout()
print("Saving flow plot with", df_recent["flow"].notna().sum(), "valid points")
plt.savefig(PRESSURE_PLOT)
plt.close()
