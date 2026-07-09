"""
語意 slot 解析器：根據追問上下文和使用者短回覆，補全 Extracted slot 欄位。

這是第三層防線，在 turn context 函式之後執行，處理：
1. 純肯定/否定短句（「有」「沒有」「對」「嗯嗯」）
2. 同義說法變體（「他還好」「都沒事」「已經跑掉了」）
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from backend.models import Extracted


# ======================
# 短句肯定/否定判斷
# ======================

_AFFIRMATIVE_EXACT = {
    "有", "是", "對", "嗯", "嗯嗯", "好", "對啊", "是啊", "有啊", "沒錯",
    "確定", "真的", "有耶", "有喔", "對喔", "有有", "是是",
}

_NEGATIVE_EXACT = {
    "沒", "沒有", "沒有耶", "不是", "不", "沒啦", "沒有啊", "不對", "不是耶",
    "停了", "散了", "走了", "結束了", "離開了", "好了", "沒事了", "沒有了",
    "沒有人", "無人", "無", "沒問題", "都沒事", "都好", "他還好",
}


def _is_affirmative(text: str) -> bool:
    t = text.strip()
    if t in _AFFIRMATIVE_EXACT:
        return True
    if len(t) <= 4 and any(tok in t for tok in ["有", "是", "對", "嗯", "好"]):
        # avoid false matches like "有點", "不是", etc.
        if not any(neg in t for neg in ["沒", "不", "無"]):
            return True
    return False


def _is_negative(text: str) -> bool:
    t = text.strip()
    if t in _NEGATIVE_EXACT:
        return True
    # 沒有X where X is very short
    if t.startswith("沒有") and len(t) <= 5:
        return True
    if t.startswith("沒") and len(t) <= 3:
        return True
    return False


# ======================
# 追問主題偵測 → slot name
# 順序重要：越具體的放越前面
# ======================

_QUESTION_SLOT_MAP: List[Tuple[List[str], str]] = [
    (["叫得醒", "叫不醒", "有沒有反應", "有反應", "意識", "清醒", "有沒有意識"], "conscious"),
    (["呼吸", "喘不過氣", "喘", "沒呼吸", "呼吸困難", "吸不到氣"], "breathing_difficulty"),
    (["武器", "持刀", "拿刀", "棍棒", "槍", "有沒有刀"], "weapon"),
    (["受困", "裡面有人", "吸入濃煙", "嗆傷"], "people_injured"),
    (["受傷", "流血", "傷者", "有沒有人受傷", "有人受傷", "有沒有受傷"], "people_injured"),
    (["還在持續", "還在打", "還在燒", "還在現場", "危險還在", "對方還在", "還在附近",
      "還在嗎", "還在嗎？", "還在嗎?", "是否仍在", "是否還在"], "danger_active"),
    (["車道", "路中間", "漏油", "冒煙", "阻擋交通", "事故是否仍", "還在車道"], "danger_active"),
]


def _detect_question_slot(question_text: str) -> Optional[str]:
    for keywords, slot in _QUESTION_SLOT_MAP:
        if any(kw in question_text for kw in keywords):
            return slot
    return None


# ======================
# 同義詞擴展 vocab
# 每個 slot 的 true/false 常見說法
# ======================

_SLOT_TRUE_VOCAB = {
    "people_injured": [
        "受傷", "流血", "倒地", "昏倒", "意識不清", "叫不醒", "骨折",
        "大量出血", "有傷者", "有人倒地", "有血", "有受傷", "有流血",
        "不舒服", "快不行", "嗆傷", "吸入濃煙", "受困",
    ],
    "weapon": [
        "有刀", "拿刀", "持刀", "有武器", "有槍", "拿槍", "有棍棒",
        "手上有刀", "看到刀", "看到武器",
    ],
    "danger_active": [
        "還在", "持續", "正在", "還沒停", "繼續", "還在打", "還在燒",
        "還在附近", "沒有走", "沒走", "沒有離開", "跟著", "一直在",
        "仍在", "沒有停", "沒有結束",
    ],
    "conscious": [
        "清醒", "有反應", "叫得醒", "意識清楚", "醒著", "有叫到",
        "有在動", "有說話", "還有反應",
    ],
    "breathing_difficulty": [
        "喘不過氣", "呼吸困難", "很喘", "沒呼吸", "吸不到氣", "嘴唇發紫",
        "臉發紫", "沒有呼吸", "快沒氣", "呼吸很淺",
    ],
}

_SLOT_FALSE_VOCAB = {
    "people_injured": [
        "沒受傷", "沒有受傷", "好好的", "都還好", "沒事", "沒有人受傷",
        "無人受傷", "都沒事", "他還好", "沒有血", "沒流血",
    ],
    "weapon": [
        "沒有武器", "沒有刀", "沒看到武器", "徒手", "沒有看到刀",
        "沒有槍", "沒有棍棒",
    ],
    "danger_active": [
        "停了", "散了", "結束了", "走了", "離開了", "滅了", "火滅了",
        "已經停了", "已經離開", "不在了", "跑了", "已經走了",
        "已經結束", "沒有了", "都走了",
    ],
    "conscious": [
        "沒反應", "叫不醒", "昏迷", "失去意識", "不清醒", "意識不清",
        "沒有反應", "沒有意識", "無反應",
    ],
    "breathing_difficulty": [
        "呼吸正常", "沒有喘", "呼吸沒問題", "還好", "呼吸ok",
        "呼吸ok", "沒有呼吸困難", "不喘", "正常呼吸",
    ],
}


def _match_vocab(text: str, slot: str) -> Optional[bool]:
    for phrase in _SLOT_TRUE_VOCAB.get(slot, []):
        if phrase in text:
            return True
    for phrase in _SLOT_FALSE_VOCAB.get(slot, []):
        if phrase in text:
            return False
    return None


# ======================
# 非 slot 問題偵測
# （機器人問地點、安全、個資時，短回覆不應映射到 slot）
# ======================

_NON_SLOT_QUESTION_SIGNALS = [
    "地點", "地址", "哪裡", "在哪", "告訴我", "你在哪", "人在哪",  # 地點
    "安全嗎", "你安全嗎", "你還好嗎", "你現在安全",               # 安全確認
    "移動到", "安全的位置", "比較安全", "移到安全", "撤離",        # 撤離確認
    "名字", "電話", "聯絡方式",                                     # 個資
    "什麼地方", "哪個地方",
]

def _is_non_slot_question(question_text: str) -> bool:
    return any(sig in question_text for sig in _NON_SLOT_QUESTION_SIGNALS)


# ======================
# 類別 slot 優先序（當問題內容無法判斷時，依此順序猜測）
# ======================

_CATEGORY_SLOT_PRIORITY: Dict[str, List[str]] = {
    "暴力事件": ["weapon", "people_injured", "danger_active"],
    "醫療急症": ["conscious", "breathing_difficulty", "people_injured"],
    "山域水域救援": ["people_injured", "danger_active"],
    "天然災害": ["danger_active", "people_injured"],
    "火災":     ["danger_active", "people_injured"],
    "交通事故": ["people_injured", "danger_active"],
    "可疑人士": ["danger_active"],
    "噪音":     ["danger_active", "people_injured"],
}

def _pending_slot_by_category(category: str, extracted) -> Optional[str]:
    """回傳該類別優先序中第一個尚未填值的 slot。"""
    slot_to_value = {
        "weapon":             extracted.weapon,
        "people_injured":     extracted.people_injured,
        "danger_active":      extracted.danger_active,
        "conscious":          extracted.conscious,
        "breathing_difficulty": extracted.breathing_difficulty,
    }
    for slot in _CATEGORY_SLOT_PRIORITY.get(category, []):
        if slot_to_value.get(slot) is None:
            return slot
    return None


# ======================
# 主入口
# ======================

def resolve_slot_from_reply(
    user_text: str,
    last_question: str,
    extracted=None,
) -> Optional[Tuple[str, bool]]:
    """
    根據上一個助理追問 + 使用者回覆，解析 slot 更新。
    回傳 (slot_name, value) 或 None。

    extracted: Extracted instance (用於 pending slot fallback)
    """
    text = user_text.strip()

    # --- 先嘗試從問題內容偵測 slot ---
    slot = _detect_question_slot(last_question)

    # --- 如果問題偵測不到 slot，嘗試用 pending slot fallback ---
    # 例外：純短句肯定/否定（≤4字）仍可使用，因為沒人會用「有」回答地點問題。
    # 只有當用戶的回覆較長（可能是地址或描述）才跳過。
    if not slot and _is_non_slot_question(last_question) and len(text) > 4:
        return None

    if not slot and extracted is not None:
        category = (extracted.category or "").strip()
        if category:
            slot = _pending_slot_by_category(category, extracted)

    if not slot:
        return None

    # 1. 同義詞 vocab 優先（明確語意）
    vocab_result = _match_vocab(text, slot)
    if vocab_result is not None:
        return (slot, vocab_result)

    # 2. 短句肯定/否定（「有」「沒有」「對」等）
    if _is_negative(text):
        return (slot, False)
    if _is_affirmative(text):
        return (slot, True)

    return None


def apply_slot_resolver(
    user_text: str,
    last_question: str,
    extracted: Extracted,
) -> Extracted:
    """
    對 None 的 slot 欄位補全，不覆蓋已有值。
    """
    result = resolve_slot_from_reply(user_text, last_question, extracted)
    if not result:
        return extracted

    slot_name, value = result

    if slot_name == "people_injured" and extracted.people_injured is None:
        extracted.people_injured = value
    elif slot_name == "weapon" and extracted.weapon is None:
        extracted.weapon = value
    elif slot_name == "danger_active" and extracted.danger_active is None:
        extracted.danger_active = value
    elif slot_name == "conscious" and extracted.conscious is None:
        extracted.conscious = value
    elif slot_name == "breathing_difficulty" and extracted.breathing_difficulty is None:
        extracted.breathing_difficulty = value

    return extracted
