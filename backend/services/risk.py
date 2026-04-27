"""
風險評分模組：關鍵字集合、訊號偵測、風險計算。
"""

import json
import random
import re
from pathlib import Path
from typing import List


# ======================
# 關鍵字集合（從 data/keywords.json 載入）
# ======================

def _load_keywords() -> dict:
    path = Path(__file__).parent.parent / "data" / "keywords.json"
    return json.loads(path.read_text(encoding="utf-8"))


_kw = _load_keywords()

DISTURBANCE_KEYWORDS: set = set(_kw["disturbance"])
AGGRESSIVE_DISTURBANCE_KEYWORDS: set = set(_kw["aggressive_disturbance"])
SUSPICIOUS_ACTIVITY_KEYWORDS: set = set(_kw["suspicious_activity"])
VIOLENCE_SIGNAL_KEYWORDS: set = set(_kw["violence_signal"])
INCIDENT_DESCRIPTION_KEYWORDS: set = set(_kw["incident_description"])
ACUTE_MEDICAL_HIGH_KEYWORDS: set = set(_kw["acute_medical_high"])
CRITICAL_INJURY_HIGH_KEYWORDS: set = set(_kw["critical_injury_high"])
MEDICAL_URGENCY_KEYWORDS: set = set(_kw["medical_urgency"])
MINOR_INJURY_KEYWORDS: set = set(_kw["minor_injury"])
DIRECT_HIGH_RISK_PHRASES: set = set(_kw["direct_high_risk"])
MEDIUM_ALERT_KEYWORDS: set = set(_kw["medium_alert"])

# ======================
# 風險訊號正規表達式
# ======================

VIOLENCE_HIGH_CONTEXT_PATTERNS = [
    re.compile(r"(有人|對方|那個人|有個人|一個人)?.{0,3}(拿刀|持刀|有刀|拿著刀|手上有刀|有武器|拿槍|持槍)"),
    re.compile(r"(拿刀|持刀|有刀|拿槍|持槍).{0,8}(追我|追人|靠近|在門口|在外面|在我家|闖進來|威脅|要砍|要殺|攻擊|衝過來)"),
    re.compile(r"(要|想|準備|一直在).{0,3}(砍|殺|攻擊|傷害)"),
    re.compile(r"(被|正在被).{0,3}(打|砍|威脅)"),
]

DISTURBANCE_CONTEXT_PATTERNS = [
    re.compile(r"(大|一直|不停|持續|高聲|狂).{0,2}(叫|喊|吼)"),
    re.compile(r"(叫|喊|吼).{0,4}(很大聲|不停|一直|持續)"),
    re.compile(r"(在我旁邊|在旁邊|在附近).{0,6}(大叫|叫喊|吼叫|大聲叫|大聲吼)"),
]

MEDICAL_HIGH_CONTEXT_PATTERNS = [
    re.compile(r"(呼吸困難|喘不過氣).{0,8}(很嚴重|越來越嚴重|快不行|快不能呼吸|臉發紫|嘴唇發紫)"),
    re.compile(r"(叫不醒|失去意識|沒呼吸).{0,6}(怎麼辦|快點|救命)"),
]

TRAFFIC_HIGH_CONTEXT_PATTERNS = [
    re.compile(r"(車禍|撞車|翻車|追撞).{0,8}(有人受傷|流血|受困|卡住)"),
]


# ======================
# 訊號偵測函式
# ======================

def contains_any_keyword(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def has_disturbance_signal(text: str) -> bool:
    return any(keyword in text for keyword in DISTURBANCE_KEYWORDS) or any(
        pattern.search(text) for pattern in DISTURBANCE_CONTEXT_PATTERNS
    )


def has_aggressive_disturbance_signal(text: str) -> bool:
    return any(keyword in text for keyword in AGGRESSIVE_DISTURBANCE_KEYWORDS) or any(
        pattern.search(text) for pattern in DISTURBANCE_CONTEXT_PATTERNS
    )


def compact_signal_text(text: str) -> str:
    return re.sub(r"[、,，。.\s]+", "", text.strip())


def is_repeated_alert_noise(text: str) -> bool:
    compact = compact_signal_text(text)
    if not compact:
        return False
    for token in ["刀", "槍", "血", "火", "救", "救命"]:
        if len(compact) < len(token) * 3 or len(compact) % len(token) != 0:
            continue
        if compact == token * (len(compact) // len(token)):
            return True
    return False


def has_contextual_pattern(text: str, patterns: List[re.Pattern]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def has_high_risk_context_signal(text: str) -> bool:
    if any(phrase in text for phrase in DIRECT_HIGH_RISK_PHRASES):
        return True
    return any([
        has_contextual_pattern(text, VIOLENCE_HIGH_CONTEXT_PATTERNS),
        has_contextual_pattern(text, MEDICAL_HIGH_CONTEXT_PATTERNS),
        has_contextual_pattern(text, TRAFFIC_HIGH_CONTEXT_PATTERNS),
    ])


def has_active_violence_emergency(text: str) -> bool:
    if any(keyword in text for keyword in ["打架", "闖入", "家暴", "被打"]):
        return True
    return has_contextual_pattern(text, VIOLENCE_HIGH_CONTEXT_PATTERNS)


def has_acute_medical_signal(text: str) -> bool:
    return any(keyword in text for keyword in ACUTE_MEDICAL_HIGH_KEYWORDS)


def has_critical_injury_signal(text: str) -> bool:
    if any(keyword in text for keyword in CRITICAL_INJURY_HIGH_KEYWORDS):
        return True
    return "流血" in text and any(
        keyword in text
        for keyword in ["倒地", "倒在地上", "昏倒", "失去意識", "叫不醒", "沒呼吸", "重傷"]
    )


def has_medical_urgency_signal(text: str) -> bool:
    return any(keyword in text for keyword in MEDICAL_URGENCY_KEYWORDS)


def has_minor_injury_signal(text: str) -> bool:
    return any(keyword in text for keyword in MINOR_INJURY_KEYWORDS)


# ======================
# 風險計算
# ======================

def risk_level_from_score(score: float) -> str:
    if score > 0.8:
        return "High"
    if score > 0.5:
        return "Medium"
    return "Low"


def simple_risk(text: str):
    score = 0.2

    if has_high_risk_context_signal(text):
        score = 0.9
    elif has_aggressive_disturbance_signal(text):
        score = 0.6
    elif is_repeated_alert_noise(text):
        score = 0.55
    elif any(k in text for k in MEDIUM_ALERT_KEYWORDS):
        score = 0.6

    score += random.uniform(-0.03, 0.03)
    score = max(0.0, min(1.0, score))

    level = risk_level_from_score(score)
    return score, level


def apply_structured_risk_floor(
    text: str,
    ex,  # Extracted — 避免循環 import，用 Any 型別
    risk_score: float,
    risk_level: str,
) -> tuple:
    score = max(0.0, min(1.0, float(risk_score)))
    level = risk_level if risk_level in ["Low", "Medium", "High"] else risk_level_from_score(score)

    if ex.category == "醫療急症":
        if (
            ex.breathing_difficulty is True
            or ex.conscious is False
            or has_acute_medical_signal(text)
            or has_critical_injury_signal(text)
        ):
            score = max(score, 0.9)
        elif ex.fever is True or has_medical_urgency_signal(text) or ex.people_injured is True:
            score = max(score, 0.62)

    if ex.category in ["暴力事件", "交通事故"]:
        if has_active_violence_emergency(text) or has_critical_injury_signal(text):
            score = max(score, 0.88)
        elif ex.weapon is True:
            score = max(score, 0.62)
        elif ex.people_injured is True:
            score = max(score, 0.68)

    if ex.category == "火災" and (ex.people_injured is True or ex.danger_active is True):
        score = max(score, 0.88)

    level = risk_level_from_score(score)
    return score, level
