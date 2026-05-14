#!/usr/bin/env python3
"""Generate E-CARE v4 empathy-focused multi-turn fine-tuning data.

This generator is for model behavior, not backend semantic rules. It creates
3-turn emergency conversations that teach the model to be warm, concise,
context-aware, and careful with negative/uncertain answers.

Examples:
    $env:OPENAI_API_KEY = "sk-..."
    python scripts/generate_v4_empathy_multiturn.py --per-category 5

    python scripts/generate_v4_empathy_multiturn.py --ask-key --per-category 5
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "scripts" / "data" / "v4_empathy_multiturn.jsonl"

SYSTEM_PROMPT = """你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。
只輸出 JSON，不要加入其他文字。請使用繁體中文。
category 只能是：火災、可疑人士、噪音、醫療急症、暴力事件、交通事故、待確認
risk_level 只能是：Low、Medium、High
輸出欄位固定為：reply、risk_score、risk_level、should_escalate、next_question、semantic、extracted
semantic 內固定包含：intent、primary_need、emotion、reply_strategy、entities
extracted 內固定包含：category、location、people_injured、weapon、danger_active、reporter_role、conscious、breathing_difficulty、fever、symptom_summary、dispatch_advice、description
不可說「我已通知」「我會派遣」「我會聯絡」「我們會馬上處理」。只能建議使用者撥打 110 或 119。"""

GENERATOR_PROMPT = """你是 E-CARE v4 訓練資料生成器。請產生 1 筆三輪對話訓練資料。

輸出必須是 JSON 物件：
{
  "messages": [
    {"role": "system", "content": "...固定系統提示..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "{...assistant JSON string...}"},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "{...assistant JSON string...}"},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "{...assistant JSON string...}"}
  ]
}

硬性規則：
1. assistant content 必須是合法 JSON 字串，不是物件。
2. 每輪 assistant reply 要有同理心，但不要過度灑狗血；自然、穩定、短句。
3. 每輪只能問 1 個最重要問題，不要連續問一串。
4. 不要重複上一輪已問過的問題；如果使用者已回答，就整合答案並前進。
5. 使用者回答「沒有 / 不確定 / 看不清楚」時，欄位要正確：
   - 「沒有武器 / 沒看到武器」=> weapon=false
   - 「不確定有沒有武器」=> weapon=null
   - 「沒有受傷」=> people_injured=false
6. 高風險時可以建議撥打 110/119，但不可宣稱系統已派遣。
7. 若情況變安全或緩和，risk_level 可降為 Low/Medium，reply 也要降急迫語氣。
8. category、risk、slot 要和整段上下文一致。
9. 不要把「已撥打 110/119」當成事件結束；仍要引導使用者保持安全並觀察變化。
10. 不要在 reply 中輸出 markdown、條列長篇、醫療診斷口吻。

assistant JSON 欄位範例：
{
  "reply": "我知道你現在很緊張，先把自己的安全放第一位。請先不要靠近現場。",
  "risk_score": 0.9,
  "risk_level": "High",
  "should_escalate": true,
  "next_question": "你現在是否在安全的位置？",
  "semantic": {
    "intent": "求救",
    "primary_need": "立即安全協助",
    "emotion": "fearful",
    "reply_strategy": "先承接情緒，再確認立即危險",
    "entities": {"location": null, "injured": null, "weapon": null, "danger_active": true}
  },
  "extracted": {
    "category": "暴力事件",
    "location": null,
    "people_injured": null,
    "weapon": null,
    "danger_active": true,
    "reporter_role": "旁觀者",
    "conscious": null,
    "breathing_difficulty": null,
    "fever": null,
    "symptom_summary": null,
    "dispatch_advice": "建議派遣：警察",
    "description": null
  }
}"""

SCENARIOS: Dict[str, List[Dict[str, str]]] = {
    "醫療急症": [
        {"name": "昏倒後恢復", "seed": "家人突然昏倒，第二輪說叫不醒，第三輪說醒了但很虛弱"},
        {"name": "呼吸困難", "seed": "爸爸胸痛喘不過氣，使用者很慌，後來說已撥119"},
        {"name": "燙傷處置", "seed": "小孩被熱湯燙傷，後來補充沒有水泡，想知道要不要送醫"},
        {"name": "中風疑似", "seed": "媽媽嘴歪、說話不清楚，使用者不確定是不是中風"},
        {"name": "短回答", "seed": "助理問意識，使用者只回答有、沒有、不確定"},
    ],
    "火災": [
        {"name": "煙味到撤離", "seed": "聞到煙味，第二輪看到濃煙，第三輪已經到出口附近"},
        {"name": "火已熄", "seed": "廚房起火，後來火滅了但還有煙味"},
        {"name": "瓦斯味", "seed": "樓下瓦斯味很重，使用者不知道能不能開燈"},
        {"name": "受困不確定", "seed": "看到大樓冒煙，不確定裡面有沒有人"},
        {"name": "已撥119", "seed": "使用者已撥119，仍害怕，不知道下一步"},
    ],
    "交通事故": [
        {"name": "車禍有人受傷", "seed": "車禍機車倒在路中，第二輪說有人流血，第三輪已撥119"},
        {"name": "無人受傷", "seed": "兩車擦撞，使用者後來說沒人受傷但車還在車道"},
        {"name": "傷者不要移動", "seed": "車禍傷者脖子痛，旁人想把他扶起來"},
        {"name": "模糊補充", "seed": "先說有人倒地，後來補充是被車撞"},
        {"name": "短回答", "seed": "助理問有沒有受傷，使用者回答沒有、不確定、有"},
    ],
    "暴力事件": [
        {"name": "沒有武器但仍危險", "seed": "樓下有人打架，第二輪說沒有武器，第三輪說還在推擠"},
        {"name": "持刀追人", "seed": "有人拿刀追人，使用者躲起來，不敢靠近"},
        {"name": "家暴旁觀", "seed": "隔壁疑似家暴，有哭叫聲，後來突然安靜"},
        {"name": "本人受害", "seed": "使用者被威脅或追趕，要先確認本人安全"},
        {"name": "緩和", "seed": "吵架衝突後警察到了，現在平靜但使用者仍害怕"},
    ],
    "可疑人士": [
        {"name": "試門把", "seed": "陌生人在門口試門把，後來說沒看到武器"},
        {"name": "尾隨", "seed": "有人一直跟著使用者，越走越近"},
        {"name": "已離開", "seed": "可疑人士走了，但使用者仍不安"},
        {"name": "看著我", "seed": "有人在外面看著使用者，不確定是不是危險"},
        {"name": "短回答", "seed": "助理問對方是否還在，使用者回答還在、走了、不確定"},
    ],
    "噪音": [
        {"name": "一般噪音", "seed": "樓上很吵，第二輪說只是音樂聲，第三輪管理員處理了"},
        {"name": "可能升級", "seed": "聽到吵架和摔東西聲，但不確定有沒有人受傷"},
        {"name": "小孩哭聲", "seed": "聽到小孩哭叫，使用者擔心但沒看到現場"},
        {"name": "深夜施工", "seed": "深夜施工噪音，使用者煩躁但沒有危險"},
        {"name": "模糊聲音", "seed": "外面很大聲，使用者不知道是噪音還是衝突"},
    ],
}

BAD_PHRASES = [
    "已經通知", "已通知", "我會通知", "我們會通知",
    "已經派遣", "已派遣", "我會派", "我們會馬上",
    "已經聯絡", "已聯絡警方", "已安排",
]
SIMPLIFIED_CHARS = "这那还没说个时间来问题处理通知确认"
ALLOWED_CATEGORIES = set(SCENARIOS) | {"待確認"}
ALLOWED_LEVELS = {"Low", "Medium", "High"}


def schema() -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ecare_v4_multiturn_record",
            "strict": False,
            "schema": {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "minItems": 7,
                        "maxItems": 7,
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                    }
                },
                "required": ["messages"],
            },
        },
    }


def assistant_payload(content: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def valid_record(record: Dict[str, Any]) -> tuple[bool, str]:
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) != 7:
        return False, "messages must contain exactly 7 turns"

    expected_roles = ["system", "user", "assistant", "user", "assistant", "user", "assistant"]
    roles = [m.get("role") for m in messages if isinstance(m, dict)]
    if roles != expected_roles:
        return False, f"roles mismatch: {roles}"

    if messages[0].get("content") != SYSTEM_PROMPT:
        messages[0]["content"] = SYSTEM_PROMPT

    questions: set[str] = set()
    for message in messages:
        content = str(message.get("content") or "")
        if message.get("role") == "assistant":
            if any(phrase in content for phrase in BAD_PHRASES):
                return False, "bad dispatch phrase"
            if sum(1 for ch in content if ch in SIMPLIFIED_CHARS) >= 3:
                return False, "too many simplified chars"
            payload = assistant_payload(content)
            if payload is None:
                return False, "assistant content is not JSON string"
            category = payload.get("extracted", {}).get("category")
            risk_level = payload.get("risk_level")
            if category not in ALLOWED_CATEGORIES:
                return False, f"bad category: {category}"
            if risk_level not in ALLOWED_LEVELS:
                return False, f"bad risk_level: {risk_level}"
            next_question = str(payload.get("next_question") or "").strip()
            if next_question and next_question in questions:
                return False, "repeated next_question"
            if next_question:
                questions.add(next_question)

            text = " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
            weapon = payload.get("extracted", {}).get("weapon")
            if any(term in text for term in ["沒有武器", "沒看到武器", "沒有看到武器"]) and weapon is True:
                return False, "weapon true despite negation"

    return True, "ok"


def build_prompt(category: str, scenario: Dict[str, str]) -> str:
    return (
        f"事件類別：{category}\n"
        f"場景名稱：{scenario['name']}\n"
        f"場景種子：{scenario['seed']}\n\n"
        "請生成自然口語的三輪對話。使用者每輪要提供新資訊，助理要承接前文，"
        "不要重複問同一件事。請讓回覆有同理心，但仍然短、清楚、可行。"
    )


def call_openai(api_key: str, model: str, category: str, scenario: Dict[str, str]) -> Optional[Dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": GENERATOR_PROMPT},
            {"role": "user", "content": build_prompt(category, scenario)},
        ],
        temperature=0.8,
        max_tokens=3500,
        response_format=schema(),
    )
    content = response.choices[0].message.content or "{}"
    try:
        record = json.loads(content)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def select_jobs(categories: Iterable[str], per_category: int, seed: int) -> List[tuple[str, Dict[str, str]]]:
    rng = random.Random(seed)
    jobs: List[tuple[str, Dict[str, str]]] = []
    for category in categories:
        pool = list(SCENARIOS[category])
        for _ in range(per_category):
            jobs.append((category, rng.choice(pool)))
    rng.shuffle(jobs)
    return jobs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--per-category", type=int, default=3)
    parser.add_argument("--category", action="append", choices=sorted(SCENARIOS), help="Generate only selected category; repeatable.")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ask-key", action="store_true", help="Prompt for OpenAI API key instead of reading environment.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned jobs without calling OpenAI.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    categories = args.category or list(SCENARIOS)
    jobs = select_jobs(categories, args.per_category, args.seed)

    print(f"model={args.model}")
    print(f"categories={','.join(categories)}")
    print(f"per_category={args.per_category}")
    print(f"output={args.output}")
    print(f"append={args.append}")

    if args.dry_run:
        for category, scenario in jobs[:20]:
            print(f"- {category}: {scenario['name']} / {scenario['seed']}")
        print(f"planned={len(jobs)}")
        return 0

    api_key = getpass.getpass("OpenAI API key: ") if args.ask_key else os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("請設定 OPENAI_API_KEY，或使用 --ask-key 臨時輸入。", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"

    accepted = failed = 0
    with output.open(mode, encoding="utf-8") as fh:
        for index, (category, scenario) in enumerate(jobs, start=1):
            print(f"[{index}/{len(jobs)}] {category} / {scenario['name']}...", end=" ", flush=True)
            try:
                record = call_openai(api_key, args.model, category, scenario)
            except Exception as exc:
                print(f"failed: {exc}")
                failed += 1
                time.sleep(args.delay)
                continue

            if record:
                ok, reason = valid_record(record)
            else:
                ok, reason = False, "empty or invalid JSON"

            if ok:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                accepted += 1
                print("OK")
            else:
                failed += 1
                print(f"rejected: {reason}")
            time.sleep(args.delay)

    print(f"\n完成：accepted={accepted}, failed={failed} -> {output}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
