"""
風險評分模組：關鍵字集合、訊號偵測、風險計算。
"""

import json
import random
import re
from pathlib import Path
from typing import List

from backend.services.incident_taxonomy import match_incident_taxonomy
from backend.services.v4_event_semantics import contains_negated, contains_uncertain, v4_risk_ceiling, v4_risk_floor


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
    re.compile(r"(呼吸困難|喘不過氣|吸不到氣|很喘).{0,8}(很嚴重|越來越嚴重|快不行|快不能呼吸|快沒氣|臉發紫|嘴唇發紫)"),
    re.compile(r"(叫不醒|失去意識|沒呼吸|沒有呼吸|沒反應|沒有反應|暈過去|昏過去).{0,6}(怎麼辦|快點|救命)?"),
    re.compile(r"(胸痛|胸悶|心臟痛).{0,8}(冒冷汗|手麻|喘|喘不過氣|很痛|壓迫感)"),
    re.compile(r"(半邊無力|嘴歪|講話不清楚|口齒不清|突然說不清楚)"),
    re.compile(r"(燙傷|燒傷|灼傷|燙到|燒到).{0,12}(嚴重|面積很大|大面積|很大一片|焦黑|發白|臉|手掌|關節|生殖器|化學|觸電)"),
    re.compile(r"(燙傷|燒傷|灼傷|燙到|燒到).{0,12}(?<!沒)(?<!沒有)(起水泡|有水泡|皮膚起水泡|水泡很大)"),
]

TRAFFIC_HIGH_CONTEXT_PATTERNS = [
    re.compile(r"(車禍|撞車|翻車|追撞|被車撞|撞到人).{0,8}(有人受傷|流血|受困|卡住|倒地|暈倒)"),
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


def has_ongoing_disturbance_signal(text: str) -> bool:
    disturbance_terms = ["吵架", "爭吵", "大吼大叫", "叫囂", "咆哮", "怒吼", "吼叫"]
    ongoing_terms = ["持續", "還在", "仍在", "一直", "沒有停", "現在還", "還沒停"]
    return any(term in text for term in disturbance_terms) and any(
        term in text for term in ongoing_terms
    )


def has_child_distress_signal(text: str) -> bool:
    child_terms = ["小孩", "孩子", "兒童", "幼童", "嬰兒", "寶寶"]
    distress_terms = ["哭", "哭聲", "哀號", "哭叫", "尖叫", "求救", "慘叫", "一直哭"]
    neighbor_terms = ["隔壁", "樓上", "樓下", "鄰居"]
    return (
        any(term in text for term in child_terms)
        and any(term in text for term in distress_terms)
    ) or (
        any(term in text for term in neighbor_terms)
        and any(term in text for term in distress_terms)
    )


def has_child_unresponsive_signal(text: str) -> bool:
    child_terms = ["小孩", "孩子", "兒童", "幼童", "嬰兒", "寶寶", "他", "她"]
    unresponsive_terms = ["沒反應", "沒有反應", "無反應", "叫不醒", "昏倒", "暈倒", "暈過去", "昏過去", "失去意識", "意識不清"]
    return any(term in text for term in child_terms) and any(
        term in text for term in unresponsive_terms
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
    if has_child_unresponsive_signal(text):
        return True
    if any(phrase in text for phrase in DIRECT_HIGH_RISK_PHRASES):
        return True
    weapon_terms = ["刀", "槍", "武器", "棍棒", "球棒", "鐵棍"]
    has_weapon_negation = contains_negated(text, weapon_terms) or contains_uncertain(text, weapon_terms)
    return any([
        (not has_weapon_negation and has_contextual_pattern(text, VIOLENCE_HIGH_CONTEXT_PATTERNS)),
        has_contextual_pattern(text, MEDICAL_HIGH_CONTEXT_PATTERNS),
        has_contextual_pattern(text, TRAFFIC_HIGH_CONTEXT_PATTERNS),
    ])


def has_active_violence_emergency(text: str) -> bool:
    child_distress = (
        any(keyword in text for keyword in ["小孩", "孩子", "兒童", "幼童", "嬰兒"])
        and any(keyword in text for keyword in ["哭", "哭聲", "哀號", "哭叫", "尖叫", "求救", "慘叫", "一直哭"])
    )
    neighbor_distress = (
        any(keyword in text for keyword in ["隔壁", "樓上", "樓下", "鄰居"])
        and any(keyword in text for keyword in ["哭", "哭聲", "哀號", "哭叫", "尖叫", "求救", "慘叫", "一直哭"])
    )
    if child_distress or neighbor_distress:
        return True
    if any(keyword in text for keyword in ["打架", "闖入", "家暴", "被打", "虐待", "受虐", "打小孩", "打罵"]):
        return True
    return has_contextual_pattern(text, VIOLENCE_HIGH_CONTEXT_PATTERNS)


def has_acute_medical_signal(text: str) -> bool:
    return any(keyword in text for keyword in ACUTE_MEDICAL_HIGH_KEYWORDS)


def has_critical_injury_signal(text: str) -> bool:
    if any(keyword in text for keyword in CRITICAL_INJURY_HIGH_KEYWORDS):
        return True
    if any(keyword in text for keyword in ["沒反應", "沒有反應", "無反應", "叫不醒", "失去意識", "意識不清", "暈過去", "昏過去"]):
        return True
    if any(keyword in text for keyword in ["暈倒", "暈過去", "昏過去", "倒地", "倒下", "倒在地上", "倒在路邊"]):
        return True
    return "流血" in text and any(
        keyword in text
        for keyword in ["倒地", "倒在地上", "倒在路邊", "昏倒", "暈倒", "失去意識", "叫不醒", "沒呼吸", "重傷"]
    )


def has_medical_urgency_signal(text: str) -> bool:
    return any(keyword in text for keyword in MEDICAL_URGENCY_KEYWORDS)


def has_burn_signal(text: str) -> bool:
    return any(keyword in text for keyword in ["燙傷", "燒傷", "灼傷", "燙到", "燒到"])


def has_severe_burn_signal(text: str) -> bool:
    return has_contextual_pattern(text, MEDICAL_HIGH_CONTEXT_PATTERNS) and has_burn_signal(text)


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
    taxonomy_match = match_incident_taxonomy(text)

    if taxonomy_match:
        group_id = taxonomy_match.get("group_id")
        subtype = taxonomy_match.get("subtype")
        if group_id == "fire_rescue":
            score = 0.78
            if subtype in ["火災事故", "緊急救護", "交通事故", "山域水域救援", "危險物品事故"]:
                score = 0.86
        elif group_id == "criminal":
            if subtype in ["暴力犯罪", "家庭暴力", "性侵害犯罪", "特殊刑案"]:
                score = 0.86
            else:
                score = 0.55
        elif group_id == "medical_legal":
            score = 0.55
        elif group_id == "civil_social":
            score = 0.35

    v4_floor = v4_risk_floor(text, None)
    if v4_floor:
        score = max(score, v4_floor[0])

    if has_high_risk_context_signal(text):
        score = max(score, 0.9)
    elif has_child_distress_signal(text):
        score = max(score, 0.62)
    elif has_ongoing_disturbance_signal(text):
        score = max(score, 0.62)
    elif has_aggressive_disturbance_signal(text):
        score = max(score, 0.6)
    elif is_repeated_alert_noise(text):
        score = max(score, 0.55)
    elif any(k in text for k in MEDIUM_ALERT_KEYWORDS):
        score = max(score, 0.6)

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
    taxonomy_match = match_incident_taxonomy(text)

    if taxonomy_match:
        group_id = taxonomy_match.get("group_id")
        subtype = taxonomy_match.get("subtype")
        if group_id == "fire_rescue":
            score = max(score, 0.78)
            if subtype in ["火災事故", "緊急救護", "交通事故", "山域水域救援", "危險物品事故"]:
                score = max(score, 0.86)
        elif group_id == "criminal" and subtype in ["暴力犯罪", "家庭暴力", "性侵害犯罪", "特殊刑案"]:
            score = max(score, 0.86)
        elif group_id == "criminal":
            score = max(score, 0.55)

    v4_floor = v4_risk_floor(text, ex.category)
    if v4_floor:
        score = max(score, v4_floor[0])

    if has_ongoing_disturbance_signal(text):
        score = max(score, 0.62)

    if has_child_distress_signal(text):
        score = max(score, 0.62)

    if has_child_unresponsive_signal(text) or has_critical_injury_signal(text):
        score = max(score, 0.9)

    if ex.category == "醫療急症":
        burn_signal = has_burn_signal(text)
        severe_burn_signal = has_severe_burn_signal(text)
        if severe_burn_signal:
            score = max(score, 0.78)
        elif burn_signal:
            score = max(score, score)
        elif (
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

    v4_ceiling = v4_risk_ceiling(text, ex.category)
    if v4_ceiling:
        score = min(score, v4_ceiling[0])

    level = risk_level_from_score(score)
    return score, level
