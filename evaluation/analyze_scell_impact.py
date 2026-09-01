import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import glob
import os
import re

# ================= Configuration =================
CSV_DIR = '.'
TARGET_FILE_PATTERN = "eval_application_throughput_full_3_scellsIn_qwen.csv"

def get_scell_count(text):
    if not isinstance(text, str) or "Current Network State" not in text:
        return 0
    current_part = text.split("Current Network State")[1]
    
    match = re.search(r"\[Secondary Cells\]:(.*)", current_part)
    if match:
        scell_line = match.group(1)
        return len(re.findall(r"RSRP:?\s*-?\d", scell_line))
    return 0

def get_pcell_rsrp(text):
    if not isinstance(text, str) or "Current Network State" not in text:
        return -140
    current_part = text.split("Current Network State")[1]
    match = re.search(r"Primary Cell.*?SS-RSRP\s*([-\d\.]+)", current_part)
    return float(match.group(1)) if match else -140

def main():
    # 1. Load Data
    files = glob.glob(os.path.join(CSV_DIR, TARGET_FILE_PATTERN))
    if not files:
        # Fallback to check exceptions or other files
        files = glob.glob(os.path.join(CSV_DIR, "*qwen*.csv"))
    
    if not files:
        print("Error: No suitable CSV file found to parse prompts.")
        return

    filepath = files[0]
    print(f"Analyzing SCell Impact using: {filepath}")
    df = pd.read_csv(filepath)

    # 2. Extract Features
    print("Parsing prompts...")
    df['SCell_Count'] = df['Input_Prompt_Snippet'].apply(get_scell_count)
    df['PCell_RSRP'] = df['Input_Prompt_Snippet'].apply(get_pcell_rsrp)
    
    df_active = df[df['Ground_Truth_Mbps'] > 10].copy()
    
    # ================= Analysis 1: Correlation =================
    corr = df_active[['Ground_Truth_Mbps', 'SCell_Count', 'PCell_RSRP']].corr()
    print("\n" + "="*40)
    print(" Feature Correlation Matrix ")
    print("="*40)
    print(corr['Ground_Truth_Mbps'])
    print("-" * 40)
    
    # ================= Analysis 2: Boxplot (Throughput by SCell Count) =================
    plt.figure(figsize=(8, 6))
    sns.boxplot(x='SCell_Count', y='Ground_Truth_Mbps', data=df_active, palette="Blues")
    plt.title('Impact of SCell Count on Throughput', fontsize=14)
    plt.xlabel('Number of Active SCells', fontsize=12)
    plt.ylabel('Throughput (Mbps)', fontsize=12)
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    plt.savefig('scell_impact_boxplot.png', dpi=300)
    print("Saved scell_impact_boxplot.png")
    
    # ================= Analysis 3: Marginal Gain (Average Tput per Count) =================
    summary = df_active.groupby('SCell_Count')['Ground_Truth_Mbps'].agg(['mean', 'median', 'count', 'std'])
    print("\n" + "="*40)
    print(" Throughput Stats by SCell Count ")
    print("="*40)
    print(summary)
    
    if 0 in summary.index and 1 in summary.index:
        gain = summary.loc[1, 'mean'] - summary.loc[0, 'mean']
        print(f"\nAverage Gain from 0 -> 1 SCell: +{gain:.2f} Mbps")
    
    if 1 in summary.index and 2 in summary.index:
        gain = summary.loc[2, 'mean'] - summary.loc[1, 'mean']
        print(f"Average Gain from 1 -> 2 SCells: +{gain:.2f} Mbps")

    # ================= Analysis 4: Control Variable (High Signal Only) =================
    df_good_signal = df_active[df_active['PCell_RSRP'] > -90]
    if not df_good_signal.empty:
        summary_good = df_good_signal.groupby('SCell_Count')['Ground_Truth_Mbps'].mean()
        print("\n" + "="*40)
        print(" Impact under GOOD Signal (RSRP > -90) ")
        print("="*40)
        print(summary_good)
        
        plt.figure(figsize=(8, 6))
        sns.boxplot(x='SCell_Count', y='Ground_Truth_Mbps', data=df_good_signal, palette="Greens")
        plt.title('Impact of SCell Count (Good Signal Only)', fontsize=14)
        plt.savefig('scell_impact_good_signal.png', dpi=300)
        print("Saved scell_impact_good_signal.png")

if __name__ == "__main__":
    main()