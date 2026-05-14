#!/usr/bin/env python3
"""Generate candidate V4 semantic cases with the OpenAI API.

The output is review material, not production truth. Review candidates before
copying terms into backend/data/v4_semantic_lexicon.json or test case files.

Usage:
    $env:OPENAI_API_KEY = "sk-..."
    python scripts/generate_v4_semantic_candidates.py --per-category 20
    python scripts/generate_v4_semantic_candidates.py --category 醫療急症 --per-category 50
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = ROOT / "backend" / "data" / "v4_semantic_lexicon.json"
DEFAULT_OUTPUT = ROOT / "scripts" / "data" / "v4_semantic_candidates.jsonl"

CATEGORIES = ["暴力事件", "醫療急症", "火災", "交通事故", "可疑人士", "噪音"]
RISK_LEVELS = ["Low", "Medium", "High"]


def load_lexicon() -> Dict[str, Any]:
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


def chunks(total: int, batch_size: int) -> Iterable[int]:
    remaining = total
    while remaining > 0:
        size = min(batch_size, remaining)
        remaining -= size
        yield size


def build_prompt(category: str, count: int, lexicon: Dict[str, Any]) -> str:
    event = lexicon["events"][category]
    known_terms = {
        "category_terms": event.get("category_terms", [])[:40],
        "high_terms": event.get("high_terms", [])[:30],
        "medium_terms": event.get("medium_terms", [])[:30],
        "lower_terms": event.get("lower_terms", [])[:30],
        "slot_terms": event.get("slot_terms", {}),
    }
    return f"""
請替 E-CARE 緊急助理生成 {count} 筆「語意理解候選資料」。

事件類別：{category}
既有語意資料庫摘要：
{json.dumps(known_terms, ensure_ascii=False, indent=2)}

請產生真實使用者可能會說的繁體中文口語短句，包含：
- High 句子
- Medium 句子
- Low/已緩和句子
- 否定句，例如沒有受傷、沒有武器、火已經滅了
- 不確定句，例如不確定、好像、看不出來
- 使用者本人 vs 旁觀者 vs 家屬/照顧者
- 模糊句，例如「他看起來怪怪的」「外面好像不太對勁」

每筆都要標註 expected：
- category：只能是 {CATEGORIES}
- risk_level：只能是 Low / Medium / High
- people_injured：true / false / null
- weapon：true / false / null
- danger_active：true / false / null
- conscious：true / false / null
- breathing_difficulty：true / false / null
- reporter_role：本人 / 本人受害 / 旁觀者 / 照顧者/家屬 / 代他人通報 / null

規則：
- 不要產生太像範本的句子；要像一般人慌張時打字。
- 不要使用簡體字。
- 不要捏造 E-CARE 已派人或已通知警方。
- 如果句子其實應該被分類成其他事件，expected.category 要填真正類別。
- text 不要超過 45 個中文字。
- id 使用英文 snake_case，必須唯一。

只輸出 JSON，格式如下：
{{
  "items": [
    {{
      "id": "traffic_blocking_no_injury_01",
      "text": "剛剛車禍，車還在路中間但沒人受傷",
      "expected": {{
        "category": "交通事故",
        "risk_level": "Medium",
        "people_injured": false,
        "weapon": null,
        "danger_active": true,
        "conscious": null,
        "breathing_difficulty": null,
        "reporter_role": "旁觀者"
      }},
      "notes": "為何這樣標註，簡短說明"
    }}
  ]
}}
""".strip()


def response_schema() -> Dict[str, Any]:
    expected_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "category": {"type": "string", "enum": CATEGORIES},
            "risk_level": {"type": "string", "enum": RISK_LEVELS},
            "people_injured": {"type": ["boolean", "null"]},
            "weapon": {"type": ["boolean", "null"]},
            "danger_active": {"type": ["boolean", "null"]},
            "conscious": {"type": ["boolean", "null"]},
            "breathing_difficulty": {"type": ["boolean", "null"]},
            "reporter_role": {
                "type": ["string", "null"],
                "enum": ["本人", "本人受害", "旁觀者", "照顧者/家屬", "代他人通報", None],
            },
        },
        "required": [
            "category",
            "risk_level",
            "people_injured",
            "weapon",
            "danger_active",
            "conscious",
            "breathing_difficulty",
            "reporter_role",
        ],
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "v4_semantic_candidates",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "expected": expected_schema,
                                "notes": {"type": "string"},
                            },
                            "required": ["id", "text", "expected", "notes"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    }


def parse_json(content: str) -> Dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()
    return json.loads(content)


def call_openai(client: Any, model: str, category: str, count: int, lexicon: Dict[str, Any]) -> List[Dict[str, Any]]:
    prompt = build_prompt(category, count, lexicon)
    messages = [
        {
            "role": "system",
            "content": (
                "你是資料標註員，只輸出符合 schema 的 JSON。"
                "請用繁體中文生成台灣使用者可能輸入的緊急事件短句。"
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.9,
            max_tokens=5000,
            response_format=response_schema(),
        )
    except Exception:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.9,
            max_tokens=5000,
            response_format={"type": "json_object"},
        )
    content = response.choices[0].message.content or "{}"
    data = parse_json(content)
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def normalize_item(item: Dict[str, Any], category: str, index: int) -> Dict[str, Any]:
    expected = item.get("expected") if isinstance(item.get("expected"), dict) else {}
    normalized = {
        "id": str(item.get("id") or f"{category}_{index}"),
        "text": str(item.get("text") or "").strip(),
        "expected": {
            "category": expected.get("category") if expected.get("category") in CATEGORIES else category,
            "risk_level": expected.get("risk_level") if expected.get("risk_level") in RISK_LEVELS else "Medium",
            "people_injured": expected.get("people_injured"),
            "weapon": expected.get("weapon"),
            "danger_active": expected.get("danger_active"),
            "conscious": expected.get("conscious"),
            "breathing_difficulty": expected.get("breathing_difficulty"),
            "reporter_role": expected.get("reporter_role"),
        },
        "notes": str(item.get("notes") or "").strip(),
        "source": "openai",
        "review_status": "pending",
    }
    return normalized


def quality_ok(item: Dict[str, Any]) -> bool:
    text = item.get("text", "")
    if not text or len(text) > 80:
        return False
    if any(ch in text for ch in "这还说个问题处理确认"):
        return False
    expected = item.get("expected", {})
    return expected.get("category") in CATEGORIES and expected.get("risk_level") in RISK_LEVELS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--category", default="all", help="all or one V4 category")
    parser.add_argument("--per-category", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print planned categories without calling the API.")
    args = parser.parse_args()

    categories = CATEGORIES if args.category == "all" else [args.category]
    invalid = [category for category in categories if category not in CATEGORIES]
    if invalid:
        raise SystemExit(f"unknown category: {', '.join(invalid)}")

    lexicon = load_lexicon()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"model={args.model}")
    print(f"categories={', '.join(categories)}")
    print(f"per_category={args.per_category} batch_size={args.batch_size}")
    print(f"output={output}")

    if args.dry_run:
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("請先設定 OPENAI_API_KEY，例如：$env:OPENAI_API_KEY='sk-...'")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    mode = "a" if args.append else "w"
    total = 0
    seen_texts: set[str] = set()

    with output.open(mode, encoding="utf-8") as fh:
        for category in categories:
            generated_for_category = 0
            for batch_count in chunks(args.per_category, args.batch_size):
                print(f"[{category}] generating {batch_count}...", end=" ", flush=True)
                items = call_openai(client, args.model, category, batch_count, lexicon)
                accepted = 0
                for item in items:
                    normalized = normalize_item(item, category, total + accepted + 1)
                    text = normalized["text"]
                    if text in seen_texts or not quality_ok(normalized):
                        continue
                    seen_texts.add(text)
                    fh.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                    accepted += 1
                generated_for_category += accepted
                total += accepted
                print(f"accepted={accepted}")
                time.sleep(args.delay)
            print(f"[{category}] total accepted={generated_for_category}")

    print(f"\n完成：{total} 筆候選資料 -> {output}")
    print("下一步：人工審核 review_status=pending 的資料，再挑選加入 v4_semantic_cases.jsonl 或 v4_semantic_lexicon.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
