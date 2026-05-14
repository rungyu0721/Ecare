#!/usr/bin/env python3
"""Check V4 multi-turn context handling for short follow-up answers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models import ChatMessage  # noqa: E402
from backend.services.extraction.entities import simple_extract  # noqa: E402
from backend.services.postprocess import contextualize_reply_and_question  # noqa: E402


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


def as_messages(raw_messages: List[Dict[str, str]]) -> List[ChatMessage]:
    return [
        ChatMessage(role=str(message["role"]), content=str(message["content"]))
        for message in raw_messages
    ]


def actual_payload(case: Dict[str, Any]) -> Dict[str, Any]:
    extracted = simple_extract(str(case.get("seed_text") or ""))
    reply, next_question = contextualize_reply_and_question(
        as_messages(case.get("messages") or []),
        extracted,
        str(case.get("llm_reply") or ""),
        str(case.get("llm_next_question") or ""),
        str(case.get("risk_level") or "Low"),
    )
    return {
        "reply": reply,
        "next_question": next_question,
        "category": extracted.category,
        "people_injured": extracted.people_injured,
        "weapon": extracted.weapon,
        "danger_active": extracted.danger_active,
        "conscious": extracted.conscious,
        "breathing_difficulty": extracted.breathing_difficulty,
        "dispatch_advice": extracted.dispatch_advice,
    }


def check_case(case: Dict[str, Any]) -> List[str]:
    expected = case.get("expected") or {}
    if not isinstance(expected, dict):
        return ["expected must be an object"]

    actual = actual_payload(case)
    failures: List[str] = []

    for key, expected_value in expected.items():
        if key == "reply_contains":
            for token in expected_value:
                if token not in actual["reply"]:
                    failures.append(f"reply missing {token!r}: {actual['reply']!r}")
        elif key == "next_question_contains":
            for token in expected_value:
                if token not in actual["next_question"]:
                    failures.append(f"next_question missing {token!r}: {actual['next_question']!r}")
        elif key == "reply_not_contains":
            for token in expected_value:
                if token in actual["reply"]:
                    failures.append(f"reply should not contain {token!r}: {actual['reply']!r}")
        elif key == "next_question_not_contains":
            for token in expected_value:
                if token in actual["next_question"]:
                    failures.append(
                        f"next_question should not contain {token!r}: {actual['next_question']!r}"
                    )
        else:
            actual_value = actual.get(key)
            if actual_value != expected_value:
                failures.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default="scripts/data/v4_context_cases.jsonl",
        help="Path to JSONL context test cases.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print passing cases too.")
    args = parser.parse_args()

    cases = load_cases(Path(args.path))
    failed = 0

    for case in cases:
        failures = check_case(case)
        if failures:
            failed += 1
            print(f"FAIL {case['id']}: seed={case.get('seed_text')!r}")
            for failure in failures:
                print(f"  - {failure}")
            print(f"  actual: {actual_payload(case)}")
        elif args.verbose:
            print(f"PASS {case['id']}")

    passed = len(cases) - failed
    print(f"\nV4 context cases: {passed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
