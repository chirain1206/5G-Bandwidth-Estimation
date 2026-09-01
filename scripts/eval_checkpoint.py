import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
import json
import os
import sys
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from tqdm import tqdm
import matplotlib.pyplot as plt

BASE_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
OUTPUT_DIR = "llama3-5g-predictor"  
VAL_DATA = "dataset_ucc_llama3_5g_only/val.jsonl" 
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def get_latest_checkpoint(output_dir):
    if not os.path.exists(output_dir):
        return None
    checkpoints = [d for d in os.listdir(output_dir) if d.startswith("checkpoint-")]
    if not checkpoints:
        return None

    latest = sorted(checkpoints, key=lambda x: int(x.split("-")[-1]))[-1]
    return os.path.join(output_dir, latest)

def extract_number(text):
    try:
        return float(text.strip())
    except ValueError:
        import re
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        if match:
            return float(match.group())
        return 0.0

ckpt_path = get_latest_checkpoint(OUTPUT_DIR)
if not ckpt_path:
    print(f"{OUTPUT_DIR} can't find checkpoint!")
    sys.exit()

print(f"Loading checkpoint: {ckpt_path} on {DEVICE}...")

model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    load_in_4bit=True, 
    device_map="auto",
    torch_dtype=torch.float16
)
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
tokenizer.pad_token = tokenizer.eos_token

model = PeftModel.from_pretrained(model, ckpt_path)
model.eval()

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
print("Starting inference (this may take a while)...")

for i in tqdm(range(len(prompts))):
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

y_true = np.array(ground_truths)
y_pred = np.array(predictions)

mae = mean_absolute_error(y_true, y_pred)
rmse = np.sqrt(mean_squared_error(y_true, y_pred))
r2 = r2_score(y_true, y_pred)

print("\n" + "="*30)
print(f"Evaluation Report ({os.path.basename(ckpt_path)})")
print("="*30)
print(f"Samples: {len(y_true)}")
print(f"MAE  : {mae:.4f} Mbps")
print(f"RMSE : {rmse:.4f} Mbps")
print(f"R^2   : {r2:.4f}")
print("="*30)


plt.figure(figsize=(8, 8))
plt.scatter(y_true, y_pred, alpha=0.3, s=10)

p1 = max(max(y_pred), max(y_true))
p2 = min(min(y_pred), min(y_true))
plt.plot([p1, p2], [p1, p2], 'r--')

plt.xlabel('Ground Truth (Mbps)')
plt.ylabel('Prediction (Mbps)')
plt.title(f'Prediction Analysis (R2={r2:.3f})')
plt.grid(True)
plt.savefig(f'{OUTPUT_DIR}/eval_result.png')
print(f"Scatter plot saved to {OUTPUT_DIR}/eval_result.png")