#!/usr/bin/env python3
"""
用 OpenAI API 或本機 Ollama 自動生成 E-CARE 訓練資料。

用法（OpenAI）：
    $env:OPENAI_API_KEY = "sk-..."
    python scripts/generate_training_data.py --count 50 --output scripts/data/generated.jsonl

用法（本機 Ollama，不需要 API Key）：
    python scripts/generate_training_data.py --backend ollama --model llama3.1:8b --count 50
"""

import argparse
import json
import os
import random
import time
import urllib.request
from pathlib import Path


# ======================
# 場景範本
# ======================

SCENARIOS = [
    {"category": "醫療急症", "risk": "High",  "seed": "家人突然失去意識倒在地上，叫不醒"},
    {"category": "醫療急症", "risk": "High",  "seed": "朋友說呼吸很困難，嘴唇開始發紫"},
    {"category": "醫療急症", "risk": "Medium", "seed": "自己發燒到39度，頭很暈，擔心越來越嚴重"},
    {"category": "醫療急症", "risk": "Medium", "seed": "老人家摔倒，腿可能骨折，意識清楚但很痛"},
    {"category": "醫療急症", "risk": "Low",   "seed": "小孩擦破皮，輕微流血，不確定需不需要送醫"},
    {"category": "醫療急症", "risk": "High",  "seed": "有人抽搐倒地，已經停止抽搐但沒有反應"},
    {"category": "火災",     "risk": "High",  "seed": "廚房起火，火勢開始蔓延到客廳，家裡還有人"},
    {"category": "火災",     "risk": "High",  "seed": "看到樓上住戶窗戶冒出濃煙，不確定裡面有沒有人"},
    {"category": "火災",     "risk": "Medium", "seed": "聞到焦味，不確定是不是失火，還沒看到火"},
    {"category": "暴力事件", "risk": "High",  "seed": "有人拿刀在外面追人，現在跑進大樓裡"},
    {"category": "暴力事件", "risk": "High",  "seed": "有人闖進家裡，躲在房間裡，很害怕"},
    {"category": "暴力事件", "risk": "High",  "seed": "看到有人被打倒在地上流血，打人的人還在現場"},
    {"category": "暴力事件", "risk": "Medium", "seed": "兩個人在路邊激烈爭吵，其中一個人好像要動手"},
    {"category": "暴力事件", "risk": "Medium", "seed": "室友喝醉酒情緒失控，開始砸東西，很害怕"},
    {"category": "可疑人士", "risk": "Medium", "seed": "有陌生人在社區裡一直徘徊，已經一個多小時了"},
    {"category": "可疑人士", "risk": "Medium", "seed": "走路回家時發現有人一直跟著自己"},
    {"category": "可疑人士", "risk": "Low",   "seed": "鄰居最近很可疑，一直有陌生人進出，不確定要不要報警"},
    {"category": "噪音",     "risk": "Low",   "seed": "隔壁深夜還在施工，已經吵了三個小時"},
    {"category": "噪音",     "risk": "Medium", "seed": "樓上有人一直大吼大叫，聽起來像在激烈爭吵"},
    {"category": "交通事故", "risk": "High",  "seed": "目擊嚴重車禍，有人被困在車內，看起來有受傷"},
    {"category": "交通事故", "risk": "Medium", "seed": "機車和汽車擦撞，機車騎士摔倒，走路好像有點跛"},
    {"category": "待確認",   "risk": "Medium", "seed": "外面有很大的聲響，不知道發生了什麼事，有點害怕"},
    {"category": "待確認",   "risk": "Low",   "seed": "不確定這樣算不算要報警，但感覺有點不對勁"},
    {"category": "待確認",   "risk": "Medium", "seed": "聽到有人在喊救命，不知道從哪裡來的"},
]


GENERATOR_SYSTEM_PROMPT = """你是緊急報案訓練資料生成器。請根據場景生成繁體中文對話，輸出 JSON 物件。

輸出結構（固定格式，不要更改欄位名稱）：
{
  "user1": "第一輪使用者說的話（自然口語、有情緒）",
  "assistant1": {
    "reply": "有同理心的1到2句回應",
    "risk_score": 0.7,
    "risk_level": "High",
    "should_escalate": true,
    "next_question": "最重要的下一個問題",
    "category": "火災|可疑人士|噪音|醫療急症|暴力事件|交通事故|待確認",
    "people_injured": null,
    "weapon": null,
    "danger_active": null,
    "dispatch_advice": "建議派遣：警察"
  },
  "user2": "第二輪使用者回答（回應上一個問題）",
  "assistant2": {
    "reply": "有同理心的1到2句回應",
    "risk_score": 0.7,
    "risk_level": "High",
    "should_escalate": true,
    "next_question": "下一個問題或空字串",
    "category": "火災|可疑人士|噪音|醫療急症|暴力事件|交通事故|待確認",
    "people_injured": null,
    "weapon": null,
    "danger_active": null,
    "dispatch_advice": "建議派遣：警察"
  }
}

同理心原則：
- reply 要先接住情緒，不要像系統訊息
- 用「我知道你現在很害怕」「我先陪你整理」這類自然說法
- risk_level High 時 reply 要簡短有力"""

TRAINING_SYSTEM_PROMPT = (
    "你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。\n"
    "只輸出 JSON，不要加入其他文字。\n"
    "category 只能是：火災、可疑人士、噪音、醫療急症、暴力事件、交通事故、待確認\n"
    "risk_level 只能是：Low、Medium、High"
)


def build_user_prompt(scenario: dict) -> str:
    return (
        f"請生成一段關於「{scenario['seed']}」的緊急報案對話。\n"
        f"場景：{scenario['category']}，預期風險：{scenario['risk']}\n"
        f"要求 2 到 3 輪對話，展示助理如何逐步釐清狀況並保持同理心。"
    )


# ======================
# OpenAI 後端
# ======================

def call_openai(api_key: str, model: str, scenario: dict) -> list | None:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
                {"role": "user",   "content": build_user_prompt(scenario)},
            ],
            temperature=0.9,
            max_tokens=2000,
        )
        return parse_turns(resp.choices[0].message.content or "")
    except Exception as e:
        print(f"[跳過] {e}")
        return None


# ======================
# Ollama 後端
# ======================

def call_ollama(model: str, scenario: dict, base_url: str = "http://localhost:11434", debug: bool = False) -> list | None:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt(scenario)},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.7, "num_predict": 4096},
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        content = data.get("message", {}).get("content", "")
        return parse_flat_response(content, debug=debug)
    except Exception as e:
        print(f"[跳過] {e}")
        return None


# ======================
# 共用解析
# ======================

def parse_flat_response(raw: str, debug: bool = False) -> list | None:
    """把模型輸出的扁平 JSON（user1/assistant1/user2/assistant2）轉成 turns 清單。"""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        d = json.loads(raw)
    except Exception as e:
        if debug:
            print(f"\n  [除錯] JSON 解析失敗：{e}\n  原始：{raw[:300]}")
        return None

    if not all(k in d for k in ("user1", "assistant1", "user2", "assistant2")):
        if debug:
            print(f"\n  [除錯] 缺少必要欄位，有：{list(d.keys())}")
        return None

    def assistant_to_full_json(a: dict) -> str:
        category = a.get("category", "待確認")
        dispatch_map = {
            "火災": "建議派遣：消防隊", "醫療急症": "建議派遣：救護車",
            "暴力事件": "建議派遣：警察", "可疑人士": "建議派遣：警察",
            "噪音": "建議派遣：警察", "交通事故": "建議派遣：救護車 + 警察",
            "待確認": "建議派遣：待確認",
        }
        risk_level = a.get("risk_level", "Medium")
        full = {
            "reply": a.get("reply", ""),
            "risk_score": a.get("risk_score", 0.5),
            "risk_level": risk_level,
            "should_escalate": a.get("should_escalate", risk_level == "High"),
            "next_question": a.get("next_question", ""),
            "semantic": {
                "intent": "求救" if risk_level == "High" else "通報",
                "primary_need": "立即安全協助" if risk_level == "High" else "釐清狀況",
                "emotion": "fearful" if risk_level in ["High", "Medium"] else "neutral",
                "reply_strategy": "先穩定情緒，再確認安全",
                "entities": {"location": None, "injured": a.get("people_injured"),
                             "weapon": a.get("weapon"), "danger_active": a.get("danger_active")},
            },
            "extracted": {
                "category": category,
                "location": None,
                "people_injured": a.get("people_injured"),
                "weapon": a.get("weapon"),
                "danger_active": a.get("danger_active"),
                "reporter_role": None, "conscious": None,
                "breathing_difficulty": None, "fever": None, "symptom_summary": None,
                "dispatch_advice": a.get("dispatch_advice", dispatch_map.get(category, "建議派遣：待確認")),
                "description": None,
            },
        }
        return json.dumps(full, ensure_ascii=False)

    a1 = d["assistant1"] if isinstance(d["assistant1"], dict) else {}
    a2 = d["assistant2"] if isinstance(d["assistant2"], dict) else {}

    return [
        {"role": "user",      "content": str(d["user1"])},
        {"role": "assistant", "content": assistant_to_full_json(a1)},
        {"role": "user",      "content": str(d["user2"])},
        {"role": "assistant", "content": assistant_to_full_json(a2)},
    ]


def parse_turns(raw: str, debug: bool = False) -> list | None:
    raw = raw.strip()
    # 去掉 markdown code fence
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    # 找出第一個 [ 開頭的位置
    start = raw.find("[")
    if start < 0:
        if debug:
            print(f"\n  [除錯] 找不到 JSON 陣列，原始輸出：\n  {raw[:300]}")
        return None
    raw = raw[start:]
    try:
        turns = json.loads(raw)
    except Exception as e:
        if debug:
            print(f"\n  [除錯] JSON 解析失敗：{e}\n  原始輸出：\n  {raw[:300]}")
        return None

    if not isinstance(turns, list) or len(turns) < 2:
        return None

    # 修正：有些模型把 assistant content 輸出成 dict 而不是字串
    fixed = []
    for turn in turns:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "assistant" and isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        elif role == "assistant" and isinstance(content, str):
            # 確認 content 本身是合法 JSON
            try:
                json.loads(content)
            except Exception:
                if debug:
                    print(f"\n  [除錯] assistant content 不是合法 JSON：{content[:200]}")
                return None
        fixed.append({"role": role, "content": content})

    return fixed if len(fixed) >= 2 else None


# ======================
# 主流程
# ======================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",  default="scripts/data/generated.jsonl")
    parser.add_argument("--count",   type=int, default=100)
    parser.add_argument("--backend", choices=["openai", "ollama"], default="openai")
    parser.add_argument("--model",   default=None,
                        help="OpenAI: gpt-4o-mini（預設）  Ollama: llama3.1:8b（預設）")
    parser.add_argument("--delay",   type=float, default=0.5)
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--debug", action="store_true", help="顯示模型原始輸出（除錯用）")
    args = parser.parse_args()

    # 決定模型名稱預設值
    if args.model is None:
        args.model = "gpt-4o-mini" if args.backend == "openai" else "llama3.1:8b"

    # OpenAI 需要 Key
    api_key = None
    if args.backend == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("請設定 $env:OPENAI_API_KEY=sk-...")
            return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"後端：{args.backend}  模型：{args.model}")
    print(f"目標：{args.count} 筆  輸出：{output_path}\n")

    generated = failed = 0

    with output_path.open("w", encoding="utf-8") as f:
        scenario_index = 0
        while generated < args.count:
            scenario = SCENARIOS[scenario_index % len(SCENARIOS)]
            scenario_index += 1
            label = scenario['seed'][:22]
            print(f"[{generated+1}/{args.count}] {label}...", end=" ", flush=True)

            if args.backend == "openai":
                turns = call_openai(api_key, args.model, scenario)
            else:
                turns = call_ollama(args.model, scenario, args.ollama_url, debug=args.debug)

            if turns:
                record = {
                    "messages": [{"role": "system", "content": TRAINING_SYSTEM_PROMPT}] + turns
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                generated += 1
                n = len([t for t in turns if t["role"] == "user"])
                print(f"OK（{n} 輪）")
            else:
                failed += 1
                print("失敗")

            time.sleep(args.delay)

    print(f"\n完成：{generated} 筆成功，{failed} 筆失敗 → {output_path}")


if __name__ == "__main__":
    main()
