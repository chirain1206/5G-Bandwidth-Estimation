# 文件名: preprocess_ucc.py
import pandas as pd
import glob
import os
import json
import numpy as np
from sklearn.model_selection import train_test_split

# ================= 配置区域 =================
DATA_ROOT = '5G-production-dataset' 
OUTPUT_DIR = 'dataset_ucc_llama3_5g_only'
# ===========================================

print(f">>> 1. Scanning CSV files in {DATA_ROOT}...")
csv_files = glob.glob(os.path.join(DATA_ROOT, '**/*.csv'), recursive=True)
print(f"Found {len(csv_files)} CSV files.")

if not csv_files:
    raise ValueError("No CSV files found! Check path.")

# 1. 读取并合并
df_list = []
for file in csv_files:
    try:
        temp_df = pd.read_csv(file)
        temp_df['Source_File'] = os.path.basename(file) 
        df_list.append(temp_df)
    except Exception as e:
        print(f"Skipping {file}: {e}")

df = pd.concat(df_list, ignore_index=True)
print(f"Total raw rows: {len(df)}")

# 这一步会把 "-", "N/A" 等脏数据全部变成 NaN，防止后面报错
numeric_cols = ['CQI', 'NRxRSRP', 'NRxRSRQ', 'RSRP', 'RSRQ', 'SNR', 'RSSI']
for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

df['NetworkMode'] = df['NetworkMode'].astype(str)
# 过滤：NetworkMode 必须包含 '5G'
len_before_5g = len(df)
df = df[df['NetworkMode'].str.contains('5G', case=False, na=False)].copy()
print(f"Filtered Non-5G data: {len_before_5g} -> {len(df)} rows")

# 2. 基础清洗 (Filter Idle & Low Speed)
# UCC: State='D' is downloading. Bitrate is kbps.
df = df[(df['State'] == 'D') & (df['DL_bitrate'] > 50)].copy()
df['Target_Mbps'] = df['DL_bitrate'] / 1000.0

# 3. 特征工程 (Lag Features)
print(">>> 2. Generating Context Features...")
df['datetime'] = pd.to_datetime(df['Timestamp'], format='%Y.%m.%d_%H.%M.%S')
df = df.sort_values(['Source_File', 'datetime'])

df['Prev_Mbps'] = df.groupby('Source_File')['Target_Mbps'].shift(1)
df['Time_Diff'] = df.groupby('Source_File')['datetime'].diff().dt.total_seconds()

# 过滤掉不连续的时间点 (间隔 > 3s)
df = df[(df['Prev_Mbps'].notnull()) & (df['Time_Diff'] <= 3.0)].copy()

# 4. 上下文感知清洗 (Cleaning)
print(">>> 3. Cleaning Outliers...")
df['RSRP_Bin'] = pd.cut(df['RSRP'], bins=range(-140, -40, 5))
grouped = df.groupby('RSRP_Bin')['Target_Mbps']
df['Bin_Mean'] = grouped.transform('mean')
df['Bin_Std']  = grouped.transform('std')

def is_valid(row):
    if pd.isna(row['Bin_Mean']) or pd.isna(row['Bin_Std']): return True
    sigma = 3.0 # 放宽一点，保留更多波动
    lower = max(row['Bin_Mean'] - sigma * row['Bin_Std'], 0.1)
    upper = row['Bin_Mean'] + sigma * row['Bin_Std']
    return lower <= row['Target_Mbps'] <= upper

df = df[df.apply(is_valid, axis=1)]
print(f"Final valid rows: {len(df)}")

# 5. 构建 Rich Prompt (包含所有 Metrics)
def row_to_json(row):
    # --- LTE Metrics ---
    lte_rsrp = f"{row['RSRP']} dBm"
    lte_rsrq = f"{row['RSRQ']} dB"
    lte_snr  = f"{row['SNR']} dB"
    lte_rssi = f"{row['RSSI']} dBm"
    
    # CQI 有时候是 NaN
    cqi_val = row['CQI']
    if pd.notna(cqi_val) and cqi_val >= 0:
        lte_cqi = str(int(cqi_val))
    else:
        lte_cqi = "Unknown"

    # --- 5G NR Metrics ---
    nr_rsrp_val = row.get('NRxRSRP', float('nan'))
    nr_rsrq_val = row.get('NRxRSRQ', float('nan'))
    
    # 判断 5G 是否存在
    if pd.isna(nr_rsrp_val) or nr_rsrp_val <= -139:
        nr_str = "Not Detected (NSA Idle or LTE Only)"
    else:
        # 这里把 NR RSRP 和 RSRQ 都放进去
        nr_str = f"RSRP {nr_rsrp_val:.1f} dBm, RSRQ {nr_rsrq_val:.1f} dB"

    # --- Context ---
    prev_bw = f"{row['Prev_Mbps']:.2f} Mbps"
    
    # --- 组合 User Input ---
    user_content = (
        f"Context: The throughput in the previous second was {prev_bw}.\n"
        f"Network State:\n"
        f"- Mode: {row['NetworkMode']}\n"
        f"- Operator: {row['Operatorname']}\n"
        f"- Cell Sector ID: {row['CellID']}\n"
        f"Signal Quality:\n"
        f"- LTE: RSRP {lte_rsrp}, RSRQ {lte_rsrq}, SNR {lte_snr}, RSSI {lte_rssi}, CQI {lte_cqi}\n"
        f"- 5G NR: {nr_str}\n"
        f"Mobility: {row['Speed']} km/h"
    )
    
    return {
        "messages": [
            {"role": "system", "content": "You are a 5G network expert. Predict the downlink throughput (in Mbps). Return only the numeric value."},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": f"{row['Target_Mbps']:.2f}"}
        ]
    }

data_list = [row_to_json(row) for _, row in df.iterrows()]

# 6. 保存
train_data, val_data = train_test_split(data_list, test_size=0.1, random_state=42)
os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(f"{OUTPUT_DIR}/train.jsonl", 'w') as f:
    for entry in train_data: f.write(json.dumps(entry) + '\n')
with open(f"{OUTPUT_DIR}/val.jsonl", 'w') as f:
    for entry in val_data: f.write(json.dumps(entry) + '\n')

print(f"\nDone! Data saved to {OUTPUT_DIR}/")
