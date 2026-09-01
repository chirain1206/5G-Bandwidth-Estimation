import json
import os
import time
import google.generativeai as genai
from tqdm import tqdm

# 从环境变量读取 API Key，不要在代码里硬编码密钥
# export GOOGLE_API_KEY="..."  (Linux/macOS)
# $env:GOOGLE_API_KEY="..."    (Windows PowerShell)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise SystemExit("请先设置环境变量 GOOGLE_API_KEY（Google AI Studio 申请）")

INPUT_FILE = "val_hard_top10.jsonl"  
OUTPUT_FILE = "val_hard_cot.jsonl" 

MODEL_NAME = 'gemini-3-flash-preview' 

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)

SYSTEM_PROMPT = """
Role: You are a 5G Network Performance Expert.

Task: The user will paste JSONL lines containing network history, current state, an XGBoost prediction of downlink throughput ending at next timestamp, and a Ground Truth Residual.
Your goal is to rewrite the 'assistant' content to include a logical "Chain-of-Thought" analysis BEFORE the final residual.

### Domain Knowledge (Crucial for Analysis):
1. **Definition of Residual**: Residual = Actual Throughput - Baseline Prediction.
   - **Negative Residual (e.g., -50)**: The network performed WORSE than expected. Look for congestion, configuration limits (low RB), or signal drops.
   - **Positive Residual (e.g., +20)**: The network performed BETTER than expected. Look for excellent spectral efficiency or SCell activation.
2. **Context**: The XGBoost model often relies on averages and fails to capture **sudden changes** (e.g., drop in T vs T-1) or **configuration mismatches**.

### Metrics Guide (Use these to explain the "Why"):
   - **RSRP, RSRQ**: Signal Power. Weak signal (<-110dBm) limits max speed.
   - **SINR**: Interference. (>20dB is Clean).
   - **BLER**: Block Error Rate. **>10% is critical**, implying packet loss/retransmissions which kills throughput.
   - **Avg RB (Resource Blocks)**: The pipe width. 
     - **Low RB (<10)** with heavy traffic indicates **CONGESTION** (Shared with too many users).
   - **Modulation/MCS**: 
     - Order: 256QAM > 64QAM > 16QAM > QPSK.
     - **CRITICAL MISMATCH**: If SINR is High (>15dB) but Modulation is Low (e.g., QPSK), this is a configuration failure causing large negative residuals.

### Logic Guide (Step-by-Step):
1. **Check the Sign**: Is the residual negative (performance miss) or positive (performance beat)?
2. **Scan for "Change" and "Contradictions"**: 
   - **Trend**: Did RSRP or Throughput drop significantly from T-1 to T?
   - **Mismatch**: Is the signal good (High RSRP/SINR) but the Modulation/RB allocation surprisingly low?
3. **Formulate Hypothesis**: Explain *why* the baseline missed it.

### Output Format Constraint (STRICT):
1. Format: Output MUST be a single line, excluding system and user content: "Analysis: [Reasoning]... \n\n### Final Residual: [Value]"
2. The line count of output MUST match the line count of input (1-to-1 mapping).
3. Keep reasoning concise (30-50 words).
4. ANCHOR RULE: You MUST use "### Final Residual:" as the separator.
5. Do NOT change the numerical value of the Final Residual. Use the exact number from the input.
6. Do NOT output JSON. Do NOT output markdown code blocks. Just plain text.

### Example:
Input Assistant Content: "-67.95"
Output Assistant Content: "Analysis: Despite good SINR (19dB), the modulation is stuck at QPSK (100%) and Avg RB dropped to 10. This indicates a severe configuration mismatch or congestion that XGBoost missed. \n\n### Final Residual: -67.95"
"""

def generate_cot(entry):
    try:
        user_content_str = json.dumps(entry)
        
        full_prompt = f"{SYSTEM_PROMPT}\n\n[Input Data]\n{user_content_str}"

        response = model.generate_content(full_prompt)
        result_text = response.text.strip()

        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        
        return result_text.strip()

    except Exception as e:
        print(f"\n[API Error] {e}")
        return None

def main():
    if not os.path.exists(INPUT_FILE):
        print(f" Input file not found: {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        input_lines = f.readlines()

    processed_count = 0
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            processed_count = len(f.readlines())
    
    print(f" Total Tasks: {len(input_lines)} | Completed: {processed_count}")
    
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f_out:
        for i in tqdm(range(processed_count, len(input_lines)), desc="Processing"):
            line = input_lines[i]
            if not line.strip(): continue
            
            entry = json.loads(line)
            
            try:
                user_str = json.dumps(entry)
                
                # 请求生成
                response = model.generate_content(f"{SYSTEM_PROMPT}\nInput:\n{user_str}")
                raw_text = response.text.strip()
                
                # 清洗 Markdown
                if raw_text.startswith("```"):
                    raw_text = raw_text.replace("```json", "").replace("```", "").strip()
                
                # === 核心修改：暴力移除换行 ===
                # 把所有换行符替换成两个空格，保证视觉上有一点间隔，但物理上不换行
                flat_text = raw_text.replace("\n", "  ").replace("\r", "")
                
                # 构造对象
                new_obj = {"role": "assistant", "content": flat_text}
                
                # 写入
                f_out.write(json.dumps(new_obj, ensure_ascii=False) + "\n")
                f_out.flush()
                
            except Exception as e:
                print(f"Error: {e}")
                # 写入错误占位符
                f_out.write(json.dumps({"role": "assistant", "content": "ERROR"}) + "\n")

    print("\n Generation Completed！")

if __name__ == "__main__":
    print(SYSTEM_PROMPT)
    #main()