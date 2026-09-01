import pandas as pd
import glob
import os
import json
import numpy as np
import argparse
from sklearn.model_selection import train_test_split

# ================= Argument Parsing =================
def parse_args():
    parser = argparse.ArgumentParser(description="Unified Preprocessing for 5G Bandwidth Prediction")
    
    parser.add_argument("--input_path", type=str, default="./",
                        help="Path to the coalesced CSV file or folder.")
    
    parser.add_argument("--output_root", type=str, default=".",
                        help="Root directory to save the output folder.")
   
    parser.add_argument("--split_ratio", type=float, default=0.2,
                        help="Percentage of validation set (e.g. 0.2 for 20%).")
                        
    parser.add_argument("--window_size", type=int, default=3,
                        help="Window size of historical information")
                        
    parser.add_argument("--history_mode", type=str, default="full",
                        choices=['full', 'bw_only'],
                        help="full: history contains device signal. bw_only: history contains only past throughput")
                        
    parser.add_argument("--include_scells", action="store_true",
                        help="Wheather or not to include secondary cells information")
                        
    parser.add_argument("--throughput_mode", type=str, default="application_throughput",
                        choices=['application_throughput', 'phys_throughput'],
                        help="Select prediction target source.")
                        
    parser.add_argument("--sample_ratio", type=float, default=1.0,
                        help="Fraction of data to keep (e.g., 0.5 for 50%). Default 1.0 (keep all).")
                        
    return parser.parse_args()

# ================= Helper: Data Cleaning =================
def apply_context_aware_cleaning(df, rsrp_col, target_col='Target_Mbps'):
    """
    Applies outlier cleaning based on RSRP bins to remove statistical anomalies.
    """
    print(f">>> Applying Context-Aware Cleaning (Based on {rsrp_col})...")
    
    # Create bins (Range -140 to -40, step 5)
    df['RSRP_Bin'] = pd.cut(df[rsrp_col], bins=range(-140, -40, 5))
    
    # Calculate stats per bin
    grouped = df.groupby('RSRP_Bin', observed=False)[target_col]
    df['Bin_Mean'] = grouped.transform('mean')
    df['Bin_Std']  = grouped.transform('std')

    def is_valid(row):
        if pd.isna(row['Bin_Mean']) or pd.isna(row['Bin_Std']): return True
        
        # 3-sigma rule
        sigma = 3.0 
        lower = max(row['Bin_Mean'] - sigma * row['Bin_Std'], 0.1) 
        upper = row['Bin_Mean'] + sigma * row['Bin_Std']
        
        return lower <= row[target_col] <= upper

    before_len = len(df)
    df_clean = df[df.apply(is_valid, axis=1)].copy()
    print(f"    Cleaned outliers: {before_len} -> {len(df_clean)} rows")
    
    return df_clean.drop(columns=['RSRP_Bin', 'Bin_Mean', 'Bin_Std'])

# ================= Helper: History Generation =================
def generate_history_features(df, group_col, time_col, target_col, state_col, history_mode, window_size):
    """
    Generates history strings containing Throughput and Network State.
    Crucial: This generates history for Time T-1, T-2... to be used as input at Time T.
    """
    
    print(f">>> Generating History (Window: {window_size})...")
    
    # Sort to ensure correct shifting
    df = df.sort_values([group_col, time_col])
    
    # Calculate Time Diff to ensure continuity (we don't want history from 10s ago)
    df['Time_Diff'] = df.groupby(group_col)[time_col].diff().dt.total_seconds()
    
    # Create Lag columns
    for i in range(1, window_size + 1):
        # Shift features BACKWARDS to create history for the current row
        df[f'Lag_Bw_{i}'] = df.groupby(group_col)[target_col].shift(i)
        df[f'Lag_State_{i}'] = df.groupby(group_col)[state_col].shift(i)

    def format_history(row):
        # Allow small gaps (e.g. up to 1.5s or 2.0s due to processing jitter), but reject large gaps
        if pd.isna(row['Time_Diff']) or row['Time_Diff'] >= 2.0:
            return None # Discontinuous, cannot form valid history
            
        lines = []
        for i in range(1, window_size + 1):
            bw = row.get(f'Lag_Bw_{i}')
            state = row.get(f'Lag_State_{i}')
            
            if pd.isna(bw) or pd.isna(state):
                return None 
                
            if history_mode == 'bw_only':
                lines.append(f"T-{i} Throughput: {bw:.2f} Mbps")
            else:
                lines.append(f"T-{i} (Throughput: {bw:.2f} Mbps): {state}")
        
        return "History (Past Activity):\n" + "\n".join(lines)

    df['History_Prompt'] = df.apply(format_history, axis=1)
    
    valid_len = len(df)
    df = df.dropna(subset=['History_Prompt'])
    print(f"    Rows with valid continuous history: {valid_len} -> {len(df)}")
    
    return df

# ================= Formatters (Row -> String) =================

def format_scell_metrics(row):
    """
    Formats SCell metrics. Handles missing values explicitly ("N/A").
    Only includes SCells that have at least valid RSRP or Type info.
    """
    def val(col, unit=""):
        v = row.get(col)
        # Check for NaN or None
        if pd.isna(v) or v == "N/A" or v == "": return "N/A"
        try: return f"{float(v):.1f} {unit}"
        except: return f"{v} {unit}"

    scells = []
    # Assuming MAX_SCELLS is 8 based on merge_dataset.py
    for i in range(1, 9):
        # Check if SCell exists (using Type or RSRP as indicator)
        type_col = f'SCell{i}_Type_NSG'
        rsrp_col = f'SCell{i}_RSRP_NSG'
        
        # If both Type and RSRP are missing, we assume this SCell slot is empty/inactive
        if pd.isna(row.get(type_col)) and pd.isna(row.get(rsrp_col)):
            continue

        rsrp = val(f'SCell{i}_RSRP_NSG', 'dBm')
        rsrq = val(f'SCell{i}_RSRQ_NSG', 'dB')
        sinr = val(f'SCell{i}_SINR_NSG', 'dB')
        band = val(f'SCell{i}_BAND_NSG')
        if band != 'N/A':        
            band = int(float(val(f'SCell{i}_BAND_NSG')))
        cell_type = row.get(type_col, 'Unknown')
        
        # Explicitly format the string. If SINR is N/A, it will show "SINR: N/A"
        scells.append(f"SCell{i} ({cell_type}): [RSRP: {rsrp}, RSRQ: {rsrq}, SINR: {sinr}, BAND: {band}]")
    
    if not scells:
        return "No Secondary Cells Reported"
        
    return " | ".join(scells)

def format_metrics(row, include_scells=False):
    """
    Formats the 'Current Network State' string.
    """
    def val(col, unit="", is_int=False):
        v = row.get(col)
        if pd.isna(v) or v == "N/A": return "N/A"
        try: 
            val_float = float(v)
            if is_int: return f"{int(val_float)} {unit}"
            else: return f"{val_float:.1f} {unit}"
        except: return f"{v} {unit}"

    # 1. Environment / Context
    # Include Timestamp to help LLM understand time of day (derived from Unix if needed, or string)
    # Here we rely on the generic 'State' or just the raw metrics.
    # We can add 'Mobility_Mode' from merge_dataset.py
    #mobility = row.get('Mobility_Mode', 'Unknown')
    #env_str = (f"Mode: {mobility}, "
    #           f"Net: {row.get('Network_Mode_NSG', 'N/A')}, "
    #           f"Speed: {val('Speed_NSG', ' m/s')}")
    env_str = (f"5G Mode: {row.get('Network_Mode_NSG', 'N/A')}, "
               f"Speed: {val('Speed_NSG', ' m/s')}")

    # 2. NR Primary Cell (SA or NSA)
    nr_str = (f"Band {val('NR_PCell_Band_NSG', is_int=True)}, "
              f"SS-RSRP {val('NR_PCell_RSRP_NSG', 'dBm')}, "
              f"SS-RSRQ {val('NR_PCell_RSRQ_NSG', 'dB')}, "
              f"SS-SINR {val('NR_PCell_SINR_NSG', 'dB')}, "
              f"CQI {val('NR_PCell_CQI_NSG', is_int=True)}")

    # 3. LTE Primary Cell (Anchor)
    lte_str = (f"Band {val('LTE_PCell_Band_NSG', is_int=True)}, "
               f"RSRP {val('LTE_PCell_RSRP_NSG', 'dBm')}, "
               f"RSRQ {val('LTE_PCell_RSRQ_NSG', 'dB')}, "
               f"SINR {val('LTE_PCell_SINR_NSG', 'dB')}, "
               f"CQI {val('LTE_PCell_CQI_NSG', is_int=True)}")
    
    base = f"[{env_str}] | [5G Primary Cell: {nr_str}] | [LTE Primary Cell: {lte_str}]"
    
    if include_scells:
        scell_str = format_scell_metrics(row)
        return f"{base}\n[Secondary Cells]: {scell_str}"
    return base

# ================= Processors =================

def process_data(input_file, throughput_mode, include_scells, history_mode, window_size):
    print(f">>> Processing Dataset: {input_file}")
    
    if not os.path.exists(input_file):
        raise ValueError(f"File {input_file} not found.")
        
    df = pd.read_csv(input_file)
    
    print(f"    Initial rows: {len(df)}")

    # 1. Data Filtering
    # Remove data where Probe Elapsed Time is < 3000ms (3s) (TCP Slow-Start Filtering)
    if 'Probe Elapsed Time(ms)' in df.columns:
        before_tcp = len(df)
        df = df[df['Probe Elapsed Time(ms)'] >= 3000].copy()
        print(f"    Filtered TCP Slow-Start (<3000ms): {before_tcp} -> {len(df)} rows")
    else:
        print("    [Warning] 'Probe Elapsed Time(ms)' not found. Skipping TCP filter.")
        
    # Filter for 5G Modes only (SA and NSA)
    if 'Network_Mode_NSG' in df.columns:
        before_mode_filter = len(df)
        # Keep only rows where mode is SA or NSA
        df = df[df['Network_Mode_NSG'].isin(['SA', 'NSA'])].copy()
        print(f"    Filtered Non-5G Modes (Kept SA/NSA): {before_mode_filter} -> {len(df)} rows")
    else:
        print("    [Warning] 'Network_Mode_NSG' column not found. Skipping mode filter.")

    # 2. Determine Raw Target Column (Current/Past Throughput)
    # Note: This is the 'lagged' throughput we calculated in Java/NSG
    if throughput_mode == 'phys_throughput':
        # Ensure column exists (from merge_dataset.py)
        if 'PHYS_Throughput_DL_Total_NSG' not in df.columns:
             # Fallback calculation if column missing
             cols = ['LTE_PCell_PHYS_Throughput_NSG', 'NR_PCell_PHYS_Throughput_NSG']
             df['PHYS_Throughput_DL_Total_NSG'] = df[cols].fillna(0).sum(axis=1)
        
        raw_target_col = 'PHYS_Throughput_DL_Total_NSG'
        print("    Target Source: Physical Layer Throughput (NSG)")
    else:
        # Default: Application Throughput
        # Column name from merge_dataset.py
        raw_target_col = 'APP_Throughput_DL_Total'
        if raw_target_col not in df.columns:
            # Fallback for older CSVs
            if 'Downlink Avg(Mbps)' in df.columns:
                raw_target_col = 'Downlink Avg(Mbps)'
            else:
                raise ValueError(f"Target column '{raw_target_col}' not found.")
        print("    Target Source: Application Layer Throughput")

    # Filter invalid speeds
    df['Raw_Throughput'] = pd.to_numeric(df[raw_target_col], errors='coerce')
    df = df[df['Raw_Throughput'] > 0.1].copy()

    # 3. Create Session Groups
    # Use 'Source_File_ID' from merge_dataset.py to identify unique sessions
    if 'Source_File_ID' not in df.columns:
        print("    [Warning] 'Source_File_ID' not found. Assuming single session (risk of discontinuity).")
        df['Source_File_ID'] = 'dummy_session'
    
    # 4. Parse Timestamp
    #if 'Timestamp' in df.columns:
    #    df['datetime'] = pd.to_datetime(df['Timestamp'], unit='ms')
    #elif 'Timestamp_dt' in df.columns:
    #    df['datetime'] = pd.to_datetime(df['Timestamp_dt'])
    #else:
    #    raise ValueError("No valid Timestamp column found.")
    df['datetime'] = pd.to_datetime(df['Timestamp_dt'])

    df = df.sort_values(['Source_File_ID', 'datetime'])

    # =========================================================================
    # CRITICAL STEP: Shift Target for Forecasting (With Continuity Check)
    # =========================================================================
    print("    >>> Shifting Target by -1 (Forecasting Next Second)...")
    
    # Get the timestamp and throughput for the next row
    # We shift both the target value AND the timestamp to check the gap
    grouped = df.groupby('Source_File_ID')
    df['Prediction_Target'] = grouped['Raw_Throughput'].shift(-1)
    df['Next_Datetime']     = grouped['datetime'].shift(-1)
    
    # Calculate the time difference between current time T and next row T_next
    df['Target_Time_Gap'] = (df['Next_Datetime'] - df['datetime']).dt.total_seconds()
    
    # Strict filtering: Keep only rows where the gap is within a reasonable range (e.g., 0 < gap < 2.0s)
    # If gap >= 2.0s, it indicates missing data or end of session; T cannot be used to predict T_next.
    # gap > 0 ensures no duplicate timestamps.
    valid_continuity = (df['Target_Time_Gap'] > 0) & (df['Target_Time_Gap'] < 2.0)
    
    before_gap_filter = len(df)
    df = df[valid_continuity].copy()
    print(f"    Continuity Check (Future): Dropped {before_gap_filter - len(df)} rows where next sample was missing or too far (>=2s).")
    
    # Cleanup
    df = df.dropna(subset=['Prediction_Target'])
    df = df.drop(columns=['Next_Datetime', 'Target_Time_Gap'])
    print(f"    Rows after shifting and dropping NaNs: {len(df)}")

    # 5. Clean Numeric Columns (for metric formatting)
    # (Optional: ensure numeric types for specific columns used in formatting)
    
    # 6. Generate "Metrics State" String (Signal at Time T)
    df['Metrics_State'] = df.apply(lambda r: format_metrics(r, include_scells), axis=1)

    # 7. Generate History Features
    # Note: We use 'Raw_Throughput' for history, because at Time T, we DO know the throughput of T (past).
    # Input: History(T-1, T-2...) + State(T)
    # Output: Prediction_Target (Throughput T+1)
    df = generate_history_features(
        df, 'Source_File_ID', 'datetime', 'Raw_Throughput', 'Metrics_State',
        history_mode=history_mode, 
        window_size=window_size
    )
    
    # 8. Final Cleaning (Split by Mode for Precision)
    print("    >>> Preparing Mode-Specific Cleaning...")
    
    clean_dfs = []
    
    if 'Network_Mode_NSG' not in df.columns:
        df['Network_Mode_NSG'] = 'Unknown' # Fallback

    # Cleaning for different mode accordingly
    for mode, group in df.groupby('Network_Mode_NSG'):
        if group.empty: continue
        
        # Decide the primary cleaning metric
        if mode == 'SA':
            target_rsrp = 'NR_PCell_RSRP_NSG'
        else: # NSA or LTE or Unknown
            target_rsrp = 'LTE_PCell_RSRP_NSG'
            
        if target_rsrp not in group.columns:
            target_rsrp = 'NR_PCell_RSRP_NSG' if 'NR_PCell_RSRP_NSG' in group.columns else None
            
        if target_rsrp and group[target_rsrp].notna().sum() > 10:
            print(f"    Cleaning Group: {mode} using {target_rsrp}...")
            cleaned_group = apply_context_aware_cleaning(group, rsrp_col=target_rsrp, target_col='Prediction_Target')
            clean_dfs.append(cleaned_group)
        else:
            print(f"    Skipping cleaning for {mode} (Not enough data or missing col).")
            clean_dfs.append(group)

    # Merge back cleaned dataset
    if clean_dfs:
        df = pd.concat(clean_dfs).sort_values(['Source_File_ID', 'datetime'])
        print(f"    Final Dataset Size: {len(df)}")

    return df

# ================= Main =================

def main():
    args = parse_args()
    
    # Check input path
    input_path = args.input_path
    if os.path.isdir(input_path):
        input_path = os.path.join(input_path, "coalesced_bandwidth_traces.csv")
    
    # Process
    df = process_data(input_path, args.throughput_mode, args.include_scells, args.history_mode, args.window_size)
    
    # =========================================================
    # --- Group-wise Sampling ---
    # =========================================================
    if args.sample_ratio < 1.0:
        print(f"\n>>> ?? Group-wise Sampling: Keeping {args.sample_ratio*100}% per Session...")
        
        def sample_per_group(group):
            return group.sample(frac=args.sample_ratio, random_state=19991206)

        df = df.groupby('Source_File_ID', group_keys=False).apply(sample_per_group)
        df = df.reset_index(drop=True)
        print(f"    New Dataset Size: {len(df)}")
    # =========================================================
    
    # Define the precise system prompt required
    system_content_str = (
        "You are a 5G network expert specializing in mobile measurement analysis. "
        "Your task is to forecast the achievable downlink throughput (Mbps) for the **Next Second (Interval [T, T+1])**.\n\n"
        
        "### Temporal Definitions:\n"
        "Data is reported as a sequence of timestamps (T, T-1, T-2...).\n"
        "1. **Metrics (RSRP, SINR, CQI)**: These represent the network signal state measured **at the specific timestamp**.\n"
        "2. **Throughput**: This represents the data rate achieved in the **1-second window ENDING at that timestamp**.\n"
        "   - Example 'T-1': Contains Metrics measured at T-1 AND Throughput accumulated during interval [T-2, T-1].\n"
        "   - Example 'Current T': Contains Metrics measured at T AND Throughput accumulated during interval [T-1, T].\n\n"
        
        "### Input Context:\n"
        "You are provided with:\n"
        "1. **History**: Past network behavior (T-1, T-2...).\n"
        "2. **Current State (Time T)**: Real-time metrics (RSRP, CQI) AND the just-completed throughput (Interval [T-1, T]).\n\n"
        
        "### Key Instructions:\n"
        "1. **Aggregate Capacity**: The total throughput is the sum of contributions from the Primary Cell (PCell) AND all active Secondary Cells (SCells).\n"
        "2. **Ignore List Order**: SCells are listed in arbitrary order. You must evaluate ALL listed cells (PCell + SCells) to determine the total pipe size.\n"
        "3. **Handling Missing Data**: 'N/A' indicates data was not reported. Treat these as having high uncertainty but potential contribution if other indicators (like Type) are present."
    )
    
    # Save Output
    out_dir_name = f"dataset_{args.throughput_mode}_{args.history_mode}_{args.window_size}"
    if args.include_scells:
        out_dir_name += "_scellsIn"
    out_dir = os.path.join(args.output_root, out_dir_name)
    os.makedirs(out_dir, exist_ok=True)
    
    # =========================================================================
    # Split Strategy: Stratified Group Split (Parsing ID directly)
    # =========================================================================
    
    # 1. Get unique session IDs
    unique_sessions = pd.Series(df['Source_File_ID'].unique())
    
    # 2. Extract mode from the ID string (assuming format "mode_timestamp_device")
    # e.g., "driving_2025..." -> "driving"
    session_modes = unique_sessions.apply(lambda x: x.split('_')[0])
    
    train_sessions = []
    val_sessions = []
    
    print(f"\nPerforming Stratified Split (Ratio: {1-args.split_ratio}/{args.split_ratio})...")
    np.random.seed(19991206) 

    # 3. Iterate through each mode found in the IDs
    for mode in session_modes.unique():
        # Filter sessions belonging to this mode
        # mode_sessions is a numpy array of IDs
        mode_sessions = unique_sessions[session_modes == mode].values
        
        # Shuffle
        np.random.shuffle(mode_sessions)
        
        # Calculate split index
        n = len(mode_sessions)
        split_idx = int(n * (1 - args.split_ratio))
        
        # Safety: Ensure at least 1 session in train if possible
        if split_idx == 0 and n > 0: split_idx = 1 
            
        train_sessions.extend(mode_sessions[:split_idx])
        val_sessions.extend(mode_sessions[split_idx:])
        
        print(f"  Mode '{mode}': Total {n} -> Train {split_idx} | Val {n - split_idx}")

    # 4. Apply Split
    train_df = df[df['Source_File_ID'].isin(train_sessions)]
    val_df = df[df['Source_File_ID'].isin(val_sessions)]
    
    def df_to_jsonl(dataframe):
        data = []
        for _, row in dataframe.iterrows():
            current_state = row['Metrics_State']
            history_block = row['History_Prompt']
            current_bw = row['Raw_Throughput']
            
            user_content = (
                f"{history_block}\n\n"
                f"Current Network State (Time T):\n"
                f"Last Second Throughput: {current_bw:.2f} Mbps\n"
                f"{current_state}"
            )
            
            entry = {
                "messages": [
                    {"role": "system", "content": system_content_str},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": f"{row['Prediction_Target']:.2f}"}
                ]
            }
            data.append(entry)
        return data

    train_data = df_to_jsonl(train_df)
    val_data = df_to_jsonl(val_df)
    
    print(f"\nData Split (Session-based):")
    print(f"  Training: {len(train_data)} samples ({len(train_sessions)} sessions)")
    print(f"  Validation: {len(val_data)} samples ({len(val_sessions)} sessions)")
    
    with open(f"{out_dir}/train.jsonl", 'w') as f:
        for entry in train_data: f.write(json.dumps(entry) + '\n')
    with open(f"{out_dir}/val.jsonl", 'w') as f:
        for entry in val_data: f.write(json.dumps(entry) + '\n')
        
    print(f"\nSuccess! Output directory: {out_dir}")

if __name__ == "__main__":
    main()