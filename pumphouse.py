import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# --- Config ---
INPUT_FILE = "data/flow.csv"
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

# --- Plot 1: Flow rate ---
plt.figure(figsize=(10, 4))
plt.plot(df_recent[DATE_COLUMN], df_recent["flow"], label="Flow Rate", color="blue")
plt.xlabel("Date")
plt.ylabel("Flow Rate")
plt.title("Flow Rate Over Last 30 Days")
plt.grid(True)
plt.tight_layout()
plt.savefig(FLOW_PLOT)
plt.close()

# --- Plot 2: Pressures + Flow (dual axis) ---
fig, ax1 = plt.subplots(figsize=(10, 4))

# Primary Y axis: pressures
ax1.plot(df_recent[DATE_COLUMN], df_recent["combined_press"], label="Vac + Sys Pressure", color="red")
ax1.plot(df_recent[DATE_COLUMN], df_recent["f1_press"], label="F1 Pressure", color="green")
ax1.set_xlabel("Date")
ax1.set_ylabel("Pressure")
ax1.tick_params(axis='y')
ax1.grid(True)

# Secondary Y axis: flow
ax2 = ax1.twinx()
ax2.plot(df_recent[DATE_COLUMN], df_recent["flow"], label="Flow Rate", color="blue", linestyle="--")
ax2.set_ylabel("Flow Rate")
ax2.tick_params(axis='y')

# Legends
lines_1, labels_1 = ax1.get_legend_handles_labels()
lines_2, labels_2 = ax2.get_legend_handles_labels()
ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper left")

plt.title("Pressures and Flow Over Last 30 Days")
plt.tight_layout()
plt.savefig(PRESSURE_PLOT)
plt.close()
