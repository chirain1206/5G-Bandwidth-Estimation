import pandas as pd
import numpy as np

# Load dataset
df = pd.read_csv('coalesced_bandwidth_traces.csv')

# --- 1. ENGLISH ANNOTATIONS: Band-to-Capacity Mapping ---
# 41: High (TDD 100MHz), 66/25/2/4: Mid (FDD 20MHz), others: Low (Coverage)
capacity_map = {
    41: 'High-Capacity',
    66: 'Mid-Capacity', 25: 'Mid-Capacity', 2: 'Mid-Capacity', 4: 'Mid-Capacity',
    71: 'Low-Capacity', 12: 'Low-Capacity', 14: 'Low-Capacity', 29: 'Low-Capacity', 30: 'Low-Capacity'
}

def get_capacity_score(band):
    # Higher score = More potential bandwidth
    mapping = {41: 10, 66: 5, 25: 5, 2: 5, 4: 5, 71: 2, 12: 1, 14: 1, 29: 1, 30: 1}
    return mapping.get(band, 0)

# --- 2. CROSS-SCELL AGGREGATION ---
# Check all 4 SCell slots for their combined 'strength'
scell_bands = [f'SCell{i}_BAND_NSG' for i in range(1, 5)]
scell_rsrps = [f'SCell{i}_RSRP_NSG' for i in range(1, 5)]

# Total Capacity Score: Sum of capacity weights of all active SCells
df['Total_SCell_Cap_Score'] = df[scell_bands].apply(lambda row: sum([get_capacity_score(b) for b in row if pd.notna(b)]), axis=1)

# Average SCell Signal (Handling your 'value 8' by looking at changes)
df['Avg_SCell_Signal'] = df[scell_rsrps].mean(axis=1)

# --- 3. SCENARIO EXTRACTION: "The Decoupled SCell Jump" ---
# PCell is stable (RSRP change < 2 units)
df['pcell_stable'] = df['NR_PCell_RSRP_NSG'].diff().abs() < 2

# SCell pool is volatile (Signal changes > 30% OR Capacity score changes)
# We use percentage change for signal because '8' is a small mapped value
df['scell_signal_volatile'] = df['Avg_SCell_Signal'].pct_change().abs() > 0.01
df['scell_cap_changed'] = df['Total_SCell_Cap_Score'].diff() != 0

# Throughput actually moved (> 50Mbps)
df['throughput_jump'] = df['APP_Throughput_DL_Total'].diff().abs() > 50
df['actual_diff'] = df['APP_Throughput_DL_Total'].diff().abs()

# The Golden Filter
critical_mask = df['pcell_stable'] & (df['scell_signal_volatile'] | df['scell_cap_changed']) & df['throughput_jump']
critical_events = df[critical_mask].copy()

df['actual_diff'] = df['APP_Throughput_DL_Total'].diff().abs()

critical_events = df[critical_mask].copy()

if len(critical_events) > 0:
    avg_jump_mbps = critical_events['actual_diff'].mean()
    print(f"--- 5G SCell Feature Validation (Corrected) ---")
    print(f"Total Rows: {len(df)}")
    print(f"Critical Events: {len(critical_events)}")
    print(f"Average Speed Jump during these events: {avg_jump_mbps:.2f} Mbps")

    best_case = critical_events.loc[critical_events['actual_diff'].idxmax()]
    print("\n--- Best Candidate for your Research Figure ---")
    print(f"Timestamp: {best_case['Timestamp']}")
    print(f"Speed Jump: {best_case['actual_diff']:.2f} Mbps")
    print(f"PCell: Band {best_case['NR_PCell_Band_NSG']} (Stable)")