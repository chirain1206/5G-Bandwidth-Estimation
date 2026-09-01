# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import glob
import os
import re

# ================= Configuration =================
CSV_DIR = '.'
OUTPUT_FILENAME = 'full_performance_comparison.png'

# Set to None to plot everything (The Whole Picture)
ZOOM_RANGE = None 
#ZOOM_RANGE = (0, 1000) # Optional: Use this if you want a specific window

BASE_PATTERN = "eval_application_throughput_full_3_scellsIn_*.csv"
EXCEPTION_FILE = "eval_application_throughput_full_3_qwen.csv"

# ================= Style Definitions =================
STYLES = {
    'Ground Truth':   {'color': 'black',   'ls': '-',  'lw': 1.5, 'label': 'Ground Truth', 'marker': None}, # No marker for GT to keep it clean
    'qwen':           {'color': '#d62728', 'ls': '-',  'lw': 1.2, 'label': 'Qwen (Proposed)', 'marker': '*', 'ms': 6},
    'qwen_no_scells': {'color': '#ff7f0e', 'ls': '--', 'lw': 1.2, 'label': 'Qwen (No SCells)', 'marker': 'x', 'ms': 5},
    'xgboost':        {'color': '#1f77b4', 'ls': '-.', 'lw': 1.2, 'label': 'XGBoost', 'marker': '^', 'ms': 5},
    'lstm':           {'color': '#2ca02c', 'ls': ':',  'lw': 1.2, 'label': 'LSTM', 'marker': 's', 'ms': 5},
    'ma':             {'color': 'gray',    'ls': '--', 'lw': 1.0, 'label': 'MA', 'marker': 'v', 'ms': 5},
    'qwen_residual':             {'color': 'gray',    'ls': '--', 'lw': 1.0, 'label': 'qwen_residual', 'marker': 'v', 'ms': 5},
    'qwen_residual_cot':           {'color': '#2ca02c', 'ls': ':',  'lw': 1.2, 'label': 'qwen_residual_cot', 'marker': 's', 'ms': 5},
    'hm':             {'color': 'brown',   'ls': ':',  'lw': 1.0, 'label': 'HM', 'marker': 'D', 'ms': 5}
}

def get_model_key(filename):
    if filename == EXCEPTION_FILE:
        return 'qwen_no_scells'
    match = re.search(r"scellsIn_(.*).csv", filename)
    if match:
        return match.group(1)
    return 'unknown'

def main():
    # 1. Collect Files
    files = glob.glob(os.path.join(CSV_DIR, BASE_PATTERN))
    if os.path.exists(os.path.join(CSV_DIR, EXCEPTION_FILE)):
        files.append(os.path.join(CSV_DIR, EXCEPTION_FILE))
    
    if not files:
        print("Error: No CSV files found.")
        return

    # 2. Load Data
    data_store = {}
    ground_truth = None
    
    print(f"Loading {len(files)} files...")
    
    for filepath in files:
        filename = os.path.basename(filepath)
        key = get_model_key(filename)
        try:
            df = pd.read_csv(filepath)
            
            # Load GT once
            if ground_truth is None:
                ground_truth = df['Ground_Truth_Mbps'].values
            
            # Store prediction
            data_store[key] = df['Predicted_Mbps'].values
            
        except Exception as e:
            print(f"Error reading {filename}: {e}")

    # 3. Handle Range (Full or Zoom)
    if ZOOM_RANGE:
        start, end = ZOOM_RANGE
        start = max(0, start)
        end = min(len(ground_truth), end)
        x_axis = np.arange(start, end)
        ground_truth = ground_truth[start:end]
        for k in data_store:
            data_store[k] = data_store[k][start:end]
        print(f"Plotting range: {start} to {end}")
    else:
        x_axis = np.arange(len(ground_truth))
        print(f"Plotting full range: {len(ground_truth)} samples")

    # 4. Calculate Dynamic Markevery
    # Rule: Show approx 40 markers regardless of total length
    total_points = len(ground_truth)
    dynamic_markevery = max(1, total_points // 40)
    print(f"Dynamic markevery set to: {dynamic_markevery} (to avoid clutter)")

    # 5. Plotting
    plt.figure(figsize=(16, 9)) # Wide figure for full view
    
    # Plot GT
    s_gt = STYLES['Ground Truth']
    plt.plot(x_axis, ground_truth, label=s_gt['label'], 
             color=s_gt['color'], ls=s_gt['ls'], lw=s_gt['lw'], alpha=0.6)
    
    # Define Order
    #model_order = ['hm', 'ma', 'lstm', 'xgboost', 'qwen_no_scells', 'qwen']
    model_order = ['hm', 'xgboost', 'qwen', 'qwen_residual']
    
    for key in model_order:
        if key in data_store:
            pred = data_store[key]
            s = STYLES.get(key, {'color':'k', 'ls':'-'})
            
            # === 新增：计算多个评估指标 ===
            # 1. MAPE (排除除以0的情况)
            mask = ground_truth > 1.0
            if np.sum(mask) > 0:
                mape = np.mean(np.abs((ground_truth[mask] - pred[mask]) / ground_truth[mask])) * 100
            else:
                mape = np.nan
            
            # 2. MAE (Mean Absolute Error)
            mae = np.mean(np.abs(ground_truth - pred))
            
            # 3. RMSE (Root Mean Squared Error)
            rmse = np.sqrt(np.mean((ground_truth - pred)**2))
            
            # 4. R^2 (Coefficient of Determination)
            ss_res = np.sum((ground_truth - pred)**2)
            ss_tot = np.sum((ground_truth - np.mean(ground_truth))**2)
            if ss_tot != 0:
                r2 = 1 - (ss_res / ss_tot)
            else:
                r2 = np.nan # 方差为0的情况

            # 构建详细的 Label 字符串
            # 格式：Name (MAPE=...%, MAE=..., RMSE=..., R2=...)
            metrics_list = []
            if not np.isnan(mape): metrics_list.append(f"MAPE={mape:.1f}%")
            metrics_list.append(f"MAE={mae:.2f}")
            metrics_list.append(f"RMSE={rmse:.2f}")
            if not np.isnan(r2): metrics_list.append(f"R2={r2:.3f}")
            
            metrics_str = ", ".join(metrics_list)
            label_str = f"{s['label']} ({metrics_str})"
            
            plt.plot(x_axis, pred, label=label_str,
                     color=s['color'], ls=s['ls'], lw=s['lw'],
                     marker=s.get('marker'), ms=s.get('ms', 5),
                     markevery=dynamic_markevery,
                     alpha=0.8)

    plt.xlabel('Time Index', fontsize=14, fontweight='bold')
    plt.ylabel('Throughput (Mbps)', fontsize=14, fontweight='bold')
    #plt.title('Overall Throughput Prediction Performance', fontsize=16)
    plt.grid(True, linestyle='--', alpha=0.5)
    
    # Legend outside or top
    #plt.legend(bbox_to_anchor=(0.5, 1.1), loc='upper center', ncol=3, frameon=False, fontsize=12)
    plt.legend(bbox_to_anchor=(0.5, 1.15), loc='upper center', ncol=2, frameon=True, fontsize=10)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_FILENAME, dpi=300)
    print(f"Full plot saved to {OUTPUT_FILENAME}")

if __name__ == "__main__":
    main()