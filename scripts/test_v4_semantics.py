#!/usr/bin/env python3
"""Check V4 event semantic extraction and risk rules against JSONL cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.extraction.entities import simple_extract  # noqa: E402
from backend.services.risk import apply_structured_risk_floor, simple_risk  # noqa: E402


RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2}


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
            cases.append(case)
    return cases


def risk_matches(actual: str, expected: str, mode: str) -> bool:
    if mode == "exact":
        return actual == expected
    if mode == "at_least":
        return RISK_ORDER.get(actual, -1) >= RISK_ORDER.get(expected, -1)
    if mode == "at_most":
        return RISK_ORDER.get(actual, 99) <= RISK_ORDER.get(expected, 99)
    raise ValueError(f"unknown risk mode: {mode}")


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


def check_case(case: Dict[str, Any], *, risk_mode: str) -> List[str]:
    text = str(case.get("text") or "").strip()
    expected = case.get("expected") or {}
    if not text:
        return ["missing text"]
    if not isinstance(expected, dict):
        return ["expected must be an object"]

    actual = actual_payload(text)
    failures: List[str] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key == "risk_level":
            if not risk_matches(str(actual_value), str(expected_value), risk_mode):
                failures.append(f"{key}: expected {risk_mode} {expected_value!r}, got {actual_value!r}")
        elif actual_value != expected_value:
            failures.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default="scripts/data/v4_semantic_cases.jsonl",
        help="Path to JSONL semantic test cases.",
    )
    parser.add_argument(
        "--risk-mode",
        choices=["exact", "at_least", "at_most"],
        default="exact",
        help="How to compare expected risk_level values.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print passing cases too.")
    args = parser.parse_args()

    path = Path(args.path)
    cases = load_cases(path)
    failed = 0

    for case in cases:
        failures = check_case(case, risk_mode=args.risk_mode)
        if failures:
            failed += 1
            print(f"FAIL {case['id']}: {case.get('text')}")
            for failure in failures:
                print(f"  - {failure}")
            print(f"  actual: {actual_payload(str(case.get('text') or ''))}")
        elif args.verbose:
            print(f"PASS {case['id']}: {case.get('text')}")

    passed = len(cases) - failed
    print(f"\nV4 semantic cases: {passed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
