import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import os

INPUT_FILE = 'coalesced_bandwidth_traces.csv'       
OUTPUT_DIR = 'figures'          
def load_data(filepath):
    if not os.path.exists(filepath):
        print(f"Error: File {filepath} not exists")
        return None
    return pd.read_csv(filepath)

def setup_style():
    sns.set_theme(style="whitegrid")
    plt.rcParams['figure.figsize'] = (10, 6)
    plt.rcParams['font.size'] = 12

def clean_label(label):
    return label.replace('_NSG', '').replace('_', ' ')

def save_current_plot(filename):
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    path = os.path.join(OUTPUT_DIR, filename)
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close() 
    print(f"[Saved] {path}")

# =========================================
#              plot method
# =========================================

def plot_nr_cqi_vs_dl(df):
    """
    Task 1: NR CQI vs Downlink Avg(Mbps)
    Boxplot, No Outliers
    """
    col_x = 'NR_CQI_NSG' 
    col_y = 'Downlink Avg(Mbps)'
    
    if col_x not in df.columns:
        print(f"Skipping Plot 1: Column {col_x} not found.")
        return

    print("Generating Plot 1: NR CQI vs Downlink...")
    
    plt.figure()
    ax = sns.boxplot(x=col_x, y=col_y, data=df, showfliers=False)
    
    plt.xlabel(clean_label(col_x), fontweight='bold')
    plt.ylabel(clean_label(col_y), fontweight='bold')
    plt.title(f'{clean_label(col_y)} by {clean_label(col_x)}')
    
    save_current_plot('1_NR_CQI_vs_Downlink.png')

def plot_lte_cqi_vs_dl(df):
    """
    Task 2: LTE PCell CQI vs Downlink Avg(Mbps)
    Boxplot, No Outliers
    """
    col_x = 'LTE_PCell_CQI_NSG'
    col_y = 'Downlink Avg(Mbps)'
    
    if col_x not in df.columns:
        print(f"Skipping Plot 2: Column {col_x} not found.")
        return

    print("Generating Plot 2: LTE CQI vs Downlink...")

    plt.figure()
    ax = sns.boxplot(x=col_x, y=col_y, data=df, showfliers=False)
    
    plt.xlabel(clean_label(col_x), fontweight='bold')
    plt.ylabel(clean_label(col_y), fontweight='bold')
    plt.title(f'{clean_label(col_y)} by {clean_label(col_x)}')
    
    save_current_plot('2_LTE_CQI_vs_Downlink.png')

# =========================================
#                 Main Program
# =========================================

if __name__ == "__main__":
    df = load_data(INPUT_FILE)
    
    if df is not None:
        setup_style()
        
        plot_nr_cqi_vs_dl(df)
        plot_lte_cqi_vs_dl(df)
        
        # plot_new_custom_chart(df)
        
        print("\nAll plots generated successfully.")