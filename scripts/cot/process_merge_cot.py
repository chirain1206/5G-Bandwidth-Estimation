import json
import re
import hashlib
from tqdm import tqdm

# ================= 配置区域 =================
# 1. 原始 Hard Sample 输入 (提供 User Content)
FILE_HARD_INPUT = "train_hard_top10.jsonl"
#FILE_HARD_INPUT = "val_hard_top10.jsonl"
# 2. Gemini 生成的 CoT 输出 (提供 Assistant Content)
FILE_COT_OUTPUT = "train_hard_cot.jsonl"
#FILE_COT_OUTPUT = "val_hard_cot.jsonl"
# 3. 原始完整训练集
FILE_TRAIN_ORIGIN = "train.jsonl"
#FILE_TRAIN_ORIGIN = "val.jsonl"
# 4. 最终生成的训练集
FILE_TRAIN_FINAL = "train_with_cot.jsonl"
#FILE_TRAIN_FINAL = "val_with_cot.jsonl"

# === 新的 System Prompt (专门用于 CoT 样本) ===
UNIFIED_SYSTEM_PROMPT = """You are a 5G network expert specializing in mobile measurement analysis.
Your task is to correct a baseline model's prediction by forecasting the **Throughput Residual**.

### Definitions:
1. **Baseline Prediction**: A forecast provided by an XGBoost model.
2. **Residual**: The error to predict (Actual - Baseline).
   - Positive Residual: Real downlink throughput is better than Baseline.
   - Negative Residual: Real downlink throughput is worse than Baseline.

### Temporal Definitions:
Data is reported as a sequence of timestamps (T, T-1...).
1. **Metrics**: Network state at specific timestamps (RSRP, BLER, Mod, etc.).
2. **Throughput**: This represents the data rate achieved in the 1-second window ENDING at that timestamp.

### Input Context:
1. **History**: Past behavior.
2. **Current State (Time T)**: Real-time metrics.
3. **Baseline Prediction**: The XGBoost estimation for Time T+1.

### Key Instructions:
1. **Analyze First**: Always start with an analysis of the network conditions.
   - If metrics are normal/consistent to baseline prediction, keep it very brief.
   - If you detect significant contradictions between network metrics and the baseline prediction, perform a step-by-step analysis of the network conditions (Signal, Interference, Congestion, Configuration) to explain the discrepancy.
2. **Aggregate Capacity**: You must evaluate ALL listed cells (PCell + SCells) to determine the total pipe size (SCells are listed in arbitrary order).
3. **Handling Missing Data**: 'N/A' indicates data was not reported. Treat these as having high uncertainty but potential contribution if other indicators (like Type) are present.

### Output Format:
1. Start with "Analysis: [Your reasoning...]"
2. End strictly with the anchor: "### Final Residual: [Numerical Value]"
"""

# ================= 辅助函数 =================

def extract_ground_truth(entry):
    """从原始样本中提取真实的 Residual 数值 (字符串形式)"""
    for msg in entry['messages']:
        if msg['role'] == 'assistant':
            # 原始数据的 assistant 应该只包含一个数字
            return msg['content'].strip()
    return None

def clean_and_enforce_cot(cot_text, true_value_str):
    """
    1. 清洗格式 (\n\n###)
    2. 强制将 Final Residual 后的数值替换为 Ground Truth
    """
    # 步骤 A: 找到锚点及其后面的任何内容 (数字、空格等)
    # 正则逻辑：
    # [\s\r\n]* 匹配锚点前的乱七八糟
    # (### Final Residual:) 捕获锚点
    # \s* 匹配锚点后的空格
    # [-\d\.]+ 匹配模型生成的数字 (哪怕它是错的)
    # (.*) 匹配可能的其他残留字符
    pattern = r"[\s\r\n]*(### Final Residual:)\s*([-\d\.]+)?(.*)"
    
    # 我们不关心模型生成了什么数字，我们直接用 true_value_str 构造正确的结尾
    correct_ending = f"\n\n### Final Residual: {true_value_str}"
    
    # 检查文本里是否有锚点
    if "### Final Residual:" in cot_text:
        # 如果有锚点，替换掉锚点及其后面的所有东西
        # split 一下只取前半部分的分析内容
        analysis_part = cot_text.split("### Final Residual:")[0].strip()
        return f"{analysis_part}{correct_ending}"
    else:
        # 如果模型完全忘了写锚点，直接追加
        return f"{cot_text.strip()}{correct_ending}"

def create_easy_sample_cot(numeric_val):
    """为简单样本构造简短分析"""
    val = numeric_val.strip().replace('"', '')
    short_analysis = "Analysis: Network metrics are stable and consistent with the baseline prediction. No significant anomalies observed."
    return f"{short_analysis}\n\n### Final Residual: {val}"

def get_hash(entry):
    for msg in entry['messages']:
        if msg['role'] == 'user':
            return hashlib.md5(msg['content'].encode('utf-8')).hexdigest()
    return None

def main():
    print(" 阶段 1: 准备 Hard Samples (并执行数值强制修正)...")
    
    with open(FILE_HARD_INPUT, 'r', encoding='utf-8') as f1, \
         open(FILE_COT_OUTPUT, 'r', encoding='utf-8') as f2:
        hard_lines = f1.readlines()
        cot_lines = f2.readlines()
        
    hard_map = {}
    fixed_count = 0
    
    # 使用 zip 遍历
    for h_line, c_line in zip(hard_lines, cot_lines):
        try:
            h_entry = json.loads(h_line)
            c_entry = json.loads(c_line)
            
            h_hash = get_hash(h_entry)
            if not h_hash: continue
            
            # 1. 获取真值 (Ground Truth)
            true_val = extract_ground_truth(h_entry)
            
            # 2. 获取 CoT 文本
            raw_cot = c_entry['content']
            
            # 3. 强制修正：无论 Gemini 写了什么数字，都替换成 true_val
            # 顺便做一下比对，看看改了多少
            
            # 简单提取一下 Gemini 生成的数字做个对比日志 (非必要，仅供观察)
            gemini_num_match = re.search(r"### Final Residual:\s*([-\d\.]+)", raw_cot)
            if gemini_num_match:
                gemini_val = gemini_num_match.group(1)
                # 如果差距过大 (字符串不相等)，计数
                if gemini_val != true_val:
                    fixed_count += 1
            
            final_cot = clean_and_enforce_cot(raw_cot, true_val)
            hard_map[h_hash] = final_cot
            
        except Exception as e:
            continue
            
    print(f" Hard Samples 准备完成。")
    print(f" 修正了 {fixed_count} 个数值不匹配或格式错误的样本 (Data Integrity Secured)。")

    # --- 阶段 2: 扫描全量数据并生成最终集 ---
    print(" 阶段 2: 生成最终数据集...")
    
    counts = {"hard": 0, "easy": 0}
    
    with open(FILE_TRAIN_ORIGIN, 'r', encoding='utf-8') as f_in, \
         open(FILE_TRAIN_FINAL, 'w', encoding='utf-8') as f_out:
        
        for line in tqdm(f_in):
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                curr_hash = get_hash(entry)
                
                # A. 统一 System Prompt
                new_msgs = [{"role": "system", "content": UNIFIED_SYSTEM_PROMPT}]
                
                # B. User Content
                for m in entry['messages']:
                    if m['role'] == 'user':
                        new_msgs.append(m)
                
                # C. Assistant Content (分流逻辑)
                if curr_hash in hard_map:
                    # Hard Sample: 用修正后的 Gemini 分析
                    final_content = hard_map[curr_hash]
                    counts["hard"] += 1
                else:
                    # Easy Sample: 构造简短分析
                    orig_val = extract_ground_truth(entry)
                    final_content = create_easy_sample_cot(orig_val)
                    counts["easy"] += 1
                
                new_msgs.append({"role": "assistant", "content": final_content})
                
                f_out.write(json.dumps({"messages": new_msgs}, ensure_ascii=False) + "\n")
                
            except Exception as e:
                continue

    print("\n 全部完成！")
    print(f" 统计:")
    print(f"   - Hard Samples (Deep CoT): {counts['hard']}")
    print(f"   - Easy Samples (Brief CoT): {counts['easy']}")
    print(f" 所有样本的最终数值均已锁定为原始 Ground Truth。")

if __name__ == "__main__":
    main()