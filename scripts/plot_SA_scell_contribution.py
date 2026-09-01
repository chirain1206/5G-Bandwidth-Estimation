import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# 1. 读取数据
df = pd.read_csv('coalesced_bandwidth_traces.csv')

# 2. 筛选 SA 模式
df_sa = df[df['Network_Mode_NSG'] == 'SA'].copy()

# 3. 计算 Primary 和 Secondary Throughput
# PCell 直接读取
df_sa['Primary Cell (PCell)'] = df_sa['NR_PCell_PHYS_Throughput_NSG']

# SCell = 总吞吐 - PCell吞吐
df_sa['Secondary Cells (SCell)'] = df_sa['PHYS_Throughput_DL_Total_NSG'] - df_sa['NR_PCell_PHYS_Throughput_NSG']

# 数据清洗：将计算产生的负值（如果有）置为 0
df_sa['Secondary Cells (SCell)'] = df_sa['Secondary Cells (SCell)'].apply(lambda x: max(0, x))

# 4. 转换数据格式 (Melt) 以便绘图
plot_data = df_sa[['Primary Cell (PCell)', 'Secondary Cells (SCell)']].melt(
    var_name='Component', 
    value_name='Throughput (Mbps)'
)

# 5. 绘图
plt.figure(figsize=(10, 7))

# 定义颜色 (蓝/橙)
palette = {'Primary Cell (PCell)': '#1f77b4', 'Secondary Cells (SCell)': '#ff7f0e'}

# 【关键点】 showfliers=False 用于去除离群值
sns.boxplot(
    x='Component', 
    y='Throughput (Mbps)', 
    data=plot_data, 
    palette=palette, 
    width=0.5, 
    showfliers=False
)

plt.title('Throughput Contribution: Primary vs Secondary Cells (SA Mode)')
plt.ylabel('Physical Throughput (Mbps)')
plt.xlabel('') # 移除 X 轴标签
plt.grid(True, linestyle='--', alpha=0.5)

# 保存并显示
plt.savefig('pcell_vs_scell_boxplot.png', dpi=300)
plt.show()