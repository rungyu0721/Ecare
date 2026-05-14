"""Incident response guide helpers for safe, event-specific advice."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from backend.models import Extracted


@lru_cache(maxsize=1)
def load_incident_response_guides() -> dict[str, Any]:
    path = Path(__file__).parent.parent / "data" / "incident_response_guides.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term and term in text for term in terms)


def match_incident_response_guides(
    text: str,
    extracted: Optional[Extracted],
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Return compact guides that apply to the current event and user text."""

    normalized = text or ""
    category = extracted.category if extracted else None
    matched: list[dict[str, Any]] = []

    for guide in load_incident_response_guides().get("guides", []):
        categories = guide.get("applies_to_categories", [])
        category_match = not category or category in categories
        signal_match = _contains_any(normalized, guide.get("trigger_signals", []))
        structured_match = bool(
            extracted
            and (
                extracted.conscious is False
                or extracted.breathing_difficulty is True
                or extracted.people_injured is True
            )
            and category in categories
        )

        if not category_match or not (signal_match or structured_match):
            continue

        matched.append(
            {
                "id": guide.get("id"),
                "title": guide.get("title"),
                "only_if": guide.get("only_if", []),
                "important_notes": guide.get("important_notes", []),
                "priority_steps": guide.get("priority_steps", [])[:4],
                "avoid": guide.get("avoid", [])[:3],
                "reply_style": guide.get("reply_style", [])[:2],
                "source_refs": guide.get("source_refs", []),
            }
        )
        if len(matched) >= limit:
            break

    return matched
