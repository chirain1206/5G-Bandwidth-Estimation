import os
import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer, 
    AutoModelForCausalLM, 
    BitsAndBytesConfig,
    DataCollatorForLanguageModeling
)
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig
import argparse

# ================= Configuration Arguments Setup =================
def build_argparser():
    parser = argparse.ArgumentParser(description="Fine-tune Llama 3.1 for bandwidth prediction using LoRA and TRL.")

    # Model and Output Configuration
    parser.add_argument("--model_id", type=str, 
                        default="meta-llama/Meta-Llama-3.1-8B-Instruct",
                        help="Pre-trained model ID from Hugging Face.")
    parser.add_argument("--data_dir", type=str, 
                        default="dataset_nsg_5g_only",
                        help="Root directory containing train.jsonl and val.jsonl.")
    parser.add_argument("--output_dir", type=str, 
                        default="predictor_nsg_5g_only",
                        help="Directory to save checkpoints and final model.")
    
    # Training Parameters
    parser.add_argument("--epochs", type=int, 
                        default=2,
                        help="Number of training epochs.")
    parser.add_argument("--batch_size", type=int, 
                        default=6,
                        help="Per device training batch size.")
    parser.add_argument("--max_seq_length", type=int, 
                        default=512,
                        help="Maximum sequence length for tokenization.")
    parser.add_argument("--learning_rate", type=float, 
                        default=2e-4,
                        help="Initial learning rate.")
    
    # Resume/Checkpointing
    parser.add_argument("--resume_from_checkpoint", type=str, 
                        default=None,
                        help="Path to a specific checkpoint folder or set to 'last' to auto-pick the latest in output_dir.")
    
    return parser

# ================= Main Training Function =================
def main():
    parser = build_argparser()
    args = parser.parse_args()

    # --- 0. Dynamic Configuration ---
    MODEL_ID = args.model_id
    DATA_DIR = args.data_dir
    OUTPUT_DIR = args.output_dir

    print(f"Loading model: {MODEL_ID}...")
    
    # --- 1. Model Loading and Quantization ---
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto",
        attn_implementation="flash_attention_2" 
    )
    
    # --- 2. Tokenizer and LoRA Config ---
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.model_max_length = args.max_seq_length # Use argument here
    
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )

    # --- 3. Data Loading ---
    dataset = load_dataset("json", data_files={
        "train": f"{DATA_DIR}/train.jsonl",
        "validation": f"{DATA_DIR}/val.jsonl"
    })

    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    # --- 4. Training Arguments (SFTConfig) ---
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        num_train_epochs=args.epochs, # Use argument here
        per_device_train_batch_size=args.batch_size, # Use argument here
        gradient_accumulation_steps=2,
        learning_rate=args.learning_rate, # Use argument here
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=10,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=3,
        eval_strategy="steps",
        eval_steps=100,
        fp16=True,
        optim="paged_adamw_8bit",
        packing=False,
        report_to="none"
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=peft_config,
        data_collator=collator,
        #max_seq_length=args.max_seq_length,
    )
    
    # --- 5. Start Training with Resume Logic ---
    print(">>> Starting Training...")
    
    # Determine resume path
    resume_path = args.resume_from_checkpoint
    if resume_path == "last":
        # Check output directory for latest checkpoint
        checkpoints = [d for d in os.listdir(args.output_dir) if d.startswith("checkpoint-")]
        if checkpoints:
            # Find the checkpoint with the highest step number
            latest_ckpt_dir = sorted(checkpoints, key=lambda x: int(x.split('-')[-1]))[-1]
            resume_path = os.path.join(args.output_dir, latest_ckpt_dir)
        else:
            resume_path = None # Start from scratch if 'last' is specified but no checkpoint exists

    trainer.train(resume_from_checkpoint=resume_path)
    
    # --- 6. Save Final Model ---
    print(f">>> Saving model to {OUTPUT_DIR}")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

if __name__ == "__main__":
    main()