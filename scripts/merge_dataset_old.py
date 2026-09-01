import pandas as pd
import json
import glob
import os

# ==========================================
# 1. 全局配置 (Configuration)
# ==========================================

# 文件名匹配模式
# 脚本会自动提取 CSV 文件名末尾的 "_设备名" (例如 _pixel10) 去匹配对应的 JSON
INPUT_CSV_PATTERN = 'bandwidth_traces_MERGED_*.csv'
INPUT_JSON_PATTERN = '*.UE1.json'
OUTPUT_FILENAME = 'coalesced_bandwidth_traces.csv'

# 最大支持提取的辅小区 (SCell) 数量
MAX_SCELLS = 8

# 【简单字段映射表】
# 格式: "JSON内部路径" : "输出CSV列名"
# 说明: 复杂的逻辑（如求和、列表遍历）在代码中处理，简单的直接在这里配置
SIMPLE_FIELD_MAPPING = {
    # --- 时间与位置 ---
    'Timestamp': 'timestamp_NSG',  # 使用系统时间戳与 App 对齐
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
    'LTE.PrimaryCell.PCell_PCI':        'LTE_PCell_PCI_NSG',
    'LTE.PrimaryCell.PCell_Band':       'LTE_PCell_Band_NSG',
    'LTE.PrimaryCell.PCell_Throughput':       'LTE_PCell_PHYS_Throughput_NSG',

    # --- Physical Layer (NSA Anchor) ---
}

# ==========================================
# 2. 核心逻辑工具函数
# ==========================================

def get_value_by_path(item, path):
    """根据 'Key1.Key2' 路径安全获取值，不存在则返回 None"""
    keys = path.split('.')
    val = item
    try:
        for k in keys:
            if val is None: return None
            val = val.get(k)
        return val
    except:
        return None

def get_device_suffix(filename):
    """
    从 CSV 文件名提取设备后缀以进行精确匹配
    例如: 'bandwidth_traces_20251223_pixel10.csv' -> 返回 'pixel10'
    逻辑: 取文件名(不含扩展名)最后一个下划线后的部分
    """
    base = os.path.basename(filename)
    root, _ = os.path.splitext(base)
    parts = root.split('_')
    if len(parts) > 1:
        return parts[-1]
    return ""

def extract_nsg_data(json_files, target_device_suffix):
    """
    提取 NSG 数据，仅处理文件名包含 target_device_suffix 的 JSON 文件
    """
    extracted_rows = []
    
    # 1. 过滤：只保留属于该设备的 JSON Logs
    matched_files = [f for f in json_files if target_device_suffix.lower() in f.lower()]
    
    if not matched_files:
        print(f"    [Warning] No JSON file found for device tag: '{target_device_suffix}'")
        return pd.DataFrame()

    print(f"    -> Parsing {len(matched_files)} JSON logs for device '{target_device_suffix}'...")

    for j_file in matched_files:
        try:
            with open(j_file, 'r') as f:
                data = json.load(f)
                
            for item in data.get('data', []):
                row = {}

                # --- A. 执行简单映射 ---
                for json_path, csv_col in SIMPLE_FIELD_MAPPING.items():
                    row[csv_col] = get_value_by_path(item, json_path)

                # --- B. 智能判断网络模式 (SA / NSA / LTE) ---
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

                # --- C. 计算总 RLC Throughput (核心 Target) ---
                # 公式: Total = NR_RLC + LTE_RLC
                # 即使 NSA 模式下 PDCP 为 0，RLC 依然能准确反映有效吞吐量
                nr_rlc = 0.0
                lte_rlc = 0.0
                nr_phys = 0.0
                lte_phys = 0.0
                
                # 1. 取 NR RLC和PHYS
                val_nr = get_value_by_path(item, 'NR5G.Data_Performance.RLC_Throughput_DL')
                if val_nr: nr_rlc = float(val_nr)
                val_nr = get_value_by_path(item, 'NR5G.Data_Performance.Physical_Throughput_DL')
                if val_nr: nr_phys = float(val_nr)

                # 2. 取 LTE RLC和PHYS (兼容层级差异)
                val_lte = get_value_by_path(item, 'LTE_Data_KPI.RLC_Throughput_DL')
                if not val_lte:
                    val_lte = get_value_by_path(item, 'LTE.LTE_Data_KPI.RLC_Throughput_DL')
                if val_lte: lte_rlc = float(val_lte)
                val_lte = get_value_by_path(item, 'LTE_Data_KPI.Agg_Throughput_DL')
                if not val_lte:
                    val_lte = get_value_by_path(item, 'LTE.LTE_Data_KPI.Agg_Throughput_DL')
                if val_lte: lte_phys = float(val_lte)
                
                # 3. 求和
                row['RLC_Throughput_DL_Total_NSG'] = nr_rlc + lte_rlc
                row['PHYS_Throughput_DL_Total_NSG'] = nr_phys + lte_phys
                
                # (可选) 保留分量用于调试
                row['NR_RLC_DL_NSG'] = nr_rlc
                row['LTE_RLC_DL_NSG'] = lte_rlc
                row['NR_PHYS_DL_NSG'] = nr_phys
                row['LTE_PHYS_DL_NSG'] = lte_phys

                # --- D. 提取辅小区 (SCells) - 混合逻辑 ---
                scells_found = []

                # D1. 提取 NR SCells (SA模式 - 列表结构)
                nr_table = get_value_by_path(item, 'NR5G.NRCellTable_Serving')
                #cur_scell_num = 0
                if isinstance(nr_table, list):
                    for cell in nr_table:
                        # ServingType != 0 表示它是 SCell
                        if cell.get('ServingType', 0) != 0:
                            #phys_throughput = get_value_by_path(item, 'NR5G.SecondaryCell_Radio_DL.SCell_Physical_Throughput_DL')[cur_scell_num]
                            #print(phys_throughput)
                            scells_found.append({
                                'Type': 'NR',
                                'RSRP': cell.get('RSRP'),
                                'RSRQ': cell.get('RSRQ'),
                                'SINR': cell.get('SINR'),
				#'PHYS_Throughput': phys_throughput
                            })
                            #cur_scell_num = cur_scell_num + 1

                # D2. 提取 LTE SCells (NSA模式 - 对象结构)
                # 扫描 item 根目录 和 item['LTE'] 目录
                search_roots = [item]
                if 'LTE' in item: search_roots.append(item['LTE'])
                
                for i in range(1, MAX_SCELLS+1): # 扫描 SecondaryCell_1 到 8
                    key = f"SecondaryCell_{i}_Radio"
                    found_in_root = False
                    for root in search_roots:
                        if key in root:
                            d = root[key]
                            scells_found.append({
                                'Type': 'LTE',
                                'RSRP': d.get(f'SCell{i}_RSRP'),
                                'RSRQ': d.get(f'SCell{i}_RSRQ'),
                                'SINR': d.get(f'SCell{i}_SINR'),
				#'PHYS_Throughput': d.get(f'SCell{i}_Throughput')
                            })
                            found_in_root = True
                            break
                    # 优化：通常 SCell 是连续的，找不到1就不太可能有2，但为了稳健继续循环
                
                # D3. 将找到的 SCell 填入列
                for i in range(MAX_SCELLS):
                    prefix = f"SCell{i+1}"
                    if i < len(scells_found):
                        sc = scells_found[i]
                        row[f'{prefix}_Type_NSG'] = sc['Type']
                        row[f'{prefix}_RSRP_NSG'] = sc['RSRP']
                        row[f'{prefix}_RSRQ_NSG'] = sc['RSRQ']
                        row[f'{prefix}_SINR_NSG'] = sc['SINR']
                        #row[f'{prefix}_PHYS_Throughput_NSG'] = sc['PHYS_Throughput']
                    else:
                        row[f'{prefix}_Type_NSG'] = None
                        row[f'{prefix}_RSRP_NSG'] = None
                        row[f'{prefix}_RSRQ_NSG'] = None
                        row[f'{prefix}_SINR_NSG'] = None
                        #row[f'{prefix}_PHYS_Throughput_NSG'] = None
                
                extracted_rows.append(row)

        except Exception as e:
            print(f"    [Error] Failed to process {j_file}: {e}")

    return pd.DataFrame(extracted_rows)

# ==========================================
# 3. 主合并流程
# ==========================================

def batch_process_and_merge(csv_pattern, output_file_path):
    # 获取所有可用的 JSON 文件列表
    all_json_files = glob.glob(INPUT_JSON_PATTERN)
    if not all_json_files:
        print(f"Error: No JSON files found matching {INPUT_JSON_PATTERN}")
        return
        
    # 获取所有 CSV 文件
    csv_files = glob.glob(csv_pattern)
    merged_frames = []
    
    print(f"Found {len(csv_files)} CSV files. Starting device-specific merge...")
    
    for c_file in csv_files:
        # 1. 识别设备后缀 (e.g., pixel10)
        device_suffix = get_device_suffix(c_file)
        if not device_suffix:
            print(f"Skipping {c_file}: Could not determine device suffix.")
            continue
            
        print(f"\nProcessing CSV: {c_file} (Device: {device_suffix})")
        
        # 2. 提取该设备对应的 NSG 数据
        df_nsg = extract_nsg_data(all_json_files, device_suffix)
        
        if df_nsg.empty:
            print(f"  -> Skipping: No matching JSON data found for device '{device_suffix}'.")
            continue

        df_nsg['Speed_NSG'] = df_nsg['Speed_NSG'] / 3.6
        df_nsg = df_nsg.rename(columns={'Speed_NSG': 'Speed_m_s_NSG'})
            
        # 3. 准备时间轴合并
        df_nsg['Timestamp_dt'] = pd.to_datetime(df_nsg['timestamp_NSG'])
        df_nsg = df_nsg.sort_values('Timestamp_dt')
        
        # 获取 NSG 数据的时区 (例如 -05:00)
        nsg_tz = df_nsg['Timestamp_dt'].iloc[0].tzinfo

        KEEP_COLUMNS = ['Timestamp', 'Probe Elapsed Time(ms)']
        try:
            df_app = pd.read_csv(c_file)

            # 检查列是否存在，防止报错
            available_cols = [c for c in KEEP_COLUMNS if c in df_app.columns]
            if len(available_cols) < len(KEEP_COLUMNS):
                missing = set(KEEP_COLUMNS) - set(available_cols)
                print(f"  Warning: Missing columns in {c_file}: {missing}")
            df_app = df_app[available_cols]
            
            # 解析 App 时间戳 (格式: 2025.12.08_03.13.57.736)
            df_app['Timestamp_dt'] = pd.to_datetime(df_app['Timestamp'], format='%Y.%m.%d_%H.%M.%S.%f', errors='coerce')
            df_app = df_app.dropna(subset=['Timestamp_dt'])
            
            # 时区对齐：将 App 时间强制转换为与 NSG 相同的时区
            if nsg_tz:
                if df_app['Timestamp_dt'].dt.tz is None:
                    df_app['Timestamp_dt'] = df_app['Timestamp_dt'].dt.tz_localize(nsg_tz)
                else:
                    df_app['Timestamp_dt'] = df_app['Timestamp_dt'].dt.tz_convert(nsg_tz)
            
            df_app = df_app.sort_values('Timestamp_dt')

            # 4. 执行合并 (Merge AsOf) - 容差 1秒
            merged = pd.merge_asof(
                df_app, df_nsg,
                on='Timestamp_dt',
                direction='nearest',
                tolerance=pd.Timedelta('1s')
            )
            
            # 过滤掉未匹配到 NSG 数据的行
            merged = merged.dropna(subset=['timestamp_NSG'])
            
            # 添加设备标识列
            merged['Device_ID'] = device_suffix
            
            if len(merged) > 0:
                merged_frames.append(merged)
                print(f"  -> MATCH SUCCESS: {len(merged)} rows matched.")
            else:
                print("  -> No time-matches found (check timestamps or timezones).")
            
        except Exception as e:
            print(f"  ! Error processing {c_file}: {e}")

    # 5. 保存最终结果
    if merged_frames:
        final_df = pd.concat(merged_frames, ignore_index=True)
        
        # 清理中间辅助列
        if 'Timestamp_dt' in final_df.columns:
            final_df = final_df.drop(columns=['Timestamp_dt'])
            
        # 【列排序优化】: 将重要列提前
        cols = list(final_df.columns)
        # 1. Device_ID 放最前
        if 'Device_ID' in cols:
            cols.insert(0, cols.pop(cols.index('Device_ID')))
        # 2. Network_Mode 放第二
        if 'Network_Mode_NSG' in cols:
             cols.insert(1, cols.pop(cols.index('Network_Mode_NSG')))
        # 3. Target (RLC Total和PHYS total) 放 Timestamp 旁边
        if 'PHYS_Throughput_DL_Total_NSG' in cols and 'Timestamp' in cols:
            cols.insert(cols.index('Timestamp') + 1, cols.pop(cols.index('PHYS_Throughput_DL_Total_NSG')))
        if 'RLC_Throughput_DL_Total_NSG' in cols and 'Timestamp' in cols:
            cols.insert(cols.index('Timestamp') + 1, cols.pop(cols.index('RLC_Throughput_DL_Total_NSG')))

            
        final_df = final_df[cols]
        final_df.to_csv(output_file_path, index=False)
        print(f"\n Success! Coalesced data saved to: {output_file_path}")
    else:
        print("\n Warning: No data matched across all files.")

if __name__ == "__main__":
    batch_process_and_merge(INPUT_CSV_PATTERN, OUTPUT_FILENAME)