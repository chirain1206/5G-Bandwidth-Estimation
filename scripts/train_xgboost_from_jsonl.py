import json
import re
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
import os
import argparse
import time

# ================= Argument Parsing =================
def parse_args():
    parser = argparse.ArgumentParser(description="Train XGBoost Baseline from JSONL Data")
    
    # Dataset Selection
    parser.add_argument("--dataset_type", type=str, required=True, choices=['custom', 'nsg'],
                        help="Choose 'nsg' to include MCS/RB/MIMO features, or 'custom' for basic signals only.")
    
    # History Mode
    parser.add_argument("--history_mode", type=str, required=True, choices=['full_3', 't1_full', 'full_3_SCells'],
                        help="Choose 'full_3' for T1-T3 lags, or 't1_full' for only T1 lag.")

    return parser.parse_args()

# ================= Helper Functions =================

def extract_val(text, pattern, type_func=float):
    """
    Extracts a value using regex. Returns NaN if not found.
    """
    match = re.search(pattern, text)
    if match:
        try:
            return type_func(match.group(1))
        except:
            return np.nan
    return np.nan

def parse_jsonl_to_df(file_path, dataset_type, history_mode):
    """
    Parses JSONL file into a Pandas DataFrame suitable for XGBoost.
    Extracts features from the 'user' content string.
    """
    print(f"Parsing {file_path} [Type: {dataset_type}, Mode: {history_mode}]...")
    
    data = []
    
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return pd.DataFrame()

    with open(file_path, 'r') as f:
        lines = f.readlines()
        
    for line in lines:
        try:
            entry = json.loads(line)
            messages = entry['messages']
            
            # 1. Extract Target (Label)
            # Find the assistant message
            target_str = next((m['content'] for m in messages if m['role'] == 'assistant'), None)
            if target_str is None: continue
            target = float(target_str)

            # 2. Extract Input Features (User Prompt)
            user_content = next((m['content'] for m in messages if m['role'] == 'user'), "")
            
            # Initialize row dict
            row = {'Target_Mbps': target, 'User_Prompt': user_content}
            
            # ==========================================
            # A. Parsing History
            # ==========================================
            # Determine steps based on history mode
            if history_mode == 'full_3' or 'full_3_SCells':
                steps = [1, 2, 3]
            else:
                # Both t1_full and t1_bw_only use only T-1
                steps = [1]
            
            for i in steps:
                # Regex for T-i line
                step_pattern = rf"T-{i} \(Throughput: ([\d\.]+) Mbps\)"
                # If mode is NOT t1_bw_only, capture the metrics string too
                if history_mode != 't1_bw_only':
                    step_pattern += ": (.*)"
                
                step_match = re.search(step_pattern, user_content)
                
                if step_match:
                    # History Throughput (Always present)
                    row[f'Lag_{i}_Mbps'] = float(step_match.group(1))
                    
                    # History Metrics (Only if NOT t1_bw_only)
                    if history_mode != 't1_bw_only':
                        hist_state_str = step_match.group(2)
                        
                        # Extract Key Metrics from History
                        row[f'Lag_{i}_LTE_PCell_RSRP'] = extract_val(hist_state_str, r"LTE Primary Cell:.*RSRP ([\-\d\.]+)dBm")
                        row[f'Lag_{i}_LTE_PCell_RSRQ'] = extract_val(hist_state_str, r"LTE Primary Cell:.*RSRQ ([\-\d\.]+)dBm")
                        row[f'Lag_{i}_LTE_PCell_SINR'] = extract_val(hist_state_str, r"LTE Primary Cell:.*SINR ([\-\d\.]+)dBm")
                        row[f'Lag_{i}_LTE_PCell_CQI']  = extract_val(hist_state_str, r"LTE Primary Cell:.*CQI ([\d]+)")
                        row[f'Lag_{i}_NR_RSRP']  = extract_val(hist_state_str, r"5G:.*SS-RSRP ([\-\d\.]+)dBm")
                        row[f'Lag_{i}_NR_RSRQ']  = extract_val(hist_state_str, r"5G:.*SS-RSRQ ([\-\d\.]+)dBm")
                        row[f'Lag_{i}_NR_SINR']  = extract_val(hist_state_str, r"5G:.*SS-SINR ([\-\d\.]+)dBm")
                        row[f'Lag_{i}_NR_CQI']  = extract_val(hist_state_str, r"5G:.*SS-CQI ([\-\d\.]+)dBm")
                        
                        if history_mode == 'full_3_SCells':
                            for j in [1, 2, 3]:
                                row[f'Lag_{i}_LTE_SCell{j}_RSRP'] = extract_val(hist_state_str, rf"LTE Secondary Cell{j}:.*RSRP ([\-\d\.]+)dBm")
                                row[f'Lag_{i}_LTE_SCell{j}_RSRQ'] = extract_val(hist_state_str, rf"LTE Secondary Cell{j}:.*RSRQ ([\-\d\.]+)dBm")
                                row[f'Lag_{i}_LTE_SCell{j}_SINR'] = extract_val(hist_state_str, rf"LTE Secondary Cell{j}:.*SINR ([\-\d\.]+)dBm")
                        
                        if dataset_type == 'nsg':
                            row[f'Lag_{i}_LTE_MCS'] = extract_val(hist_state_str, r"LTE \[.*MCS ([\d]+)")
                            row[f'Lag_{i}_LTE_RB'] = extract_val(hist_state_str, r"LTE \[.*RB ([\d]+)")
                            row[f'Lag_{i}_LTE_MIMO'] = extract_val(hist_state_str, r"LTE \[.*MIMO ([\d]+)")
                            
                            row[f'Lag_{i}_NR_MCS'] = extract_val(hist_state_str, r"NR \[.*MCS ([\d]+)")
                            row[f'Lag_{i}_NR_RB']  = extract_val(hist_state_str, r"NR \[.*RB ([\d]+)")
                            row[f'Lag_{i}_NR_MIMO']  = extract_val(hist_state_str, r"NR \[.*MIMO ([\d]+)")
                else:
                    row[f'Lag_{i}_Mbps'] = np.nan

            # ==========================================
            # B. Parsing Current State
            # ==========================================
            parts = user_content.split("Current Network State:")
            if len(parts) > 1:
                current_block = parts[1]
                
                # Basic Signals
                row['Cur_LTE_RSRP'] = extract_val(current_block, r"LTE Primary Cell:.*RSRP ([\-\d\.]+)dBm")
                row['Cur_LTE_RSRQ'] = extract_val(current_block, r"LTE Primary Cell:.*RSRQ ([\-\d\.]+)dB")
                row['Cur_LTE_SINR'] = extract_val(current_block, r"LTE Primary Cell:.*SINR ([\-\d\.]+)dB")
                row['Cur_LTE_CQI']  = extract_val(current_block, r"LTE Primary Cell:.*CQI ([\d]+)")
                
                row['Cur_NR_RSRP']  = extract_val(current_block, r"5G:.*SS-RSRP ([\-\d\.]+)dBm")
                row['Cur_NR_RSRQ']  = extract_val(current_block, r"5G:.*SS-RSRQ ([\-\d\.]+)dB")
                row['Cur_NR_SINR']  = extract_val(current_block, r"5G:.*SS-SINR ([\-\d\.]+)dB")
                row['Cur_NR_CQI']   = extract_val(current_block, r"5G:.*CQI ([\d]+)")
                
                if dataset_type == 'custom':
                    for j in [1, 2, 3]:
                        row[f'Cur_LTE_SCell{j}_RSRP'] = extract_val(current_block, rf"LTE Secondary Cell{j}:.*RSRP ([\-\d\.]+)dBm")
                        row[f'Cur_LTE_SCell{j}_RSRQ'] = extract_val(current_block, rf"LTE Secondary Cell{j}:.*RSRQ ([\-\d\.]+)dBm")
                        row[f'Cur_LTE_SCell{j}_SINR'] = extract_val(current_block, rf"LTE Secondary Cell{j}:.*SINR ([\-\d\.]+)dBm")

                # Physical Layer (NSG Only)
                if dataset_type == 'nsg':
                    row['Cur_LTE_MCS']  = extract_val(current_block, r"LTE \[.*MCS ([\d]+)")
                    row['Cur_LTE_RB']   = extract_val(current_block, r"LTE \[.*RB ([\d]+)")
                    row['Cur_LTE_MIMO'] = extract_val(current_block, r"LTE \[.*MIMO ([\d]+)")
                    
                    row['Cur_NR_MCS']   = extract_val(current_block, r"NR \[.*MCS ([\d]+)")
                    row['Cur_NR_RB']    = extract_val(current_block, r"NR \[.*RB ([\d]+)")
                    row['Cur_NR_MIMO']  = extract_val(current_block, r"NR \[.*MIMO ([\d]+)")

            data.append(row)
            
        except Exception as e:
            continue

    df = pd.DataFrame(data)
    print(f"Successfully loaded {len(df)} rows.")
    return df

# ================= Main Execution =================

def main():
    args = parse_args()
    
    # Create output directory
    task_name = f"{args.dataset_type}_{args.history_mode}"
    #full_output_dir = os.path.join(args.output_dir, task_name)
    #os.makedirs(full_output_dir, exist_ok=True)
    train_file = f"dataset_{args.dataset_type}_{args.history_mode}/train.jsonl"
    val_file = f"dataset_{args.dataset_type}_{args.history_mode}/val.jsonl"
    full_output_dir = f"predictor_xgboost_{args.dataset_type}_{args.history_mode}"
    

    # 1. Prepare Data
    df_train = parse_jsonl_to_df(train_file, args.dataset_type, args.history_mode)
    df_val = parse_jsonl_to_df(val_file, args.dataset_type, args.history_mode)

    if df_train.empty or df_val.empty:
        print("Error: Train or Val dataframe is empty. Check input files.")
        return

    # Define features (X) and target (y)
    target_col = 'Target_Mbps'
    feature_cols = [c for c in df_train.columns if c not in [target_col, 'User_Prompt']]
    
    print(f"\nFeatures used ({len(feature_cols)}): {feature_cols}")

    X_train = df_train[feature_cols]
    y_train = df_train[target_col]
    X_val = df_val[feature_cols]
    y_val = df_val[target_col]
    val_prompts = df_val['User_Prompt'].values

    # Handle NaNs (XGBoost handles them, but -999 is explicit)
    # Important: If dataset is 'custom', Phys columns won't exist, so this is safe.
    X_train = X_train.fillna(-999)
    X_val = X_val.fillna(-999)

    # 2. Train XGBoost
    print(f"\nTraining XGBoost for {task_name}...")
    
    model = xgb.XGBRegressor(
        n_estimators=1000,
        learning_rate=0.05,
        max_depth=8,
        subsample=0.8,
        colsample_bytree=0.8,
        n_jobs=-1,
        random_state=42,
        early_stopping_rounds=50
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=100
    )
    
    # 3. Predict & Measure Time
    print("\nRunning Inference on Validation Set...")
    start_time = time.time()
    preds = model.predict(X_val)
    end_time = time.time()
    
    # Calculate avg inference time per sample (in ms)
    total_time_ms = (end_time - start_time) * 1000
    avg_inference_time = total_time_ms / len(preds)
    
    mae = mean_absolute_error(y_val, preds)
    rmse = np.sqrt(mean_squared_error(y_val, preds))
    r2 = r2_score(y_val, preds)

    print("="*40)
    print(f"RESULTS: {task_name}")
    print("="*40)
    print(f"MAE:  {mae:.4f}")
    print(f"RMSE: {rmse:.4f}")
    print(f"R2:   {r2:.4f}")
    print("="*40)
    
    # 4. Generate & Save CSV
    print("Generating Evaluation CSV...")
    
    results_df = pd.DataFrame({
        'Input_Prompt_Snippet': val_prompts, # <--- FULL CONTENT, NO TRUNCATION
        'Ground_Truth_Mbps': y_val,
        'Predicted_Mbps': preds,
        'Abs_Error': np.abs(y_val - preds),
        'Inference_Time_ms': [avg_inference_time] * len(preds)
    })
    
    csv_filename = f"eval_xgboost_{task_name}.csv"
    csv_path = os.path.join(full_output_dir, csv_filename)
    results_df.to_csv(csv_path, index=False)
    print(f"CSV Saved to: {csv_path}")

    # 5. Save Plots & Model
    # Save Metrics to text file
    with open(os.path.join(full_output_dir, "metrics.txt"), "w") as f:
        f.write(f"Task: {task_name}\n")
        f.write(f"MAE: {mae:.4f}\nRMSE: {rmse:.4f}\nR2: {r2:.4f}\n")
    
    # Feature Importance
    plt.figure(figsize=(12, 10))
    xgb.plot_importance(model, max_num_features=25, importance_type='gain', height=0.8)
    plt.title(f"Feature Importance (Gain) - {task_name}")
    plt.tight_layout()
    plt.savefig(os.path.join(full_output_dir, "feature_importance.png"))
    plt.close()

    # Save Scatter Plot (Pred vs True)
    plt.figure(figsize=(8, 8))
    plt.scatter(y_val, preds, alpha=0.3, s=10, color='blue')
    p1 = max(max(preds), max(y_val))
    p2 = min(min(preds), min(y_val))
    plt.plot([p1, p2], [p1, p2], 'r--', label='Ideal')
    plt.xlabel('Ground Truth (Mbps)')
    plt.ylabel('Prediction (Mbps)')
    plt.title(f'XGBoost: {task_name}\nR2={r2:.3f}')
    plt.grid(True)
    plt.savefig(os.path.join(full_output_dir, "scatter_plot.png"))
    plt.close()
    
    # Save the XGBoost Model
    model_save_path = os.path.join(full_output_dir, "xgboost_model.json")
    model.save_model(model_save_path)
    print(f"XGBoost Model saved to: {model_save_path}")

    print(f"Artifacts saved to {full_output_dir}")

if __name__ == "__main__":
    main()