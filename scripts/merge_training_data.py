#!/usr/bin/env python3
"""
合併並清理 E-CARE 訓練資料，輸出 ecare_train_v4_final.jsonl。

用法：
    python scripts/merge_training_data.py

預設行為：
    1. 讀取 scripts/data/ 底下所有 .jsonl 檔
    2. 對每筆資料執行品質過濾（_quality_ok）
    3. 去除完全重複的 messages
    4. 隨機打散後輸出到 scripts/data/ecare_train_v4_final.jsonl

選項：
    --input   指定要合併的 .jsonl 檔（可多個，空白分隔），預設掃描 scripts/data/
    --output  輸出路徑，預設 scripts/data/ecare_train_v4_final.jsonl
    --no-v3   跳過 ecare_train_v3.jsonl（全部重新用 v4 資料）
    --seed    隨機種子（預設 42）
"""

import argparse
import json
import random
from pathlib import Path

# 品質過濾規則（與 generate_training_data.py 一致）
_BAD_PHRASES = [
    "已經通知", "已通知", "我會通知", "我們會通知",
    "已經派遣", "已派遣", "我會派", "我們會馬上",
    "已經聯絡", "已聯絡警方", "已安排",
]
_SIMPLIFIED_CHARS = "这那还没说个时间来问题处理通知确认"


def _quality_ok(turns: list) -> bool:
    for turn in turns:
        if turn.get("role") != "assistant":
            continue
        content = turn.get("content", "")
        if any(phrase in content for phrase in _BAD_PHRASES):
            return False
        if sum(1 for ch in content if ch in _SIMPLIFIED_CHARS) >= 3:
            return False
    return True


def _fingerprint(record: dict) -> str:
    """用前兩輪 user content 做去重 key。"""
    msgs = record.get("messages", [])
    user_turns = [m["content"] for m in msgs if m.get("role") == "user"]
    return "||".join(user_turns[:2])


def load_file(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", nargs="+", default=None,
        help="指定輸入檔案（預設掃描 scripts/data/*.jsonl）"
    )
    parser.add_argument(
        "--output", default="scripts/data/ecare_train_v4_final.jsonl"
    )
    parser.add_argument(
        "--no-v3", action="store_true",
        help="跳過 ecare_train_v3.jsonl"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_dir = Path("scripts/data")

    # 決定輸入檔清單
    if args.input:
        input_files = [Path(p) for p in args.input]
    else:
        input_files = sorted(data_dir.glob("*.jsonl"))

    # 排除輸出檔自身，避免循環
    output_path = Path(args.output)
    input_files = [f for f in input_files if f.resolve() != output_path.resolve()]

    # 排除 v3（若指定 --no-v3）
    if args.no_v3:
        input_files = [f for f in input_files if "v3" not in f.name]

    print(f"輸入檔案（{len(input_files)} 個）：")
    for f in input_files:
        print(f"  {f.name}")
    print()

    seen: set[str] = set()
    accepted: list[dict] = []
    stats: dict[str, dict] = {}

    for path in input_files:
        if not path.exists():
            print(f"[略過] 找不到 {path}")
            continue

        records = load_file(path)
        ok = bad = dup = 0

        for rec in records:
            turns = [m for m in rec.get("messages", []) if m.get("role") != "system"]

            if not _quality_ok(turns):
                bad += 1
                continue

            fp = _fingerprint(rec)
            if fp in seen:
                dup += 1
                continue

            seen.add(fp)
            accepted.append(rec)
            ok += 1

        stats[path.name] = {"total": len(records), "ok": ok, "bad": bad, "dup": dup}

    # 隨機打散
    random.seed(args.seed)
    random.shuffle(accepted)

    # 輸出
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for rec in accepted:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 報告
    print("=" * 50)
    print(f"{'檔案':<38} {'總計':>5} {'通過':>5} {'壞樣':>5} {'重複':>5}")
    print("-" * 50)
    for name, s in stats.items():
        print(f"{name:<38} {s['total']:>5} {s['ok']:>5} {s['bad']:>5} {s['dup']:>5}")
    print("=" * 50)
    print(f"最終輸出：{len(accepted)} 筆 → {output_path}")


if __name__ == "__main__":
    main()
