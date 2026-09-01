import pandas as pd
import json
import glob
import os
import re

# ==========================================
# 1. 全局配置
# ==========================================
INPUT_CSV_PATTERN = 'bandwidth_traces_MERGED_*.csv'
INPUT_JSON_PATTERN = '*.UE1.json'
OUTPUT_FILENAME = 'coalesced_bandwidth_traces.csv'
MAX_SCELLS = 8

# 简单映射 (保留最基础的，复杂的在代码里手动处理)
SIMPLE_FIELD_MAPPING = {
    # --- 时间与位置 ---
    'Timestamp': 'Timestamp_NSG',  # 使用系统时间戳与 App 对齐
    'Location.Latitude': 'Latitude_NSG',
    'Location.Longitude': 'Longitude_NSG',
    'Location.Speed': 'Speed_NSG',
    
    # --- 5G SA 主小区 (PCell) ---
    'NR5G.PrimaryCell_Radio_DL.PCell_SS_RSRP': 'NR_PCell_RSRP_NSG',
    'NR5G.PrimaryCell_Radio_DL.PCell_SS_RSRQ': 'NR_PCell_RSRQ_NSG',
    'NR5G.PrimaryCell_Radio_DL.PCell_SS_SINR': 'NR_PCell_SINR_NSG',
    'NR5G.PrimaryCell_Radio_DL.PCell_CQI_DL':  'NR_PCell_CQI_NSG',
    'NR5G.PrimaryCell_Radio_DL.PCell_Physical_Throughput_DL':  'NR_PCell_PHYS_Throughput_NSG',
    'NR5G.PrimaryCell.PCell_PCI':               'NR_PCell_PCI_NSG',
    'NR5G.PrimaryCell.PCell_Band':              'NR_PCell_Band_NSG',
    
    # --- LTE 主小区 (NSA Anchor) ---
    'LTE.PrimaryCell_Radio.PCell_RSRP': 'LTE_PCell_RSRP_NSG',
    'LTE.PrimaryCell_Radio.PCell_RSRQ': 'LTE_PCell_RSRQ_NSG',
    'LTE.PrimaryCell_Radio.PCell_SINR': 'LTE_PCell_SINR_NSG',
    'LTE.PrimaryCell.PCell_CQI_CW0':    'LTE_PCell_CQI_NSG',
    'LTE.PrimaryCell.PCell_PCI':        'LTE_PCell_PCI_NSG',
    'LTE.PrimaryCell.PCell_Band':       'LTE_PCell_Band_NSG',
    'LTE.PrimaryCell.PCell_Throughput':       'LTE_PCell_PHYS_Throughput_NSG',

    # --- Physical Layer (NSA Anchor) ---
}

# ==========================================
# 2. 辅助函数
# ==========================================

def get_value_by_path(data, path):
    """根据点分隔路径 (e.g. 'Location.Speed') 获取值"""
    keys = path.split('.')
    val = data
    try:
        for k in keys:
            val = val.get(k)
            if val is None: return None
        return val
    except:
        return None

def parse_filename_info(filename):
    """
    从 JSON 文件名中提取: (mode, timestamp, device_id)
    格式: driving_202512301634_pixel10.UE1.json
    """
    base = os.path.basename(filename)
    match = re.search(r'([a-zA-Z]+)_(\d+)_([^_.]+)', base)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return "unknown", "0000", "unknown"

def load_all_csvs():
    """
    加载所有 MERGED CSV，按 Device_ID 存入字典。
    """
    csv_files = glob.glob(INPUT_CSV_PATTERN)
    csv_map = {}
    
    print("Loading CSV lookup tables...")
    for f in csv_files:
        # 提取设备名 (假设文件名: bandwidth_traces_MERGED_pixel10.csv)
        match = re.search(r'MERGED_([^_.]+)\.csv', f)
        if match:
            device = match.group(1)
            print(f"  -> Loading {f} for device: {device}")
            try:
                df = pd.read_csv(f)
                
                # --- 核心修改：匹配你的特定时间格式 ---
                # 格式: 2025.12.26_15.09.21.306
                # 对应 format: %Y.%m.%d_%H.%M.%S.%f
                
                # 1. 解析字符串时间为 datetime 对象
                df['Timestamp_dt'] = pd.to_datetime(
                    df['Timestamp'], 
                    format='%Y.%m.%d_%H.%M.%S.%f', 
                    errors='coerce'  # 解析失败设为 NaT
                )
                
                # 2. 检查解析是否成功
                if df['Timestamp_dt'].isna().all():
                    print(f"    [Error] Timestamp parsing failed for ALL rows in {f}.")
                    print(f"    First row value: {df['Timestamp'].iloc[0]}")
                    continue

                # 3. 过滤无效行并排序
                df = df.dropna(subset=['Timestamp_dt'])
                df = df.sort_values('Timestamp_dt')
                
                # 4. (关键) 将解析好的时间转回 Unix 毫秒时间戳 (int64)
                # 这样后续代码中所有基于数值的逻辑都不用改
                # astype(np.int64) 得到纳秒，除以 10^6 得到毫秒
                #df['Timestamp'] = df['Timestamp_dt'].astype('int64') // 10**6 
                
                # 5. 只保留需要的列
                keep_cols = ['Timestamp', 'Timestamp_dt', 'Probe Elapsed Time(ms)', 'Downlink Avg(Mbps)']
                available = [c for c in keep_cols if c in df.columns]
                
                csv_map[device] = df[available]
                
            except Exception as e:
                print(f"Error reading CSV {f}: {e}")
                
    return csv_map

# ==========================================
# 3. 核心处理逻辑 (集成了你的 SCell 代码)
# ==========================================

def process_single_json_session(json_file, csv_lookup_map):
    mode, file_ts, device = parse_filename_info(json_file)
    session_id = f"{mode}_{file_ts}_{device}"
    
    # 1. 检查 Device 是否有对应的 CSV
    if device not in csv_lookup_map:
        # print(f"Skipping {json_file}: No CSV data for device '{device}'")
        return None

    # 2. 读取 JSON
    try:
        with open(json_file, 'r') as f:
            raw_json = json.load(f)
            # 兼容不同 NSG 版本：有的包在 'data' 里，有的直接是 list
            data_list = raw_json.get('data', []) if isinstance(raw_json, dict) else raw_json
    except Exception as e:
        print(f"Error reading JSON {json_file}: {e}")
        return None

    extracted_rows = []
    
    # 3. 遍历每一行 Log (深度解析)
    for item in data_list:
        row = {}
        
        # --- A. 基础映射 ---
        for json_path, csv_col in SIMPLE_FIELD_MAPPING.items():
            row[csv_col] = get_value_by_path(item, json_path)

        # --- B. 智能判断网络模式 ---
        lte_pci = get_value_by_path(item, 'LTE.PrimaryCell.PCell_PCI')
        nr_pci = get_value_by_path(item, 'NR5G.PrimaryCell.PCell_PCI')
        
        if nr_pci is not None and lte_pci is None:
            row['Network_Mode_NSG'] = 'SA'
        elif lte_pci is not None and get_value_by_path(item, 'NR5G') is not None:
            row['Network_Mode_NSG'] = 'NSA'
        elif lte_pci is not None:
            row['Network_Mode_NSG'] = 'LTE'
        else:
            row['Network_Mode_NSG'] = 'Unknown'

        # --- C. 计算总吞吐量 (Target) ---
        nr_rlc, lte_rlc = 0.0, 0.0
        nr_phys, lte_phys = 0.0, 0.0
        
        # NR
        val = get_value_by_path(item, 'NR5G.Data_Performance.RLC_Throughput_DL')
        if val: nr_rlc = float(val)
        val = get_value_by_path(item, 'NR5G.Data_Performance.Physical_Throughput_DL')
        if val: nr_phys = float(val)
        
        # LTE (兼容不同层级)
        val = get_value_by_path(item, 'LTE_Data_KPI.RLC_Throughput_DL')
        if not val: val = get_value_by_path(item, 'LTE.LTE_Data_KPI.RLC_Throughput_DL')
        if val: lte_rlc = float(val)
        
        val = get_value_by_path(item, 'LTE_Data_KPI.Agg_Throughput_DL')
        if not val: val = get_value_by_path(item, 'LTE.LTE_Data_KPI.Agg_Throughput_DL')
        if val: lte_phys = float(val)

        row['RLC_Throughput_DL_Total_NSG'] = nr_rlc + lte_rlc
        row['PHYS_Throughput_DL_Total_NSG'] = nr_phys + lte_phys
        
        # 保留分量
        row['NR_RLC_DL_NSG'] = nr_rlc
        row['LTE_RLC_DL_NSG'] = lte_rlc
        row['NR_PHYS_DL_NSG'] = nr_phys
        row['LTE_PHYS_DL_NSG'] = lte_phys

        # --- D. 提取辅小区 (SCells) ---
        scells_found = []
        
        # D1. NR SCells (SA 模式列表结构)
        nr_table = get_value_by_path(item, 'NR5G.NRCellTable_Serving')
        if isinstance(nr_table, list):
            for cell in nr_table:
                if cell.get('ServingType', 0) != 0: # SCell
                    scells_found.append({
                        'Type': 'NR',
                        'RSRP': cell.get('RSRP'),
                        'RSRQ': cell.get('RSRQ'),
                        'SINR': cell.get('SINR')
                    })

        # D2. LTE SCells (NSA 模式对象结构)
        search_roots = [item]
        if 'LTE' in item: search_roots.append(item['LTE'])
        
        for i in range(1, MAX_SCELLS + 1):
            key = f"SecondaryCell_{i}_Radio"
            for root in search_roots:
                if key in root:
                    d = root[key]
                    scells_found.append({
                        'Type': 'LTE',
                        'RSRP': d.get(f'SCell{i}_RSRP'),
                        'RSRQ': d.get(f'SCell{i}_RSRQ'),
                        'SINR': d.get(f'SCell{i}_SINR')
                    })
                    break # 找到即跳出 root 循环
        
        # D3. 填入列
        for i in range(MAX_SCELLS):
            prefix = f"SCell{i+1}"
            if i < len(scells_found):
                sc = scells_found[i]
                row[f'{prefix}_Type_NSG'] = sc['Type']
                row[f'{prefix}_RSRP_NSG'] = sc['RSRP']
                row[f'{prefix}_RSRQ_NSG'] = sc['RSRQ']
                row[f'{prefix}_SINR_NSG'] = sc['SINR']
            else:
                row[f'{prefix}_Type_NSG'] = None
                row[f'{prefix}_RSRP_NSG'] = None
                row[f'{prefix}_RSRQ_NSG'] = None
                row[f'{prefix}_SINR_NSG'] = None
        
        # --- E. 添加 Session 标记 (关键) ---
        row['Mobility_Mode'] = mode
        row['Source_File_ID'] = session_id
        
        extracted_rows.append(row)

    # 4. 转换为 DataFrame
    nsg_df = pd.DataFrame(extracted_rows)
    if nsg_df.empty or 'Timestamp_NSG' not in nsg_df.columns:
        return None

    # 单位转换与排序
    #nsg_df['Timestamp_dt'] = pd.to_datetime(nsg_df['Timestamp_NSG'], unit='ms')
    nsg_df['Timestamp_dt'] = pd.to_datetime(nsg_df['Timestamp_NSG'], errors='coerce')
    if nsg_df['Timestamp_dt'].dt.tz is not None:
        nsg_df['Timestamp_dt'] = nsg_df['Timestamp_dt'].dt.tz_localize(None)
    
    nsg_df = nsg_df.sort_values('Timestamp_dt')
    if 'Speed_NSG' in nsg_df.columns:
        nsg_df['Speed_NSG'] = nsg_df['Speed_NSG'] / 3.6 # km/h -> m/s

    # 5. 与 CSV Merge (切片匹配)
    start_time = nsg_df['Timestamp_dt'].min()
    end_time = nsg_df['Timestamp_dt'].max()
    buffer = pd.Timedelta('2s') # 稍微给大一点 buffer 防止边缘数据丢失
    
    full_csv = csv_lookup_map[device]
    mask = (full_csv['Timestamp_dt'] >= (start_time - buffer)) & \
           (full_csv['Timestamp_dt'] <= (end_time + buffer))
    target_app_df = full_csv[mask].copy()
    
    if target_app_df.empty:
        # print(f"  ! Warning: {session_id} has NO matching CSV data in time range.")
        return None

    merged = pd.merge_asof(
        target_app_df,
        nsg_df,
        on='Timestamp_dt',
        direction='nearest',
        tolerance=pd.Timedelta('500ms')
    )
    
    # 过滤未匹配行
    merged = merged.dropna(subset=['Timestamp_NSG'])
    merged['Device_ID'] = device
    
    if not merged.empty:
        sample = merged.iloc[0]
        print(f"  [Debug Time Alignment]")
        print(f"  CSV Time (Key):  {sample['Timestamp_dt']}")
        print(f"  CSV Original:    {sample['Timestamp']}")
        print(f"  NSG Time (Match):{sample['Timestamp_NSG']}")
        # 计算误差
        # 注意: JSON原始时间是带时区的字符串，比较前要小心
        # 这里只做简单的肉眼观察即可，不需要写复杂的diff代码引发报错
    
    print(f"  -> Merged {session_id}: {len(merged)} rows. (Mode: {mode})")
    return merged

# ==========================================
# 4. 主流程
# ==========================================
def main():
    csv_map = load_all_csvs()
    if not csv_map:
        print("No CSV files loaded.")
        return

    json_files = glob.glob(INPUT_JSON_PATTERN)
    print(f"\nProcessing {len(json_files)} JSON sessions...")
    
    all_sessions = []
    for jf in json_files:
        df = process_single_json_session(jf, csv_map)
        if df is not None:
            all_sessions.append(df)

    if all_sessions:
        final_df = pd.concat(all_sessions, ignore_index=True)
        
        # 清理列
        #cols_to_drop = ['Timestamp_dt']
        cols_to_drop = []
        final_df = final_df.drop(columns=[c for c in cols_to_drop if c in final_df.columns], errors='ignore')
        final_df = final_df.rename(columns={'Downlink Avg(Mbps)': 'APP_Throughput_DL_Total'})
        
        # 优化列排序
        cols = list(final_df.columns)
        priorities = ['Device_ID', 'Mobility_Mode', 'Source_File_ID', 'Timestamp', 'Timestamp_dt', 'Timestamp_NSG', 
                      'Network_Mode_NSG', 'RLC_Throughput_DL_Total_NSG', 'PHYS_Throughput_DL_Total_NSG', 'APP_Throughput_DL_Total']
        for p in reversed(priorities):
            if p in cols: cols.insert(0, cols.pop(cols.index(p)))
        final_df = final_df[cols]

        final_df.to_csv(OUTPUT_FILENAME, index=False)
        print(f"\nSuccess! Saved to {OUTPUT_FILENAME} ({len(final_df)} rows)")
    else:
        print("No data produced.")

if __name__ == "__main__":
    main()