"""類別判斷、追問偵測、派遣建議、現場危險判斷。"""

from typing import Optional

from backend.models import Extracted

# ======================
# 追問關鍵字
# ======================

LOCATION_QUESTION_KEYWORDS = ["地點", "地址", "哪裡", "位置", "在哪裡", "人在哪"]
INJURY_QUESTION_KEYWORDS = ["受傷", "失去意識", "送醫", "醫療協助", "呼吸困難", "昏倒", "意識清楚"]
CATEGORY_QUESTION_KEYWORDS = ["火災", "可疑人士", "噪音", "醫療急症", "暴力事件", "交通事故", "發生了什麼事"]
WEAPON_QUESTION_KEYWORDS = ["武器", "持刀", "棍棒", "槍"]
DANGER_QUESTION_KEYWORDS = ["還在持續", "還在現場", "是否安全", "危險還在", "還在擴大"]

# ======================
# 類別正規化
# ======================

CATEGORY_NORMALIZATION_MAP = {
    "火災": "火災",
    "可疑人士": "可疑人士",
    "噪音": "噪音",
    "醫療急症": "醫療急症",
    "暴力事件": "暴力事件",
    "交通事故": "交通事故",
    "待確認": "待確認",
    "暴力傷害": "暴力事件",
    "持械威脅": "暴力事件",
    "車禍傷病": "交通事故",
    "自殺風險": "醫療急症",
    "其他危急事件": "待確認",
    "未知": "待確認",
}


def normalize_category_name(category: Optional[str]) -> Optional[str]:
    if category is None:
        return None
    return CATEGORY_NORMALIZATION_MAP.get(category, category)


# ======================
# 詢問偵測
# ======================

def asks_about_location(text: str) -> bool:
    return any(keyword in text for keyword in LOCATION_QUESTION_KEYWORDS)


def asks_about_injury(text: str) -> bool:
    return any(keyword in text for keyword in INJURY_QUESTION_KEYWORDS)


def asks_about_category(text: str) -> bool:
    return any(keyword in text for keyword in CATEGORY_QUESTION_KEYWORDS)


def asks_about_weapon(text: str) -> bool:
    return any(keyword in text for keyword in WEAPON_QUESTION_KEYWORDS)


def asks_about_danger(text: str) -> bool:
    return any(keyword in text for keyword in DANGER_QUESTION_KEYWORDS)


# ======================
# 派遣建議
# ======================

def get_dispatch_advice(
    category: Optional[str],
    weapon: Optional[bool],
    people_injured: Optional[bool],
) -> str:
    if category == "火災":
        return "建議派遣：消防車 + 救護車" if people_injured else "建議派遣：消防車"
    if category == "醫療急症":
        return "建議派遣：救護車"
    if category == "暴力事件":
        return "建議派遣：警察，必要時通知救護車待命" if weapon else "建議派遣：警察"
    if category == "交通事故":
        return "建議派遣：警察 + 救護車" if people_injured else "建議派遣：警察"
    if category == "可疑人士":
        return "建議派遣：警察"
    if category == "噪音":
        return "建議派遣：警察或相關單位查看"
    return "建議派遣：待確認"


# ======================
# 場景判斷
# ======================

def should_ask_scene_danger(ex: Extracted, risk_level: str) -> bool:
    if ex.danger_active is not None or risk_level not in ["Medium", "High"]:
        return False
    return ex.category in ["火災", "暴力事件", "交通事故", "可疑人士"]


def build_incident_acknowledgement(ex: Extracted) -> str:
    if ex.category == "醫療急症":
        return "收到，現場有人身體不舒服，我先幫你整理。"
    if ex.category == "火災":
        return "收到，現場疑似有火災，我先幫你確認重點。"
    if ex.category == "暴力事件":
        return "收到，現場可能有衝突或人身危險，我先幫你整理。"
    if ex.category == "交通事故":
        return "收到，現場看起來有交通事故，我先幫你整理。"
    if ex.category == "可疑人士":
        return "收到，現場有可疑狀況，我先幫你整理。"
    if ex.category == "噪音":
        return "收到，現場有明顯吵鬧或叫囂，我先幫你整理。"
    return "收到，我先幫你整理目前的狀況。"
