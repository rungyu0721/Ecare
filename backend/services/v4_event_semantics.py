"""V4 event-oriented semantic hints for short, varied user wording.

This module keeps the event signal vocabulary in one place so extraction,
risk scoring, and follow-up context can evolve together.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, Tuple

from backend.models import Extracted


V4_EVENT_RULES: Dict[str, Dict[str, object]] = {
    "暴力事件": {
        "category_terms": [
            "打架", "互毆", "被打", "毆打", "家暴", "打小孩", "虐待", "闖入",
            "威脅", "恐嚇", "追我", "追人", "推人", "群毆", "砸東西", "摔東西",
            "求救", "救命", "喊救命", "散了", "警察到了",
        ],
        "high_terms": [
            "拿刀", "持刀", "有刀", "拿槍", "持槍", "有武器", "揮刀", "要砍",
            "要殺", "闖進來", "正在打", "被打", "求救", "流血", "倒地",
            "救命", "喊救命", "小孩求救", "小孩哀號", "打小孩",
        ],
        "medium_terms": [
            "吵架", "爭吵", "大吼", "咆哮", "推擠", "快打起來", "摔東西",
            "砸東西", "情緒失控",
        ],
        "lower_terms": ["散了", "停了", "離開了", "警察到了", "保全到了", "站務人員到了"],
        "slot_terms": {
            "weapon": ["刀", "槍", "武器", "棍棒", "球棒", "鐵棍"],
            "people_injured": ["受傷", "流血", "倒地", "被打", "痛", "骨折"],
            "danger_active": ["還在", "正在", "持續", "追", "靠近", "威脅", "闖進", "打架", "互毆"],
        },
    },
    "醫療急症": {
        "category_terms": [
            "昏倒", "暈倒", "倒地", "倒下", "沒反應", "叫不醒", "沒呼吸",
            "呼吸困難", "喘不過氣", "胸痛", "胸悶", "抽搐", "流血", "燙傷",
            "燒傷", "發燒", "嘔吐", "半邊無力", "嘴歪", "講話不清楚", "擦傷",
        ],
        "high_terms": [
            "沒反應", "沒有反應", "叫不醒", "失去意識", "沒呼吸", "沒有呼吸",
            "喘不過氣", "吸不到氣", "大量流血", "血流不止", "抽搐", "胸痛冒冷汗",
            "半邊無力", "嘴歪", "講話不清楚", "焦黑", "發白", "化學灼傷", "觸電",
        ],
        "medium_terms": [
            "高燒", "發燒", "頭暈", "嘔吐", "疑似骨折", "燙傷", "燒傷",
            "水泡", "症狀加重", "很痛",
        ],
        "lower_terms": ["醒了", "清醒", "呼吸正常", "血止住", "止住", "沒有水泡", "沒水泡", "沒有起水泡", "紅紅", "退燒"],
        "slot_terms": {
            "people_injured": ["受傷", "流血", "燙傷", "燒傷", "倒地", "胸痛", "發燒"],
            "conscious": ["清醒", "意識清楚", "叫得醒", "有反應"],
            "unconscious": ["沒反應", "沒有反應", "叫不醒", "失去意識", "昏迷"],
            "breathing_difficulty": ["呼吸困難", "喘不過氣", "吸不到氣", "沒呼吸", "沒有呼吸", "很喘"],
            "breathing_ok": ["呼吸正常", "呼吸沒問題", "沒有喘", "能說話"],
        },
    },
    "火災": {
        "category_terms": [
            "火災", "失火", "起火", "著火", "冒煙", "濃煙", "焦味", "瓦斯味",
            "瓦斯外洩", "電線冒煙", "爆炸", "燒起來", "火滅了", "火已經滅",
        ],
        "high_terms": [
            "明火", "火很大", "濃煙", "煙很大", "受困", "困在裡面", "瓦斯味",
            "瓦斯外洩", "爆炸", "起火", "著火", "吸入濃煙", "嗆傷",
        ],
        "medium_terms": ["焦味", "冒煙", "電線冒煙", "燒焦味", "煙味"],
        "lower_terms": ["火滅了", "火已經滅", "沒有煙", "人都出來", "大家都出來", "已經離開", "消防到了"],
        "slot_terms": {
            "people_injured": ["受困", "受傷", "嗆傷", "吸入濃煙", "困在裡面"],
            "danger_active": ["火勢", "濃煙", "冒煙", "還在燒", "越燒越大", "瓦斯味"],
        },
    },
    "交通事故": {
        "category_terms": [
            "車禍", "撞車", "被車撞", "撞到人", "追撞", "翻車", "機車倒",
            "汽車撞", "摔車", "路倒", "事故", "機車騎士", "車子冒煙", "漏油",
        ],
        "high_terms": [
            "受困", "卡住", "大量流血", "沒反應", "倒地", "暈倒", "車子起火",
            "漏油", "冒煙", "高速", "被車撞", "撞到人",
        ],
        "medium_terms": ["摔車", "機車倒", "擦撞", "車在路中", "阻塞", "有人受傷"],
        "lower_terms": ["移到路邊", "沒有人受傷", "無人受傷", "沒受傷", "警察到了", "救護車到了"],
        "slot_terms": {
            "people_injured": ["受傷", "流血", "受困", "卡住", "卡在車內", "倒地", "暈倒"],
            "danger_active": ["車道", "路中", "路中間", "漏油", "冒煙", "起火", "阻塞", "車流"],
        },
    },
    "可疑人士": {
        "category_terms": [
            "可疑", "怪人", "陌生人", "跟蹤", "尾隨", "徘徊", "鬼鬼祟祟",
            "在門口", "不走", "看我家", "試門把", "跟著我", "越走越近",
        ],
        "high_terms": [
            "跟著我", "尾隨我", "靠近我", "堵我", "在我家門口", "試門把",
            "闖入", "威脅", "有武器", "拿刀",
        ],
        "medium_terms": ["徘徊", "鬼鬼祟祟", "一直看", "不走", "在門口"],
        "lower_terms": ["走了", "離開了", "警衛到了", "管理員到了", "到人多的地方"],
        "slot_terms": {
            "weapon": ["刀", "槍", "武器", "棍棒"],
            "danger_active": ["跟著", "尾隨", "還在", "靠近", "越走越近", "不走", "在門口", "試門把", "徘徊", "鬼鬼祟祟"],
        },
    },
    "噪音": {
        "category_terms": [
            "噪音", "很吵", "吵鬧", "施工", "音樂很大", "大聲", "咆哮",
            "大吼大叫", "叫囂", "吵架", "爭吵",
        ],
        "high_terms": ["求救", "救命", "打鬥", "被打", "摔東西", "砸東西", "小孩哭", "哀號"],
        "medium_terms": ["一直吵", "還在吵", "大吼", "咆哮", "深夜", "摔東西", "砸東西"],
        "lower_terms": ["停了", "安靜了", "只是施工", "只是音樂", "管理員處理了", "處理了"],
        "slot_terms": {
            "people_injured": ["求救", "救命", "哀號", "被打", "受傷"],
            "danger_active": ["還在", "持續", "一直", "沒有停", "現在還"],
            "weapon": ["刀", "槍", "武器"],
        },
    },
}


def contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def contains_negated(text: str, terms: Iterable[str]) -> bool:
    negations = ["沒有", "沒", "無", "未發現", "沒看到", "沒有看到"]
    person_negations = ["沒有人", "沒其他人", "沒有其他人", "無人", "未發現有人"]
    return any(f"{neg}{term}" in text for neg in negations for term in terms) or any(
        f"{neg}{term}" in text for neg in person_negations for term in terms
    )


def matching_categories(text: str) -> Set[str]:
    return {
        category
        for category, rule in V4_EVENT_RULES.items()
        if contains_any(text, rule.get("category_terms", []))
    }


def best_category_from_text(text: str) -> Optional[str]:
    matches = matching_categories(text)
    for category in ["交通事故", "火災", "暴力事件", "可疑人士", "醫療急症", "噪音"]:
        if category in matches:
            return category
    return None


def v4_risk_floor(text: str, category: Optional[str]) -> Optional[Tuple[float, str]]:
    categories = [category] if category in V4_EVENT_RULES else list(matching_categories(text))
    floor: Optional[Tuple[float, str]] = None
    for cat in categories:
        rule = V4_EVENT_RULES.get(cat or "")
        if not rule:
            continue
        if contains_any(text, rule.get("high_terms", [])):
            candidate = (0.88, "High")
        elif contains_any(text, rule.get("medium_terms", [])):
            candidate = (0.60, "Medium")
        elif contains_any(text, rule.get("lower_terms", [])):
            candidate = (0.28, "Low")
        else:
            continue
        if floor is None or candidate[0] > floor[0]:
            floor = candidate
    return floor


def v4_risk_ceiling(text: str, category: Optional[str]) -> Optional[Tuple[float, str]]:
    rule = V4_EVENT_RULES.get(category or "")
    if not rule:
        return None
    if contains_any(text, rule.get("high_terms", [])):
        return None
    if contains_any(text, rule.get("lower_terms", [])):
        return (0.45, "Low")
    return None


def apply_v4_slot_hints(text: str, ex: Extracted) -> Extracted:
    rule = V4_EVENT_RULES.get(ex.category or "")
    if not rule:
        category = best_category_from_text(text)
        if category and ex.category in [None, "待確認"]:
            ex.category = category
            rule = V4_EVENT_RULES.get(category)
    if not rule:
        return ex

    slot_terms = rule.get("slot_terms", {})
    if isinstance(slot_terms, dict):
        injury_terms = slot_terms.get("people_injured", [])
        if contains_negated(text, injury_terms):
            ex.people_injured = False
        elif ex.people_injured is None and contains_any(text, injury_terms):
            ex.people_injured = True
        if ex.weapon is None and contains_any(text, slot_terms.get("weapon", [])):
            ex.weapon = True
        if ex.danger_active is None and contains_any(text, slot_terms.get("danger_active", [])):
            ex.danger_active = True
        if ex.conscious is None and contains_any(text, slot_terms.get("conscious", [])):
            ex.conscious = True
        if ex.conscious is None and contains_any(text, slot_terms.get("unconscious", [])):
            ex.conscious = False
            ex.people_injured = True
        if ex.breathing_difficulty is None and contains_any(text, slot_terms.get("breathing_difficulty", [])):
            ex.breathing_difficulty = True
            ex.people_injured = True
        if ex.breathing_difficulty is None and contains_any(text, slot_terms.get("breathing_ok", [])):
            ex.breathing_difficulty = False

    if contains_any(text, rule.get("lower_terms", [])):
        if ex.category in ["暴力事件", "可疑人士", "噪音", "火災", "交通事故"]:
            ex.danger_active = False

    return ex
