# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import glob
import os
import re

# ================= Configuration =================
CSV_DIR = '.'
OUTPUT_DIR = '.'

# File patterns
BASE_PATTERN = "eval_application_throughput_full_3_scellsIn_*.csv"
# Reference file must contain the 'Input_Prompt_Snippet' (usually the Qwen file)
REF_FILE_PATTERN = "eval_application_throughput_full_3_scellsIn_qwen.csv"
EXCEPTION_FILE = "eval_application_throughput_full_3_qwen.csv"

# ================= Style Definitions =================
STYLES = {
    'Ground Truth':   {'color': 'black',   'ls': '-',  'lw': 2.0, 'label': 'Ground Truth', 'marker': 'o', 'ms': 4},
    'qwen':           {'color': '#d62728', 'ls': '-',  'lw': 1.5, 'label': 'Qwen (Proposed)', 'marker': '*', 'ms': 6},
    'qwen_no_scells': {'color': '#ff7f0e', 'ls': '--', 'lw': 1.5, 'label': 'Qwen (No SCells)', 'marker': 'x', 'ms': 5},
    'xgboost':        {'color': '#1f77b4', 'ls': '-.', 'lw': 1.5, 'label': 'XGBoost', 'marker': '^', 'ms': 5},
    'lstm':           {'color': '#2ca02c', 'ls': ':',  'lw': 1.5, 'label': 'LSTM', 'marker': 's', 'ms': 5},
    'ma':             {'color': 'gray',    'ls': '--', 'lw': 1.5, 'label': 'MA', 'marker': 'v', 'ms': 5},
    'hm':             {'color': 'brown',   'ls': ':',  'lw': 1.5, 'label': 'HM', 'marker': 'D', 'ms': 5}
}

def get_model_key(filename):
    if filename == EXCEPTION_FILE:
        return 'qwen_no_scells'
    match = re.search(r"scellsIn_(.*).csv", filename)
    if match:
        return match.group(1)
    return 'unknown'

# ================= Helper Parsing Functions =================

def parse_last_throughput(text):
    """Extracts 'Last Second Throughput' (T-1) from the prompt."""
    if not isinstance(text, str): return None
    match = re.search(r"Last Second Throughput:\s*([\d\.]+)\s*Mbps", text)
    if match:
        return float(match.group(1))
    return None

def count_active_scells_in_block(text_block):
    """Counts the number of active SCells (with valid RSRP) in a text block."""
    if not text_block: return 0
    return len(re.findall(r"RSRP:?\s*-?\d", text_block))

def extract_scell_counts(text):
    """
    Parses the prompt to get SCell counts for T-1 and Current time.
    Returns: (count_t1, count_curr)
    """
    if not isinstance(text, str) or "Current Network State" not in text:
        return 0, 0
    parts = text.split("Current Network State")
    
    # Extract T-1 SCell block
    t1_match = re.search(r"T-1.*?(\[Secondary Cells\]:.*?)(?=\n(?:T-\d)|$)", parts[0], re.DOTALL)
    cnt_t1 = count_active_scells_in_block(t1_match.group(1)) if t1_match else 0
    
    # Extract Current SCell block
    curr_match = re.search(r"(\[Secondary Cells\]:.*?)(?=\n|$)", parts[1], re.DOTALL)
    cnt_curr = count_active_scells_in_block(curr_match.group(1)) if curr_match else 0
    
    return cnt_t1, cnt_curr

def extract_history_rsrp(text):
    """
    Extracts Primary Cell RSRP for T-3, T-2, and T-1.
    Returns: [rsrp_t3, rsrp_t2, rsrp_t1]
    """
    if not isinstance(text, str): return [None, None, None]
    
    rsrps = {}
    for t in ['T-3', 'T-2', 'T-1']:
        pattern = fr"{t}.*?Primary Cell.*?SS-RSRP\s*([-\d\.]+)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            rsrps[t] = float(match.group(1))
        else:
            rsrps[t] = None
            
    return [rsrps.get('T-3'), rsrps.get('T-2'), rsrps.get('T-1')]
    
def get_network_state(text, key='T-1'):
    if not isinstance(text, str) or "Current Network State" not in text:
        return None, None
    
    parts = text.split("Current Network State")
    hist_block = parts[0]
    curr_block = parts[1]
    
    val_t1 = None
    val_curr = None
    
    if key == 'Band':
        t1_line_match = re.search(r"T-1.*?5G Primary Cell:\s*Band\s*([A-Za-z0-9]+)", hist_block, re.DOTALL)
        if t1_line_match: val_t1 = t1_line_match.group(1)
        
        curr_match = re.search(r"5G Primary Cell:\s*Band\s*([A-Za-z0-9]+)", curr_block)
        if curr_match: val_curr = curr_match.group(1)
        
    elif key == 'CQI':
        t1_line_match = re.search(r"T-1.*?CQI\s*(\d+)", hist_block, re.DOTALL)
        if t1_line_match: val_t1 = float(t1_line_match.group(1))
        
        curr_match = re.search(r"CQI\s*(\d+)", curr_block)
        if curr_match: val_curr = float(curr_match.group(1))

    elif key == 'Mode':
        t1_line_match = re.search(r"T-1.*?5G Mode:\s*([A-Z]+)", hist_block, re.DOTALL)
        if t1_line_match: val_t1 = t1_line_match.group(1)
        
        curr_match = re.search(r"5G Mode:\s*([A-Z]+)", curr_block)
        if curr_match: val_curr = curr_match.group(1)

    return val_t1, val_curr

# ================= Event Identification Functions =================

def identify_high_volatility(df):
    """
    Event 1: High Volatility
    Definition: Absolute difference between Ground Truth and T-1 Throughput > 50 Mbps.
    """
    indices = []
    for _, row in df.iterrows():
        gt = row.get('Ground_Truth_Mbps', 0)
        last_tpt = parse_last_throughput(row.get('Input_Prompt_Snippet', ''))
        
        is_event = False
        if last_tpt is not None:
            if abs(gt - last_tpt) > 100:
            #if last_tpt - gt > 100:
                is_event = True
        indices.append(is_event)
    return np.array(indices)

def identify_scell_change(df):
    """
    Event 2: SCell Change
    Definition: The number of active SCells changed from T-1 to Current time.
    """
    indices = []
    for _, row in df.iterrows():
        cnt_t1, cnt_curr = extract_scell_counts(row.get('Input_Prompt_Snippet', ''))
        indices.append(cnt_t1 != cnt_curr)
    return np.array(indices)

def identify_handover_prep(df):
    """
    Event 3: Handover Preparation (Signal Drop)
    Definition:
    1. Primary Cell RSRP is strictly decreasing (T-3 > T-2 > T-1).
    2. Actual throughput is dropping (GT < T-1).
    """
    indices = []
    for _, row in df.iterrows():
        text = row.get('Input_Prompt_Snippet', '')
        gt = row.get('Ground_Truth_Mbps', 0)
        t1_tpt = parse_last_throughput(text)
        
        r3, r2, r1 = extract_history_rsrp(text)
        
        is_event = False
        if None not in [r3, r2, r1, t1_tpt]:
            signal_dropping = (r3 > r2) and (r2 > r1)
            speed_dropping = gt < t1_tpt
            
            if signal_dropping and speed_dropping:
                is_event = True
                
        indices.append(is_event)
    return np.array(indices)

def identify_recovery_event(df):
    """
    Event 4: Look-ahead Recovery
    Definition:
    1. Throughput was low at T-1 (< 100 Mbps).
    2. SCell was ADDED (Current SCells > T-1 SCells).
    3. Throughput actually recovered (Ground Truth > 150 Mbps).
    
    Why this matters: Baseline models (MA/LSTM) usually predict low because T-1 is low.
    Proposed model should predict high because it sees the SCell addition.
    """
    indices = []
    for _, row in df.iterrows():
        text = row.get('Input_Prompt_Snippet', '')
        gt = row.get('Ground_Truth_Mbps', 0)
        
        t1_tpt = parse_last_throughput(text)
        cnt_t1, cnt_curr = extract_scell_counts(text)
        
        is_event = False
        if t1_tpt is not None:
            #low_history = t1_tpt < 100
            scell_added = cnt_curr > cnt_t1
            #actual_recovery = gt > 150
            
            #if low_history and scell_added and actual_recovery:
            if (t1_tpt - gt > 100) and scell_added:
                is_event = True
                
        indices.append(is_event)
    return np.array(indices)
    
def identify_band_change(df):
    """
    Event: Primary Band Changed (e.g., Band 41 -> Band 5)
    Impact: Massive change in capacity.
    """
    indices = []
    for _, row in df.iterrows():
        t1, curr = get_network_state(row.get('Input_Prompt_Snippet', ''), 'Band')
        # 必须两者都存在且不相等
        is_event = (t1 is not None) and (curr is not None) and (t1 != curr)
        indices.append(is_event)
    return np.array(indices)

def identify_cqi_drop(df):
    """
    Event: CQI Significant Drop (e.g., 15 -> 5)
    Impact: Modulation drops, speed drops, even if RSRP is stable.
    Threshold: Drop > 3
    """
    indices = []
    for _, row in df.iterrows():
        t1, curr = get_network_state(row.get('Input_Prompt_Snippet', ''), 'CQI')
        is_event = False
        if t1 is not None and curr is not None:
            # CQI 掉了超过 3 (例如从好 12 变成差 8)
            if (t1 - curr) > 3:
                is_event = True
        indices.append(is_event)
    return np.array(indices)

# ================= Plotting Function =================

def plot_event_series(event_name, indices, data_dict, output_filename):
    if sum(indices) == 0:
        print(f"  [Skip] No events for '{event_name}'")
        return

    event_locs = np.where(indices)[0]
    #if len(event_locs) > 50:
    #    event_locs = event_locs[:50] # Limit points
    event_locs = event_locs[100:]
    
    x_axis = range(1, len(event_locs) + 1)
    
    # Get GT for MAPE calculation
    if 'Ground Truth' not in data_dict: return
    y_gt = data_dict['Ground Truth'][event_locs]

    plt.figure(figsize=(14, 7))

    # Plot Ground Truth
    s = STYLES['Ground Truth']
    plt.plot(x_axis, y_gt, label=s['label'], color=s['color'], 
             ls=s['ls'], lw=s['lw'], marker=s['marker'], alpha=0.8)

    # Plot Models with MAPE in Legend
    model_order = ['hm', 'ma', 'lstm', 'xgboost', 'qwen_no_scells', 'qwen']
    
    for key in model_order:
        data_key = key if key in data_dict else None
        if key == 'qwen' and 'qwen' in data_dict: data_key = 'qwen'
        
        if data_key and data_key in data_dict:
            y_pred = data_dict[data_key][event_locs]
            s = STYLES.get(key, {'color':'k', 'ls':'-', 'label':key})
            
            mask = y_gt > 1.0
            if np.sum(mask) > 0:
                local_ape = np.abs(y_gt[mask] - y_pred[mask]) / y_gt[mask]
                local_mape = np.mean(local_ape) * 100
                label_str = f"{s['label']} (MAPE={local_mape:.1f}%)"
            else:
                label_str = s['label']
            # ---------------------------

            plt.plot(x_axis, y_pred, label=label_str, color=s['color'], 
                     ls=s['ls'], lw=s['lw'], marker=s.get('marker'), 
                     ms=s.get('ms', 5), alpha=0.7)

    plt.xlabel(f'{event_name} Event', fontsize=14, fontweight='bold')
    plt.ylabel('Throughput (Mbps)', fontsize=14, fontweight='bold')
    plt.title(f'Performance Analysis: {event_name}', fontsize=16)
    plt.grid(True, linestyle='--', alpha=0.5)
    
    # Legend settings
    plt.legend(bbox_to_anchor=(0.5, 1.15), loc='upper center', ncol=3, frameon=False, fontsize=11)
    
    plt.tight_layout()
    save_path = os.path.join(OUTPUT_DIR, output_filename)
    plt.savefig(save_path, dpi=300)
    print(f"  [Success] Saved to {save_path}")

# ================= Main Execution =================

def main():
    # 1. Load Reference File
    ref_files = glob.glob(os.path.join(CSV_DIR, REF_FILE_PATTERN))
    if not ref_files:
        print("Error: Reference file not found.")
        return
    df_ref = pd.read_csv(ref_files[0])
    print(f"Loaded reference: {ref_files[0]}")

    # 2. Register Events
    # Format: 'Event Name': (function_name, 'output_filename.png')
    events_to_plot = {
        'High Volatility (>50Mbps)': (identify_high_volatility, 'plot_evt_volatility.png'),
        'SCell Change':              (identify_scell_change,    'plot_evt_scell_change.png'),
        'Handover Prep (Signal Drop)': (identify_handover_prep, 'plot_evt_handover_prep.png'),
        'Recovery (SCell Add)':      (identify_recovery_event,  'plot_evt_recovery.png'),
        'Band Change': (identify_band_change, 'plot_evt_band_change.png'),
        'CQI Drop (>3)': (identify_cqi_drop,    'plot_evt_cqi_drop.png'),
    }

    # 3. Load Model Predictions
    data_store = {'Ground Truth': df_ref['Ground_Truth_Mbps'].values}
    all_files = glob.glob(os.path.join(CSV_DIR, BASE_PATTERN))
    if os.path.exists(os.path.join(CSV_DIR, EXCEPTION_FILE)):
        all_files.append(os.path.join(CSV_DIR, EXCEPTION_FILE))

    for f in all_files:
        key = get_model_key(os.path.basename(f))
        try:
            df = pd.read_csv(f)
            if len(df) == len(df_ref):
                data_store[key] = df['Predicted_Mbps'].values
        except: pass

    # 4. Execute Analysis
    print("Starting event analysis...")
    for evt_name, (func, fname) in events_to_plot.items():
        print(f"Processing: {evt_name}...")
        indices = func(df_ref)
        plot_event_series(evt_name, indices, data_store, fname)

if __name__ == "__main__":
    main()