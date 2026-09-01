import json
import re
import argparse
import os
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Extract Hard Samples based on Residual Magnitude")
    parser.add_argument("--input_file", type=str, required=True, help="Path to input .jsonl file (train or val)")
    parser.add_argument("--output_file", type=str, default=None, help="Path to save the extracted hard samples")
    parser.add_argument("--top_percent", type=float, default=10.0, help="Top N percent of samples to extract (e.g., 10 for top 10%)")
    parser.add_argument("--min_error", type=float, default=0.0, help="Optional: Minimum absolute error threshold (e.g., 50 Mbps)")
    return parser.parse_args()

def extract_residual_from_message(messages):
    """
    从 messages 中提取 assistant 的回复（即残差 ground truth）。
    支持处理纯数字字符串，也支持带有 'Final Residual:' 的文本。
    """
    for msg in reversed(messages):
        if msg['role'] == 'assistant':
            content = msg['content']
            # 1. 尝试直接提取数字
            try:
                # 移除可能存在的星号或逗号
                clean_content = content.replace('*', '').replace(',', '')
                # 正则查找最后一个浮点数 (适应 "-25.4" 或 "text... -25.4")
                matches = re.findall(r"[-+]?\d*\.\d+|\d+", clean_content)
                if matches:
                    return float(matches[-1])
            except:
                continue
    return 0.0

def main():
    args = parse_args()
    
    input_path = Path(args.input_file)
    if not args.output_file:
        stem = input_path.stem
        args.output_file = input_path.parent / f"{stem}_hard_top{int(args.top_percent)}.jsonl"
    
    print(f"Reading from: {input_path}")
    
    samples = []
    residuals = []
    
    # 1. 读取并解析数据
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        if not line.strip(): continue
        entry = json.loads(line)
        
        # 提取残差 (Ground Truth)
        res_val = extract_residual_from_message(entry['messages'])
        
        # 计算绝对误差 (Magnitude of Residual)
        abs_error = abs(res_val)
        
        # 存储原始数据和误差，方便排序
        samples.append({
            "original_entry": entry,
            "residual": res_val,
            "abs_error": abs_error
        })
        residuals.append(abs_error)

    # 2. 统计分析
    residuals_np = np.array(residuals)
    print(f"\n--- Statistics for {input_path.name} ---")
    print(f"Total Samples: {len(samples)}")
    print(f"Max Error:     {np.max(residuals_np):.4f}")
    print(f"Avg Error:     {np.mean(residuals_np):.4f}")
    print(f"Median Error:  {np.median(residuals_np):.4f}")
    
    # 3. 确定阈值
    # 计算 Top N% 的分位数值
    threshold = np.percentile(residuals_np, 100 - args.top_percent)
    
    # 如果设置了最小误差门槛，取两者较大值
    final_threshold = max(threshold, args.min_error)
    
    print(f"\n--- Extraction Criteria ---")
    print(f"Top {args.top_percent}% Threshold: >= {threshold:.4f}")
    print(f"Final Cutoff Threshold:      >= {final_threshold:.4f}")
    
    # 4. 筛选并保存
    hard_samples = [s for s in samples if s['abs_error'] >= final_threshold]
    
    # 按误差从大到小排序 (最有价值的放在前面)
    hard_samples.sort(key=lambda x: x['abs_error'], reverse=True)
    
    print(f"\nExtracted {len(hard_samples)} samples ({len(hard_samples)/len(samples)*100:.1f}% of total).")
    print(f"Saving to: {args.output_file}")
    
    with open(args.output_file, 'w', encoding='utf-8') as f:
        for item in hard_samples:
            # 可以在这里给 output 加个标记，比如 log 一下它的 error
            # 但为了保持格式一致性，我们直接存原始 entry
            f.write(json.dumps(item['original_entry']) + '\n')

    # 5. 可视化 (可选: 帮你看看误差分布)
    try:
        plt.figure(figsize=(10, 5))
        plt.hist(residuals, bins=50, color='blue', alpha=0.7, log=True)
        plt.axvline(final_threshold, color='red', linestyle='dashed', linewidth=1, label=f'Threshold: {final_threshold:.2f}')
        plt.title('Residual Magnitude Distribution (Log Scale)')
        plt.xlabel('Absolute Residual (Mbps)')
        plt.ylabel('Count (Log)')
        plt.legend()
        plt.savefig(input_path.parent / f"{input_path.stem}_error_dist.png")
        print(f"Distribution plot saved to {input_path.parent}")
    except Exception as e:
        print("Skipped plotting (matplotlib error or environment issue).")

    # 6. 打印前 3 个最难样本的残差，让你心里有数
    print("\n--- Preview: Top 3 Hardest Samples (Residuals) ---")
    for i in range(min(3, len(hard_samples))):
        print(f"Rank {i+1}: {hard_samples[i]['residual']} Mbps")

if __name__ == "__main__":
    main()