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
    "risk_level 只能是：Low、Medium、High\n"
    "回覆要先具體承接使用者剛說的事，再給安全下一步；不可假裝已通知警方或消防。"
)


CHILD_TERMS = ["小孩", "孩子", "兒童", "幼童", "嬰兒", "寶寶"]
CHILD_DISTRESS_TERMS = ["哭", "哭聲", "哭叫", "哀號", "尖叫", "求救", "慘叫", "一直哭"]
UNRESPONSIVE_TERMS = ["沒反應", "沒有反應", "無反應", "叫不醒", "昏迷", "失去意識", "意識不清"]


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def has_child_distress(text: str) -> bool:
    return contains_any(text, CHILD_TERMS) and contains_any(text, CHILD_DISTRESS_TERMS)


def infer_reporter_role(text: str) -> str | None:
    self_victim_markers = [
        "打我", "追我", "堵我", "威脅我", "闖進我", "我被打", "我被搶",
        "我被追", "我被威脅", "我被困", "我躲", "我逃", "我出不去",
        "在打我", "對我動手", "把我推", "我受傷", "我流血",
    ]
    self_medical_markers = ["我發燒", "我不舒服", "我胸痛", "我喘不過氣", "我呼吸困難", "我頭暈", "我嘔吐"]
    witness_markers = ["我看到", "我聽到", "目擊", "隔壁", "樓上", "樓下", "鄰居", "旁邊"]
    caregiver_markers = [
        "我爸", "我媽", "爸爸", "媽媽", "爺爺", "奶奶", "阿公", "阿嬤",
        "我先生", "我太太", "我老婆", "我老公", "我兒子", "我女兒",
        "我小孩", "我的孩子", "家人",
    ]
    third_party_markers = ["他", "她", "對方", "有人", "朋友", "同學", "同事", "我朋友", "我同學"]

    if contains_any(text, self_victim_markers):
        return "本人受害"
    if contains_any(text, self_medical_markers):
        return "本人"
    if contains_any(text, witness_markers):
        return "旁觀者"
    if contains_any(text, caregiver_markers):
        return "照顧者/家屬"
    if contains_any(text, third_party_markers):
        return "代他人通報"
    return None


def infer_category(text: str) -> str:
    if any(k in text for k in ["火", "煙", "焦味", "失火", "放火", "著火", "起火", "冒煙"]):
        return "火災"
    if has_child_distress(text) or any(k in text for k in ["刀", "槍", "被打", "打架", "家暴", "毆打", "攻擊", "砍", "闖入"]):
        return "暴力事件"
    if any(k in text for k in ["可疑", "跟蹤", "徘徊", "怪人"]):
        return "可疑人士"
    if any(k in text for k in ["車禍", "撞車", "翻車"]):
        return "交通事故"
    if any(k in text for k in ["昏倒", "流血", "受傷", "心臟", "呼吸", "不舒服", "發燒", "抽搐", "沒反應", "沒有反應", "無反應", "叫不醒"]):
        return "醫療急症"
    if any(k in text for k in ["吵", "噪音", "叫", "吼", "咆哮"]):
        return "噪音"
    return "待確認"


def infer_risk(text: str, category: str):
    high = {"刀", "槍", "流血", "昏倒", "沒呼吸", "失去意識", "沒反應", "沒有反應", "無反應", "叫不醒", "放火", "闖入", "捅", "重傷"}
    medium = {"可疑", "跟蹤", "受傷", "呼吸困難", "救命", "威脅", "徘徊", "害怕"}
    if any(k in text for k in high) or category == "火災":
        return 0.88, "High"
    if has_child_distress(text):
        return 0.62, "Medium"
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


def normalize_reply_safety(reply: str) -> str:
    replacements = [
        ("我會迅速通知消防隊來救援", "建議你現在撥打 119，我也會協助你整理通報資訊"),
        ("我會立刻通知警方", "建議你現在撥打 110，我也會協助你整理通報資訊"),
        ("我會通知警方", "建議你現在撥打 110，我也會協助你整理通報資訊"),
        ("我會通知警察", "建議你現在撥打 110，我也會協助你整理通報資訊"),
        ("我會通知消防隊", "建議你現在撥打 119，我也會協助你整理通報資訊"),
        ("我會派人過去", "我可以協助你整理通報資訊"),
        ("請保持冷靜", "先慢慢來"),
        ("保持冷靜", "先慢慢來"),
    ]
    text = reply
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def convert_item(item: dict) -> dict:
    user_input = (item.get("input") or "").strip()
    raw_output = (item.get("output") or "").strip()
    category = infer_category(user_input)
    risk_score, risk_level = infer_risk(user_input, category)
    reply, next_question = split_reply_and_question(normalize_reply_safety(raw_output))
    reporter_role = infer_reporter_role(user_input)

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
            "people_injured": True if any(k in user_input for k in ["流血", "受傷", "昏倒", "沒反應", "沒有反應", "無反應", "叫不醒"]) else None,
            "weapon": True if any(k in user_input for k in ["刀", "槍"]) else None,
            "danger_active": True if any(k in user_input for k in ["一直", "還在", "持續"]) else None,
            "reporter_role": reporter_role,
            "conscious": False if contains_any(user_input, UNRESPONSIVE_TERMS) else None,
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
