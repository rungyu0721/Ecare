#!/usr/bin/env python3
"""Evaluate OpenAI-generated V4 semantic candidates against current rules.

This script is intentionally review-oriented: a mismatch can mean either
the backend needs more lexicon terms or the candidate label needs correction.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.extraction.entities import simple_extract  # noqa: E402
from backend.services.risk import apply_structured_risk_floor, simple_risk  # noqa: E402


RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2}
DEFAULT_IGNORE_KEYS = {"reporter_role"}


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            case.setdefault("id", f"line_{line_no}")
            case.setdefault("_line_no", line_no)
            cases.append(case)
    return cases


def actual_payload(text: str) -> Dict[str, Any]:
    extracted = simple_extract(text)
    score, level = simple_risk(text)
    score, level = apply_structured_risk_floor(text, extracted, score, level)
    return {
        "category": extracted.category,
        "risk_level": level,
        "risk_score": round(score, 3),
        "people_injured": extracted.people_injured,
        "weapon": extracted.weapon,
        "danger_active": extracted.danger_active,
        "conscious": extracted.conscious,
        "breathing_difficulty": extracted.breathing_difficulty,
        "fever": extracted.fever,
        "reporter_role": extracted.reporter_role,
        "symptom_summary": extracted.symptom_summary,
        "dispatch_advice": extracted.dispatch_advice,
    }


def risk_matches(actual: str, expected: str, mode: str) -> bool:
    if mode == "exact":
        return actual == expected
    if mode == "at_least":
        return RISK_ORDER.get(actual, -1) >= RISK_ORDER.get(expected, -1)
    if mode == "at_most":
        return RISK_ORDER.get(actual, 99) <= RISK_ORDER.get(expected, 99)
    raise ValueError(f"unknown risk mode: {mode}")


def compare_case(
    case: Dict[str, Any],
    *,
    keys: Optional[Iterable[str]],
    ignore_keys: set[str],
    risk_mode: str,
) -> List[str]:
    text = str(case.get("text") or "").strip()
    expected = case.get("expected") or {}
    if not text:
        return ["missing text"]
    if not isinstance(expected, dict):
        return ["expected must be an object"]

    actual = actual_payload(text)
    check_keys = list(keys) if keys else list(expected.keys())
    failures: List[str] = []
    for key in check_keys:
        if key in ignore_keys or key not in expected:
            continue
        expected_value = expected.get(key)
        actual_value = actual.get(key)
        if key == "risk_level":
            if not risk_matches(str(actual_value), str(expected_value), risk_mode):
                failures.append(f"{key}: expected {risk_mode} {expected_value!r}, got {actual_value!r}")
        elif actual_value != expected_value:
            failures.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")
    return failures


def write_review_outputs(
    *,
    accepted_path: Path,
    review_path: Path,
    accepted: List[Dict[str, Any]],
    review: List[Dict[str, Any]],
) -> None:
    accepted_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with accepted_path.open("w", encoding="utf-8") as fh:
        for case in accepted:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    with review_path.open("w", encoding="utf-8") as fh:
        for case in review:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default="scripts/data/v4_semantic_candidates.jsonl",
        help="Path to generated candidate JSONL.",
    )
    parser.add_argument(
        "--keys",
        nargs="+",
        default=["category", "risk_level", "people_injured", "weapon", "danger_active", "conscious", "breathing_difficulty"],
        help="Expected keys to compare.",
    )
    parser.add_argument(
        "--ignore-keys",
        nargs="*",
        default=sorted(DEFAULT_IGNORE_KEYS),
        help="Keys to ignore even if present in --keys.",
    )
    parser.add_argument(
        "--risk-mode",
        choices=["exact", "at_least", "at_most"],
        default="exact",
        help="How to compare expected risk_level values.",
    )
    parser.add_argument("--show", type=int, default=20, help="Max failures to print.")
    parser.add_argument("--verbose", action="store_true", help="Print passing cases too.")
    parser.add_argument("--write-review-files", action="store_true", help="Write accepted/review JSONL split files.")
    parser.add_argument("--accepted-output", default="scripts/data/v4_semantic_candidates.accepted.jsonl")
    parser.add_argument("--review-output", default="scripts/data/v4_semantic_candidates.review.jsonl")
    args = parser.parse_args()

    cases = load_cases(Path(args.path))
    ignore_keys = set(args.ignore_keys or [])
    category_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    by_category_failures: Dict[str, int] = defaultdict(int)
    accepted: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []

    printed = 0
    for case in cases:
        expected = case.get("expected") or {}
        category = str(expected.get("category") or "未知")
        category_counts[category] += 1
        failures = compare_case(
            case,
            keys=args.keys,
            ignore_keys=ignore_keys,
            risk_mode=args.risk_mode,
        )
        if failures:
            enriched = dict(case)
            enriched["actual"] = actual_payload(str(case.get("text") or ""))
            enriched["review_status"] = "needs_review"
            enriched["mismatches"] = failures
            review.append(enriched)
            by_category_failures[category] += 1
            for failure in failures:
                failure_counts[failure.split(":", 1)[0]] += 1
            if printed < args.show:
                printed += 1
                print(f"REVIEW {case['id']}: {case.get('text')}")
                for failure in failures:
                    print(f"  - {failure}")
                print(f"  actual: {enriched['actual']}")
        else:
            enriched = dict(case)
            enriched["review_status"] = "rule_passed"
            accepted.append(enriched)
            if args.verbose:
                print(f"PASS {case['id']}: {case.get('text')}")

    if args.write_review_files:
        write_review_outputs(
            accepted_path=Path(args.accepted_output),
            review_path=Path(args.review_output),
            accepted=accepted,
            review=review,
        )

    total = len(cases)
    print()
    print(f"Candidates: {len(accepted)}/{total} passed current rules")
    print("By expected category:")
    for category, count in sorted(category_counts.items()):
        failed = by_category_failures.get(category, 0)
        print(f"  {category}: {count - failed}/{count} passed")
    if failure_counts:
        print("Mismatch keys:")
        for key, count in failure_counts.most_common():
            print(f"  {key}: {count}")
    if args.write_review_files:
        print(f"Accepted output: {args.accepted_output}")
        print(f"Review output: {args.review_output}")

    return 1 if review else 0


if __name__ == "__main__":
    raise SystemExit(main())
