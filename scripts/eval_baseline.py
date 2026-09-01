import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import json
import os
import sys
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from tqdm import tqdm
import matplotlib.pyplot as plt
import re

# ================= Configuration =================
BASE_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
VAL_DATA = "dataset_nsg_full_3/val.jsonl"
OUTPUT_DIR = "baseline_nsg_full_3"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
LOG_INTERVAL = 100
# ===============================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

def extract_number(text):
    try:
        return float(text.strip())
    except ValueError:
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        if match:
            return float(match.group())
        return 0.0

def main():
    print(f"Loading BASE MODEL: {BASE_MODEL} on {DEVICE}...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
    )

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.float16
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token

    print("Model loaded successfully (No Adapters).")

    print(f"Reading validation data from {VAL_DATA}...")
    prompts = []
    ground_truths = []

    with open(VAL_DATA, 'r') as f:
        lines = f.readlines()
        print(f"Found {len(lines)} samples.")
        
        for line in lines:
            data = json.loads(line)
            messages = data['messages']
            
            input_msgs = [m for m in messages if m['role'] != 'assistant']
            
            label_str = next(m['content'] for m in messages if m['role'] == 'assistant')
            
            prompts.append(input_msgs)
            ground_truths.append(float(label_str))

    predictions = []
    print("Starting baseline inference...")

    pbar = tqdm(range(len(prompts)))
    
    for i in pbar:
        msgs = prompts[i]
        
        input_ids = tokenizer.apply_chat_template(
            msgs, 
            add_generation_prompt=True, 
            return_tensors="pt"
        ).to(DEVICE)
        
        with torch.no_grad():
            outputs = model.generate(
                input_ids,
                max_new_tokens=10, 
                do_sample=False,   
                pad_token_id=tokenizer.eos_token_id
            )
        
        generated_text = tokenizer.decode(outputs[0][input_ids.shape[1]:], skip_special_tokens=True)
        pred_val = extract_number(generated_text)
        predictions.append(pred_val)

        if (i + 1) % LOG_INTERVAL == 0:
            current_preds = np.array(predictions)
            current_truths = np.array(ground_truths[:len(predictions)])
            
            curr_mae = mean_absolute_error(current_truths, current_preds)
            curr_r2 = r2_score(current_truths, current_preds)
            pbar.set_description(f"MAE:{curr_mae:.2f} R2:{curr_r2:.2f}")

    results_df = pd.DataFrame({
        "Ground_Truth_Mbps": ground_truths,
        "Predicted_Mbps": predictions
    })
    results_df["Abs_Error"] = abs(results_df["Ground_Truth_Mbps"] - results_df["Predicted_Mbps"])
    
    csv_path = os.path.join(OUTPUT_DIR, "eval_results_baseline.csv")
    results_df.to_csv(csv_path, index=False)
    print(f"Saved results to: {csv_path}")

    y_true = np.array(ground_truths)
    y_pred = np.array(predictions)

    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)

    print("\n" + "="*30)
    print("BASELINE Evaluation Report")
    print("="*30)
    print(f"Samples: {len(y_true)}")
    print(f"MAE  : {mae:.4f} Mbps")
    print(f"RMSE : {rmse:.4f} Mbps")
    print(f"R2   : {r2:.4f}")
    print("="*30)

    plt.figure(figsize=(8, 8))
    plt.scatter(y_true, y_pred, alpha=0.3, s=10, label='Baseline Preds')
    
    p1 = max(max(y_pred), max(y_true))
    p2 = min(min(y_pred), min(y_true))
    plt.plot([p1, p2], [p1, p2], 'r--', label='Ideal')

    plt.xlabel('Ground Truth (Mbps)')
    plt.ylabel('Prediction (Mbps)')
    plt.title(f'Baseline Performance (R2={r2:.3f})')
    plt.legend()
    plt.grid(True)
    
    plot_path = os.path.join(OUTPUT_DIR, "baseline_scatter.png")
    plt.savefig(plot_path)
    print(f"Scatter plot saved to: {plot_path}")

if __name__ == "__main__":
    main()