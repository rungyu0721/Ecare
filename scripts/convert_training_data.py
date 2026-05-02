#!/usr/bin/env python3
"""
將 Alpaca 格式的 E-CARE 訓練資料轉換為 Llama 3.1 Chat 格式。

用法：
    python scripts/convert_training_data.py <input.json> <output.jsonl>
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

SYSTEM_PROMPT = (
    "你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。\n"
    "只輸出 JSON，不要加入其他文字。\n"
    "category 只能是：火災、可疑人士、噪音、醫療急症、暴力事件、交通事故、待確認\n"
    "risk_level 只能是：Low、Medium、High"
)


def infer_category(text: str) -> str:
    if any(k in text for k in ["火", "煙", "焦味", "失火", "放火", "著火", "起火", "冒煙"]):
        return "火災"
    if any(k in text for k in ["刀", "槍", "被打", "打架", "家暴", "毆打", "攻擊", "砍", "闖入"]):
        return "暴力事件"
    if any(k in text for k in ["可疑", "跟蹤", "徘徊", "怪人"]):
        return "可疑人士"
    if any(k in text for k in ["車禍", "撞車", "翻車"]):
        return "交通事故"
    if any(k in text for k in ["昏倒", "流血", "受傷", "心臟", "呼吸", "不舒服", "發燒", "抽搐"]):
        return "醫療急症"
    if any(k in text for k in ["吵", "噪音", "叫", "吼", "咆哮"]):
        return "噪音"
    return "待確認"


def infer_risk(text: str, category: str):
    high = {"刀", "槍", "流血", "昏倒", "沒呼吸", "失去意識", "放火", "闖入", "捅", "重傷"}
    medium = {"可疑", "跟蹤", "受傷", "呼吸困難", "救命", "威脅", "徘徊", "害怕"}
    if any(k in text for k in high) or category == "火災":
        return 0.88, "High"
    if any(k in text for k in medium) or category in ["暴力事件", "可疑人士"]:
        return 0.62, "Medium"
    if category == "醫療急症":
        return 0.55, "Medium"
    return 0.3, "Low"


def split_reply_and_question(output: str):
    sentences = re.split(r"(?<=[。！？])\s*", output.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return output, ""
    for i in range(len(sentences) - 1, -1, -1):
        s = sentences[i]
        if "？" in s or "請告訴" in s or "請再" in s or "請問" in s or s.startswith("請"):
            return "".join(sentences[:i]).strip() or output.strip(), s
    return output.strip(), ""


def convert_item(item: dict) -> dict:
    user_input = (item.get("input") or "").strip()
    raw_output = (item.get("output") or "").strip()
    category = infer_category(user_input)
    risk_score, risk_level = infer_risk(user_input, category)
    reply, next_question = split_reply_and_question(raw_output)

    dispatch_map = {
        "火災": "建議派遣：消防隊",
        "醫療急症": "建議派遣：救護車",
        "暴力事件": "建議派遣：警察",
        "可疑人士": "建議派遣：警察",
        "噪音": "建議派遣：警察",
        "交通事故": "建議派遣：救護車 + 警察",
        "待確認": "建議派遣：待確認",
    }

    output_json = {
        "reply": reply,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "should_escalate": risk_level == "High",
        "next_question": next_question,
        "semantic": {
            "intent": "求救" if risk_level == "High" else "通報",
            "primary_need": "立即安全協助" if risk_level == "High" else "釐清狀況",
            "emotion": "fearful" if risk_level in ["High", "Medium"] else "neutral",
            "reply_strategy": "先穩定情緒，再確認安全與位置",
            "entities": {"location": None, "injured": None, "weapon": None, "danger_active": None},
        },
        "extracted": {
            "category": category,
            "location": None,
            "people_injured": True if any(k in user_input for k in ["流血", "受傷", "昏倒"]) else None,
            "weapon": True if any(k in user_input for k in ["刀", "槍"]) else None,
            "danger_active": True if any(k in user_input for k in ["一直", "還在", "持續"]) else None,
            "reporter_role": None,
            "conscious": None,
            "breathing_difficulty": True if "呼吸" in user_input else None,
            "fever": None,
            "symptom_summary": None,
            "dispatch_advice": dispatch_map.get(category, "建議派遣：待確認"),
            "description": user_input,
        },
    }

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": json.dumps(output_json, ensure_ascii=False)},
        ]
    }


def main():
    if len(sys.argv) < 3:
        print("用法：python scripts/convert_training_data.py <input.json> <output.jsonl>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        print(f"找不到：{input_path}")
        sys.exit(1)

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    converted, skipped = 0, 0
    with output_path.open("w", encoding="utf-8") as f:
        for item in raw:
            if not item.get("input") or not item.get("output"):
                skipped += 1
                continue
            f.write(json.dumps(convert_item(item), ensure_ascii=False) + "\n")
            converted += 1

    print(f"完成：{converted} 筆，跳過 {skipped} 筆 → {output_path}")


if __name__ == "__main__":
    main()
