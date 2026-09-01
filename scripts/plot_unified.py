import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import os
import numpy as np

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
    
def filter_data(df):
    """
    Filter data to keep only '5G' and '5G+' Network Types.
    """
    if 'Network Type' not in df.columns:
        print("Warning: 'Network Type' column not found. Skipping filter.")
        return df
    
    target_types = ['5G', '5G+']
    # Filter rows where Network Type is in the target list
    filtered_df = df[df['Network Type'].isin(target_types)].copy()
    
    print(f"Data filtered. Rows before: {len(df)}, Rows after: {len(filtered_df)}")
    return filtered_df

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
    
    if col_x not in df.columns or col_y not in df.columns:
        print(f"Skipping Plot 1: Columns {col_x} or {col_y} not found.")
        return

    print("Generating Plot 1: NR CQI vs Downlink...")
    
    # Drop NaNs to ensure clean integer conversion
    plot_df = df[[col_x, col_y]].dropna().copy()
    
    if plot_df.empty:
        print("No valid data for Plot 1.")
        return

    # Force Integer type for X axis
    plot_df[col_x] = plot_df[col_x].astype(int)
    
    plt.figure()
    ax = sns.boxplot(x=col_x, y=col_y, data=plot_df, showfliers=False)
    
    # Formatting
    plt.xlabel(clean_label(col_x), fontweight='bold')
    plt.ylabel(clean_label(col_y), fontweight='bold')
    plt.title(f'{clean_label(col_x)} vs. {clean_label(col_y)}')
    
    save_current_plot('NR_CQI_vs_Downlink.png')

def plot_lte_cqi_vs_dl(df):
    """
    Task 2: LTE PCell CQI vs Downlink Avg(Mbps)
    Boxplot, No Outliers
    """
    col_x = 'LTE_PCell_CQI_NSG'
    col_y = 'Downlink Avg(Mbps)'
    
    if col_x not in df.columns or col_y not in df.columns:
        print(f"Skipping Plot 2: Columns {col_x} or {col_y} not found.")
        return

    print("Generating Plot 2: LTE CQI vs Downlink...")
    
    # Drop NaNs
    plot_df = df[[col_x, col_y]].dropna()
    
    # Force Integer type for X axis
    plot_df[col_x] = plot_df[col_x].astype(int)

    plt.figure()
    ax = sns.boxplot(x=col_x, y=col_y, data=plot_df, showfliers=False)
    
    # Formatting
    plt.xlabel(clean_label(col_x), fontweight='bold')
    plt.ylabel(clean_label(col_y), fontweight='bold')
    plt.title(f'{clean_label(col_x)} vs. {clean_label(col_y)}')
    
    save_current_plot('LTE_CQI_vs_Downlink.png')

def plot_joint_heatmap(df):
    """
    Hypothesis Verification 1: Heatmap
    X-axis: NR CQI, Y-axis: LTE CQI, Color: Downlink Avg
    """
    col_nr = 'NR_CQI_NSG'
    col_lte = 'LTE_PCell_CQI_NSG'
    col_tp = 'Downlink Avg(Mbps)'
    
    if not {col_nr, col_lte, col_tp}.issubset(df.columns):
        print("Skipping Heatmap: Missing columns.")
        return

    print("Generating Heatmap: NR CQI vs LTE CQI vs Throughput...")
    
    temp_df = df[[col_nr, col_lte, col_tp]].dropna().copy()
    temp_df[col_nr] = temp_df[col_nr].astype(int)
    temp_df[col_lte] = temp_df[col_lte].astype(int)
    
    pivot_table = temp_df.pivot_table(index=col_lte, columns=col_nr, values=col_tp, aggfunc='mean')
    
    pivot_table = pivot_table.sort_index(ascending=False)
    
    plt.figure(figsize=(12, 8))
    sns.heatmap(pivot_table, cmap="viridis", annot=False, fmt=".1f", cbar_kws={'label': 'Avg Downlink (Mbps)'})
    
    plt.xlabel('NR CQI', fontweight='bold')
    plt.ylabel('LTE CQI', fontweight='bold')
    plt.title('Impact of Joint LTE & NR CQI on Throughput')
    
    save_current_plot('Hypothesis_Joint_Heatmap.png')

def plot_nr_cqi_with_lte_hue(df):
    """
    Hypothesis Verification 2: NR CQI vs Downlink, grouped by LTE Quality
    """
    col_x = 'NR_CQI_NSG'
    col_y = 'Downlink Avg(Mbps)'
    col_hue_raw = 'LTE_PCell_CQI_NSG'
    
    if not {col_x, col_y, col_hue_raw}.issubset(df.columns):
        print("Skipping Hue Plot: Missing columns.")
        return

    print("Generating Hue Plot: NR CQI vs Downlink (grouped by LTE)...")
    
    plot_df = df.dropna(subset=[col_x, col_y, col_hue_raw]).copy()
    plot_df[col_x] = plot_df[col_x].astype(int)
    
    def categorize_lte(cqi):
        if cqi <= 6: return 'LTE Low (0-6)'
        elif cqi <= 11: return 'LTE Mid (7-11)'
        else: return 'LTE High (12-15)'
        
    plot_df['LTE_Category'] = plot_df[col_hue_raw].apply(categorize_lte)
    
    hue_order = ['LTE Low (0-6)', 'LTE Mid (7-11)', 'LTE High (12-15)']

    plt.figure(figsize=(12, 6))
    sns.lineplot(x=col_x, y=col_y, hue='LTE_Category', data=plot_df, 
                 hue_order=hue_order, marker="o", errorbar=None)
    
    plt.xlabel('NR CQI', fontweight='bold')
    plt.ylabel('Downlink Avg (Mbps)', fontweight='bold')
    plt.title('NR CQI Performance impacted by LTE Anchor Quality')
    plt.legend(title='LTE Condition')
    
    save_current_plot('Hypothesis_Hue_Trend.png')

def plot_pure_nr_performance(df):
    """
    Hypothesis Verification 3: NR CQI vs NR Specific Throughput
    Using 'NR_Total_TP_DL' instead of total average.
    """
    col_x = 'NR_CQI_NSG'
    col_y = 'NR_Phy_Throughput_NSG'
    
    if col_x not in df.columns or col_y not in df.columns:
        print(f"Skipping Pure NR Plot: Column {col_y} not found.")
        return

    print("Generating Pure NR Plot: NR CQI vs NR Throughput...")
    
    plot_df = df[[col_x, col_y]].dropna().copy()
    plot_df[col_x] = plot_df[col_x].astype(int)
    
    plt.figure()
    sns.boxplot(x=col_x, y=col_y, data=plot_df, showfliers=False)
    
    plt.xlabel('NR CQI', fontweight='bold')
    plt.ylabel('NR Component Throughput (Mbps)', fontweight='bold')
    plt.title('Pure NR Link Performance (NR CQI vs NR TP)')
    
    save_current_plot('Hypothesis_Pure_NR_Performance.png')
    
def plot_pure_lte_performance(df):
    """
    Hypothesis Verification 3: LTE CQI vs LTE Specific Throughput
    Using 'LTE_Total_TP_DL' instead of total average.
    """
    col_x = 'LTE_PCell_CQI_NSG'
    col_y = 'LTE_PCell_Phy_Throughput_NSG'
    
    if col_x not in df.columns or col_y not in df.columns:
        print(f"Skipping Pure LTE Plot: Column {col_y} not found.")
        return

    print("Generating Pure LTE Plot: LTE CQI vs LTE Throughput...")
    
    plot_df = df[[col_x, col_y]].dropna().copy()
    plot_df[col_x] = plot_df[col_x].astype(int)
    
    plt.figure()
    sns.boxplot(x=col_x, y=col_y, data=plot_df, showfliers=False)
    
    plt.xlabel('LTE CQI', fontweight='bold')
    plt.ylabel('LTE Component Throughput (Mbps)', fontweight='bold')
    plt.title('Pure LTE Link Performance (LTE CQI vs LTE TP)')
    
    save_current_plot('Hypothesis_Pure_LTE_Performance.png')
    
def plot_rb_distribution(df):
    """
    Validation 1: NR RB Allocation vs NR CQI
    Hypothesis: High CQI areas might have lower RB allocation due to congestion.
    """
    col_x = 'NR_CQI_NSG'
    col_y = 'NR_RB_Count_NSG' 
    
    if col_x not in df.columns or col_y not in df.columns:
        print(f"Skipping RB Plot: Columns {col_x} or {col_y} not found.")
        return

    print("Generating Validation Plot: RB Allocation...")
    
    plot_df = df[[col_x, col_y]].dropna().copy()
    plot_df[col_x] = plot_df[col_x].astype(int)
    plot_df[col_y] = plot_df[col_y].astype(int)

    plt.figure()

    sns.boxplot(x=col_x, y=col_y, data=plot_df, showfliers=False)
    
    plt.xlabel('NR CQI', fontweight='bold')
    plt.ylabel('Allocated RBs', fontweight='bold')
    plt.title('Resource Block (RB) Allocation by CQI')
    
    save_current_plot('Validation_RB_Allocation.png')

def plot_mimo_layers_ratio(df):
    """
    Validation 2: MIMO Layers Ratio vs NR CQI (Stacked Bar)
    Hypothesis: Mid-range CQI might have higher Rank (3 or 4 layers) than High CQI.
    """
    col_x = 'NR_CQI_NSG'
    col_y = 'NR_MIMO_Layers_NSG' 
    
    if col_x not in df.columns or col_y not in df.columns:
        print(f"Skipping MIMO Plot: Columns {col_x} or {col_y} not found.")
        return

    print("Generating Validation Plot: MIMO Layers Ratio...")
    
    plot_df = df[[col_x, col_y]].dropna().copy()
    plot_df[col_x] = plot_df[col_x].astype(int)
    plot_df[col_y] = plot_df[col_y].astype(int)
    
    # CQI 1: {Layer 1: 50, Layer 2: 10}
    # CQI 2: {Layer 1: 40, Layer 2: 20}
    cross_tab = pd.crosstab(plot_df[col_x], plot_df[col_y], normalize='index') * 100
    

    ax = cross_tab.plot(kind='bar', stacked=True, figsize=(12, 6), colormap='viridis')
    
    plt.xlabel('NR CQI', fontweight='bold')
    plt.ylabel('Percentage (%)', fontweight='bold')
    plt.title('MIMO Layers Distribution by CQI')
    plt.legend(title='Layers', bbox_to_anchor=(1.05, 1), loc='upper left')
    
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, 'Validation_MIMO_Layers.png')
    plt.savefig(path, dpi=300)
    plt.close()
    print(f"[Saved] {path}")
    
def plot_throughput_contribution_cdf(df):
    """
    Proof 1: CDF of LTE Contribution Ratio
    Calculates LTE_Ratio = LTE_TP / (LTE_TP + NR_TP)
    """
    col_lte = 'LTE_PCell_Phy_Throughput_NSG'
    col_nr = 'NR_Phy_Throughput_NSG'
    
    if col_lte not in df.columns or col_nr not in df.columns:
        print("Skipping CDF Plot: Throughput columns not found.")
        return

    print("Generating Proof Plot 1: LTE Contribution CDF...")
    
    temp_df = df[[col_lte, col_nr]].dropna().copy()
    temp_df['Total'] = temp_df[col_lte] + temp_df[col_nr]
    temp_df = temp_df[temp_df['Total'] > 0]
    
    temp_df['LTE_Ratio'] = temp_df[col_lte] / temp_df['Total']
    
    plt.figure(figsize=(8, 6))
    sns.ecdfplot(data=temp_df, x='LTE_Ratio', linewidth=2, color='darkred')
    
    plt.axvline(0.5, color='gray', linestyle='--', alpha=0.7)
    plt.text(0.05, 0.9, 'NR Dominant', transform=plt.gca().transAxes, fontsize=12, color='blue')
    plt.text(0.8, 0.1, 'LTE Dominant', transform=plt.gca().transAxes, fontsize=12, color='darkred')
    
    plt.xlabel('LTE Contribution Ratio (LTE / Total)', fontweight='bold')
    plt.ylabel('Cumulative Probability (CDF)', fontweight='bold')
    plt.title('Distribution of LTE Contribution to Total Throughput')
    plt.grid(True, alpha=0.3)
    
    save_current_plot('Proof_LTE_Contribution_CDF.png')

def plot_tp_scatter_comparison(df):
    """
    Proof 2: Scatter Plot (LTE vs Total AND NR vs Total)
    Shows which component correlates better with total speed.
    """
    col_lte = 'LTE_PCell_Phy_Throughput_NSG'
    col_nr = 'NR_Phy_Throughput_NSG'
    col_total = 'Downlink Avg(Mbps)'
    
    if not {col_lte, col_nr, col_total}.issubset(df.columns):
        print("Skipping Scatter Proof: Columns missing.")
        return

    print("Generating Proof Plot 2: Throughput Scatter Comparison...")
    
    temp_df = df[[col_total, col_lte, col_nr]].dropna()
    
    plt.figure(figsize=(8, 8))
    
    plt.scatter(temp_df[col_total], temp_df[col_lte], 
                alpha=0.3, s=10, color='red', label='LTE Component')
    
    plt.scatter(temp_df[col_total], temp_df[col_nr], 
                alpha=0.3, s=10, color='blue', label='NR Component')
    
    max_val = temp_df[col_total].max()
    plt.plot([0, max_val], [0, max_val], 'k--', alpha=0.5, label='Total (y=x)')
    
    plt.xlabel('Total Downlink Throughput (Mbps)', fontweight='bold')
    plt.ylabel('Component Throughput (Mbps)', fontweight='bold')
    plt.title('LTE and NR Phys throughput vs. Total Throughput')
    plt.legend()
    
    save_current_plot('Proof_TP_Scatter_Compare.png')
        
def plot_band_distribution(df):
    """
    Proof 4: Band Distribution Analysis (Percentage)
    Validates the hypothesis that only Low/Mid bands are present.
    Y-axis: Percentage (%)
    """
    col_lte = 'LTE_PCell_Band_NSG'
    col_nr = 'NR_Band_NSG'
    
    if col_lte not in df.columns or col_nr not in df.columns:
        print("Skipping Band Distribution: Columns not found.")
        return

    print("Generating Proof Plot 4: Band Distribution (Percentage)...")

    lte_series = df[col_lte].dropna().astype(int)
    nr_series = df[col_nr].dropna().astype(int)

    lte_counts = lte_series.value_counts(normalize=True).sort_index() * 100
    nr_counts = nr_series.value_counts(normalize=True).sort_index() * 100

    def classify_band(band, tech='NR'):
        if tech == 'NR':
            if band >= 257: return 'High-Band (mmWave)'
            elif band in [41, 77, 78, 79, 1, 2, 3, 7, 25, 66]: return 'Mid-Band (Sub-6)'
            else: return 'Low-Band (<1GHz)'
        else:
            if band in [41, 42, 48]: return 'High/Mid-Band (TDD)'
            elif band in [1, 2, 3, 4, 66]: return 'Mid-Band'
            else: return 'Low-Band'

    print("\n--- NR Band Stats (Top 5) ---")
    for band, pct in nr_counts.head(5).items():
        cat = classify_band(band, 'NR')
        print(f"Band n{band}: {pct:.1f}% ({cat})")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # Plot 1: LTE Band (Percentage)
    sns.barplot(x=lte_counts.index, y=lte_counts.values, ax=axes[0], palette='Reds')
    axes[0].set_title('LTE Anchor Band Distribution', fontweight='bold')
    axes[0].set_xlabel('LTE Band Number')
    axes[0].set_ylabel('Percentage (%)')
    axes[0].set_ylim(0, max(lte_counts.values) * 1.15) 
    
    for p in axes[0].patches:
        height = p.get_height()
        if height > 0:
            axes[0].annotate(f'{height:.1f}%', 
                             (p.get_x() + p.get_width() / 2., height), 
                             ha='center', va='bottom', fontsize=10)

    # Plot 2: NR Band (Percentage)
    sns.barplot(x=nr_counts.index, y=nr_counts.values, ax=axes[1], palette='Blues')
    axes[1].set_title('5G NR Band Distribution', fontweight='bold')
    axes[1].set_xlabel('NR Band Number')
    axes[1].set_ylabel('Percentage (%)')
    axes[1].set_ylim(0, max(nr_counts.values) * 1.15)
    
    for p in axes[1].patches:
        height = p.get_height()
        if height > 0:
            axes[1].annotate(f'{height:.1f}%', 
                             (p.get_x() + p.get_width() / 2., height), 
                             ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    
    filename = 'Proof_Band_Distribution_Pct.png'
    if 'OUTPUT_DIR' in globals():
        path = os.path.join(OUTPUT_DIR, filename)
        plt.savefig(path, dpi=300)
        plt.close()
        print(f"[Saved] {path}")
    else:
        plt.savefig(filename, dpi=300)
        plt.close()
        
def plot_scell_analysis(df):
    """
    Validation: LTE SCell Contribution Analysis (Direct PHY Reading)
    Reads 'LTE_SCellx_Phy_Throughput_NSG' columns directly to calculate SCell contribution.
    Comparisons are made strictly within the PHY Layer (NR vs PCell vs SCell) to be fair.
    """
    col_nr = 'NR_Phy_Throughput_NSG'
    col_lte_pcell = 'LTE_PCell_Phy_Throughput_NSG'
    
    scell_candidates = [
        'LTE_SCell1_Phy_Throughput_NSG',
        'LTE_SCell2_Phy_Throughput_NSG', 
        'LTE_SCell3_Phy_Throughput_NSG'
    ]
    
    if col_nr not in df.columns or col_lte_pcell not in df.columns:
        print(f"Skipping SCell Plot: Missing PCell or NR TP columns.")
        return

    print("Generating Validation Plot: SCell Contribution (PHY Layer)...")

    plot_df = df[[col_nr, col_lte_pcell]].copy()
    
    found_scell_cols = [c for c in scell_candidates if c in df.columns]
    
    if not found_scell_cols:
        print("Warning: No LTE_SCellx_Phy_Throughput_NSG columns found. Setting SCell to 0.")
        plot_df['LTE_SCell_Total'] = 0
    else:
        print(f"Found SCell columns: {found_scell_cols}")
        plot_df['LTE_SCell_Total'] = df[found_scell_cols].fillna(0).sum(axis=1)

    plot_df = plot_df.dropna(subset=[col_nr, col_lte_pcell])

    melted_df = plot_df.melt(
        value_vars=[col_nr, col_lte_pcell, 'LTE_SCell_Total'],
        var_name='Component', 
        value_name='Throughput (Mbps)'
    )
    
    melted_df['Component'] = melted_df['Component'].replace({
        col_nr: '5G NR',
        col_lte_pcell: 'LTE PCell (Anchor)',
        'LTE_SCell_Total': 'LTE SCell (Sum 1-3)'
    })

    plt.figure(figsize=(10, 6))
    sns.boxplot(x='Component', y='Throughput (Mbps)', data=melted_df, 
                palette=['#3498db', '#e74c3c', '#f1c40f'],
                showfliers=False)
    
    plt.title('PHY Layer Throughput Comparison: PCell vs SCell vs NR')
    plt.ylabel('PHY Throughput (Mbps)', fontweight='bold')
    plt.xlabel('')
    
    save_current_plot('Val_SCell_Magnitude_Boxplot.png')
    
    if len(plot_df) > 1000:
        display_df = plot_df.iloc[:1000].reset_index(drop=True)
        title_suffix = '(First 1000 Samples)'
    else:
        display_df = plot_df.reset_index(drop=True)
        title_suffix = '(All Samples)'

    plt.figure(figsize=(12, 6))
    
    plt.stackplot(display_df.index, 
                  display_df[col_lte_pcell], 
                  display_df['LTE_SCell_Total'],
                  display_df[col_nr], 
                  labels=['LTE PCell', 'LTE SCell', '5G NR'],
                  colors=['#e74c3c', '#f1c40f', '#3498db'], 
                  alpha=0.85)
    
    plt.legend(loc='upper left', frameon=True)
    plt.title(f'PHY Throughput Composition {title_suffix}')
    plt.ylabel('Stacked PHY Throughput (Mbps)', fontweight='bold')
    plt.xlabel('Sample Index', fontweight='bold')
    plt.xlim(0, len(display_df)-1)
    plt.ylim(bottom=0)
    
    save_current_plot('Val_SCell_Composition_Stack.png')

    plot_df['Total_PHY'] = plot_df[col_nr] + plot_df[col_lte_pcell] + plot_df['LTE_SCell_Total']
    avg_total_phy = plot_df['Total_PHY'].mean()
    
    avg_pcell = plot_df[col_lte_pcell].mean()
    avg_scell = plot_df['LTE_SCell_Total'].mean()
    avg_nr = plot_df[col_nr].mean()
    
    print("\n--- SCell Contribution Analysis (PHY Layer) ---")
    print(f"Total Avg PHY TP: {avg_total_phy:.2f} Mbps")
    if avg_total_phy > 0:
        print(f"  - LTE PCell: {avg_pcell:.2f} Mbps ({(avg_pcell/avg_total_phy)*100:.1f}%)")
        print(f"  - LTE SCell: {avg_scell:.2f} Mbps ({(avg_scell/avg_total_phy)*100:.1f}%)")
        print(f"  - 5G NR:     {avg_nr:.2f} Mbps ({(avg_nr/avg_total_phy)*100:.1f}%)")

# =========================================
#                 Main Program
# =========================================

if __name__ == "__main__":
    df = load_data(INPUT_FILE)
    
    if df is not None:
        # Filter Data (5G and 5G+ only)
        df = filter_data(df)
    
        setup_style()
        
        #plot_nr_cqi_vs_dl(df)
        #plot_lte_cqi_vs_dl(df)
        
        #plot_joint_heatmap(df)
        #plot_pure_lte_performance(df)
        #plot_pure_nr_performance(df)
        
        #plot_rb_distribution(df)
        #plot_mimo_layers_ratio(df)
        
        #plot_throughput_contribution_cdf(df)
        #plot_tp_scatter_comparison(df)
        
        #plot_band_distribution(df)
        
        plot_scell_analysis(df)
        
        print("\nAll plots generated successfully.")