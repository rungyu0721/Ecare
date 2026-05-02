#!/usr/bin/env python3
"""
E-CARE Fine-tune 訓練腳本（HuggingFace PEFT + QLoRA）

用法：
    python scripts/train_finetune.py --data scripts/data/ecare_train_final.jsonl

筆電（8GB VRAM）：使用預設參數即可
桌機 4080（16GB VRAM）：加上 --batch_size 4 --lora_rank 32
"""

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import Dataset
from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)


# ======================
# 設定
# ======================

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",       default="scripts/data/ecare_train_final.jsonl")
    parser.add_argument("--model",      default="Qwen/Qwen2.5-7B-Instruct",
                        help="HuggingFace 模型 ID")
    parser.add_argument("--output",     default="scripts/output/ecare-lora")
    parser.add_argument("--epochs",     type=int,   default=3)
    parser.add_argument("--batch_size", type=int,   default=1,
                        help="筆電用 1，4080 用 4")
    parser.add_argument("--grad_accum", type=int,   default=8,
                        help="梯度累積步數，batch_size * grad_accum = 有效 batch size")
    parser.add_argument("--lora_rank",  type=int,   default=16,
                        help="LoRA rank，筆電用 16，4080 用 32")
    parser.add_argument("--max_len",    type=int,   default=1024)
    parser.add_argument("--lr",         type=float, default=2e-4)
    return parser.parse_args()


# ======================
# 資料載入
# ======================

def load_jsonl(path: str) -> list:
    records = []
    for encoding in ["utf-8-sig", "utf-8", "utf-16"]:
        try:
            with open(path, encoding=encoding) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            print(f"讀取成功（encoding: {encoding}），共 {len(records)} 筆")
            return records
        except (UnicodeDecodeError, json.JSONDecodeError):
            records = []
            continue
    raise ValueError(f"無法讀取 {path}，請確認檔案格式")


def format_messages(record: dict, tokenizer) -> str:
    """把 messages 陣列轉成模型的 chat template 格式。"""
    messages = record.get("messages", [])
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )


class EcareDataset(Dataset):
    def __init__(self, records, tokenizer, max_len):
        self.items = []
        for r in records:
            text = format_messages(r, tokenizer)
            enc = tokenizer(text, truncation=True, max_length=max_len, padding=False)
            enc["labels"] = enc["input_ids"].copy()
            self.items.append(enc)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


# ======================
# 主流程
# ======================

def main():
    args = parse_args()

    print(f"模型：{args.model}")
    print(f"資料：{args.data}")
    print(f"輸出：{args.output}")
    print(f"VRAM：{torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    print()

    # --- 量化設定（4-bit QLoRA）---
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    # --- 載入 Tokenizer ---
    print("載入 Tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # --- 載入模型 ---
    print("載入模型（4-bit 量化）...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    # --- LoRA 設定 ---
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_rank,
        lora_alpha=args.lora_rank * 2,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # --- 準備資料集 ---
    print("準備資料集...")
    raw = load_jsonl(args.data)
    dataset = EcareDataset(raw, tokenizer, args.max_len)
    print(f"訓練筆數：{len(dataset)}")

    # --- 訓練參數 ---
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_path),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        fp16=False,
        bf16=True,
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
        dataloader_num_workers=0,
    )

    # --- 開始訓練 ---
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DataCollatorForSeq2Seq(tokenizer, pad_to_multiple_of=8),
    )

    print("開始訓練...")
    trainer.train()

    # --- 儲存 LoRA 權重 ---
    model.save_pretrained(str(output_path / "final"))
    tokenizer.save_pretrained(str(output_path / "final"))
    print(f"\n訓練完成，LoRA 權重儲存於：{output_path}/final")
    print("下一步：用 convert_to_gguf.py 轉換成 Ollama 可以用的格式")


if __name__ == "__main__":
    main()
