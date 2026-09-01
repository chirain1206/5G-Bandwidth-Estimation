import pandas as pd
import glob
import os
import re

def pre_merge_bandwidth_traces():
    # 1. 找到所有 bandwidth traces 文件
    all_csvs = glob.glob("bandwidth_traces_*.csv")
    
    # 用于存储分组： { 'pixel10': ['file1.csv', 'file2.csv'], 'pixel6pro': [...] }
    device_groups = {}
    
    print(f"Found {len(all_csvs)} CSV files.")

    # 2. 根据文件名提取设备名并分组
    # 假设文件名格式: bandwidth_traces_20251230_pixel10.csv
    # 正则逻辑：找到最后一个下划线后、.csv 前的部分
    for csv_file in all_csvs:
        match = re.search(r'_([^_]+)\.csv$', csv_file)
        if match:
            device_name = match.group(1)
            if device_name not in device_groups:
                device_groups[device_name] = []
            device_groups[device_name].append(csv_file)
        else:
            print(f"Skipping format mismatch: {csv_file}")

    # 3. 对每个设备进行合并
    for device, files in device_groups.items():
        print(f"\nProcessing device: {device} (Merging {len(files)} files)...")
        
        df_list = []
        for f in files:
            try:
                # 读取并添加来源文件名列(可选，方便debug)
                df = pd.read_csv(f)
                df_list.append(df)
            except Exception as e:
                print(f"Error reading {f}: {e}")
        
        if not df_list:
            continue
            
        # 合并
        merged_df = pd.concat(df_list, ignore_index=True)
        
        # 【关键步骤】按时间戳排序
        # 假设 CSV 里有一列叫 'Timestamp' (Unix ms) 或者 'Date'
        # 如果是 bandwidth_traces，通常第一列是 Timestamp
        if 'Timestamp' in merged_df.columns:
            merged_df = merged_df.sort_values('Timestamp')
        else:
            # 如果没有 Timestamp 表头，假设第一列是时间
            merged_df = merged_df.sort_values(merged_df.columns[0])

        # 4. 保存为新的“总表”
        output_filename = f"bandwidth_traces_MERGED_{device}.csv"
        merged_df.to_csv(output_filename, index=False)
        print(f"Saved merged file: {output_filename} ({len(merged_df)} rows)")

if __name__ == "__main__":
    pre_merge_bandwidth_traces()