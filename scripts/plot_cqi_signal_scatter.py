import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from mpl_toolkits.mplot3d import Axes3D

# ================= Configuration =================
INPUT_FILE = 'coalesced_bandwidth_traces.csv'
RSRP_COL = 'LTE_PCell_RSRP_NSG'
RSRQ_COL = 'LTE_PCell_RSRQ_NSG'
CQI_COL  = 'LTE_PCell_CQI_NSG'

# Binning Config (Adjust these if boxes are too small)
# Larger step = Fewer boxes = Bigger text space
RSRP_STEP = 2  # Every 2 dBm
RSRQ_STEP = 1  # Every 1 dB
# ===============================================

print(f"Loading data from {INPUT_FILE}...")
try:
    df = pd.read_csv(INPUT_FILE)
except FileNotFoundError:
    print(f"Error: {INPUT_FILE} not found.")
    exit()

# 1. Data Cleaning
print("Cleaning data...")
cols = [RSRP_COL, RSRQ_COL, CQI_COL]

for c in cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    else:
        print(f"Error: Column {c} not found in CSV.")
        exit()

df_clean = df.dropna(subset=cols)

# Filter for typical LTE ranges
df_clean = df_clean[
    (df_clean[RSRP_COL] > -140) & (df_clean[RSRP_COL] < -40) &
    (df_clean[RSRQ_COL] > -30) & (df_clean[RSRQ_COL] <= 0) &
    (df_clean[CQI_COL] >= 0) & (df_clean[CQI_COL] <= 15)
]

print(f"Valid rows for plotting: {len(df_clean)}")

# ==========================================
# Plot 1: 3D Scatter Plot (Optimized View)
# ==========================================
print("Generating 3D Scatter Plot...")
fig = plt.figure(figsize=(12, 10))
ax = fig.add_subplot(111, projection='3d')

# Scatter plot
scatter = ax.scatter(
    df_clean[RSRP_COL], 
    df_clean[RSRQ_COL], 
    df_clean[CQI_COL],
    c=df_clean[CQI_COL], 
    cmap='viridis', 
    s=20, 
    alpha=0.6
)

# Force Limits: Min -> Max
# This ensures the axis starts low and increases outwards
ax.set_xlim(df_clean[RSRP_COL].min(), df_clean[RSRP_COL].max())
ax.set_ylim(df_clean[RSRQ_COL].min(), df_clean[RSRQ_COL].max())
ax.set_zlim(0, 15)

ax.set_xlabel('RSRP (Signal Strength) [dBm]')
ax.set_ylabel('RSRQ (Signal Quality) [dB]')
ax.set_zlabel('CQI (Channel Quality) [0-15]')
ax.set_title('3D Relationship: Higher RSRP + Higher RSRQ = Higher CQI')

# [FIX] Rotate view to make axes look intuitive
# elev=20: Look slightly from above
# azim=-45: Standard corner view (X increases right, Y increases left/depth)
ax.view_init(elev=20, azim=-45)

cbar = plt.colorbar(scatter, ax=ax, pad=0.1)
cbar.set_label('CQI Value')

plt.savefig('3d_signal_analysis.png', dpi=300)
print("Saved: 3d_signal_analysis.png")

# ==========================================
# Plot 2: 2D Heatmap (Fixed Text Clipping)
# ==========================================
print("Generating 2D Heatmap...")

# 1. Binning
df_clean['RSRP_Bin'] = (df_clean[RSRP_COL] // RSRP_STEP * RSRP_STEP).astype(int)
df_clean['RSRQ_Bin'] = (df_clean[RSRQ_COL] // RSRQ_STEP * RSRQ_STEP).astype(int)

# 2. Pivot Table
# Sort index explicitly to ensure order
heatmap_data = df_clean.pivot_table(
    index='RSRQ_Bin', 
    columns='RSRP_Bin', 
    values=CQI_COL, 
    aggfunc='mean'
).sort_index(ascending=True).sort_index(axis=1, ascending=True)

# 3. Draw Heatmap
# [FIX] Massive Figure Size to allow text space
plt.figure(figsize=(18, 12)) 

ax = sns.heatmap(
    heatmap_data, 
    cmap='magma', 
    annot=True,   
    fmt=".1f", 
    # [FIX] Reduce font size to prevent overflow
    annot_kws={"size": 8},
    cbar_kws={'label': 'Average CQI (0-15)'},
    linewidths=.5 # Add grid lines for clarity
)

# [FIX] Invert Y-Axis
# By default, pivot table sorts -20 (top) to 0 (bottom).
# We invert so -20 is at Bottom, 0 is at Top.
ax.invert_yaxis()

plt.title('Heatmap: RSRP vs RSRQ vs CQI')
plt.xlabel('RSRP (Signal Strength) [dBm] -> Better')
plt.ylabel('RSRQ (Interference) [dB] -> Better')

plt.tight_layout()
plt.savefig('heatmap_signal_cqi.png', dpi=300)
print("Saved: heatmap_signal_cqi.png")

print("Done.")