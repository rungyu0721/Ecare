"""
急救知識資料服務：從 first_aid_guides.json 載入並提供急救指引文字。
"""

import json
from pathlib import Path
from typing import Optional

_GUIDES_PATH = Path(__file__).parent.parent / "data" / "first_aid_guides.json"
_guides: Optional[dict] = None


def _load() -> dict:
    global _guides
    if _guides is None:
        with _GUIDES_PATH.open(encoding="utf-8") as f:
            _guides = json.load(f)
    return _guides


def get_guide(key: str) -> tuple[str, str]:
    """Return (reply, advice) for the given scenario key."""
    entry = _load().get(key, {})
    return entry.get("reply", ""), entry.get("advice", "")
