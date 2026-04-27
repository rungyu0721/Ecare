"""地點解析：地址正規化、品質評分、位置回應判斷。"""

import re
from typing import Any, Dict, List, Optional

from backend.services.risk import INCIDENT_DESCRIPTION_KEYWORDS

VAGUE_LOCATION_PHRASES = {
    "我旁邊", "旁邊", "這裡", "那裡", "附近", "現場",
    "我這裡", "我這邊", "這邊", "那邊", "身邊",
}

LOCATION_HINT_TOKENS = {
    "縣", "市", "鄉", "鎮", "區", "村", "里",
    "路", "街", "段", "巷", "弄", "號", "樓",
}

LANDMARK_HINT_TOKENS = {
    "門口", "樓下", "樓上", "家裡", "家中", "住家", "公司", "學校",
    "校門口", "教室", "宿舍", "公園", "車站", "捷運站", "超商",
    "便利商店", "醫院", "診所", "市場", "巷口", "路口",
}


def normalize_location_candidate(text: str) -> Optional[str]:
    candidate = text.strip(" ：:，,。.？?！!；;、\n\t")
    if not candidate:
        return None

    for prefix in ["我在", "目前在", "現在在", "人在", "在", "於"]:
        if candidate.startswith(prefix) and len(candidate) > len(prefix):
            candidate = candidate[len(prefix):].strip(" ：:，,。.？?！!；;、\n\t")
            break

    if not candidate:
        return None

    if candidate in VAGUE_LOCATION_PHRASES:
        return None

    if any(
        candidate.startswith(prefix)
        for prefix in ["我旁邊", "旁邊", "附近", "這裡", "那裡", "現場"]
    ):
        return None

    return candidate


def location_quality_score(text: Optional[str]) -> int:
    if not text:
        return -1
    candidate = text.strip()
    if not candidate:
        return -1

    score = min(len(candidate), 12)

    if any(token in candidate for token in ["縣", "市", "鄉", "鎮", "區", "村", "里", "路", "街", "段", "巷", "弄", "號", "樓"]):
        score += 8
    if any(token in candidate for token in LANDMARK_HINT_TOKENS):
        score += 6
    if "+/-" in candidate and "," in candidate:
        score += 10
    if any(token in candidate for token in INCIDENT_DESCRIPTION_KEYWORDS):
        score -= 10
    if any(token in candidate for token in ["現在在", "目前在", "人在", "地上", "有人", "對方"]):
        score -= 6
    if any(token in candidate for token in ["，", ",", "。", "；", ";"]):
        score -= 6
    if candidate.isdigit():
        score -= 12
    elif len(candidate) <= 3 and any(char.isdigit() for char in candidate):
        score -= 8

    return score


def has_strong_location_signal(text: str) -> bool:
    candidate = normalize_location_candidate(text)
    if not candidate:
        return False
    if any(token in candidate for token in INCIDENT_DESCRIPTION_KEYWORDS):
        return False
    if any(token in candidate for token in LOCATION_HINT_TOKENS):
        return True
    if any(token in candidate for token in LANDMARK_HINT_TOKENS):
        return True
    return bool(re.search(r"\d", candidate) and any(token in candidate for token in ["巷", "弄", "號", "樓"]))


def is_likely_location_response(text: str) -> bool:
    candidate = normalize_location_candidate(text)
    if not candidate:
        return False
    if any(token in candidate for token in INCIDENT_DESCRIPTION_KEYWORDS):
        return False
    return has_strong_location_signal(candidate) or location_quality_score(candidate) >= 14


def extract_location_from_text(text: str) -> Optional[str]:
    candidates: List[str] = []

    for key in ["地址是", "地點是", "位於", "目前在", "現在在", "人在", "在"]:
        start = 0
        while True:
            idx = text.find(key, start)
            if idx < 0:
                break
            raw_segment = text[idx + len(key): idx + len(key) + 30]
            parts = [raw_segment] + re.split(r"[，,。！？；;\n]", raw_segment)
            for part in parts:
                candidate = normalize_location_candidate(part)
                if candidate and is_likely_location_response(candidate):
                    candidates.append(candidate)
            start = idx + len(key)

    if not candidates:
        return None

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(
        key=lambda c: (location_quality_score(c), len(c)),
        reverse=True,
    )
    return candidates[0]


def get_client_location_text(audio_context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not audio_context:
        return None

    client_location = audio_context.get("client_location")
    if not isinstance(client_location, dict):
        return None

    for key in ["address", "display_text"]:
        value = client_location.get(key)
        if isinstance(value, str):
            normalized = normalize_location_candidate(value)
            if normalized:
                return normalized

    latitude = client_location.get("latitude")
    longitude = client_location.get("longitude")
    accuracy = client_location.get("accuracy")
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        if isinstance(accuracy, (int, float)):
            return f"{latitude:.6f}, {longitude:.6f} (+/- {round(accuracy)}m)"
        return f"{latitude:.6f}, {longitude:.6f}"

    return None
