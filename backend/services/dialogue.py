"""
對話狀態管理：階段推斷、缺口判斷、對話路徑選擇、追問生成。
"""

import json
import re
from typing import Any, Dict, List, Optional

from backend.models import (
    ChatMessage,
    DialogueState,
    Extracted,
    SemanticUnderstanding,
)
from backend.services.extraction import (
    asks_about_danger,
    asks_about_injury,
    asks_about_location,
    asks_about_weapon,
    build_incident_acknowledgement,
    get_client_location_text,
    medical_follow_up_question,
    normalize_category_name,
    normalize_location_candidate,
    should_ask_scene_danger,
)
from backend.services.risk import has_high_risk_context_signal


# ======================
# 文字工具
# ======================

def normalize_brief_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def shorten_debug_text(text: Optional[str], limit: int = 80) -> str:
    normalized = (text or "").strip().replace("\n", " ")
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


GENERIC_INTAKE_MARKERS = [
    "請直接告訴我現在發生什麼事",
    "或你最需要我幫什麼",
    "你可以直接說現在發生什麼事",
    "我會協助你把事情講清楚",
    "我會一步一步協助你整理",
    "我先幫你整理目前的狀況",
    "我先幫你整理目前的情況",
    "你最想先知道哪一部分",
]


def is_generic_intake_text(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return True
    if normalized in ["你好，我在這裡。", "我在這裡，我會協助你把事情講清楚。"]:
        return True
    return any(marker in normalized for marker in GENERIC_INTAKE_MARKERS)


def is_greeting_or_opening_text(text: str) -> bool:
    normalized = normalize_brief_text(text)
    if not normalized:
        return False

    greeting_tokens = {"你好", "哈囉", "哈啰", "嗨", "hi", "hello", "在嗎", "有人嗎", "有人在嗎", "喂", "嘿"}
    opening_tokens = {"可以幫我嗎", "你可以幫我嗎", "幫我", "我需要幫忙", "我想求助"}

    if normalized in greeting_tokens or normalized in opening_tokens:
        return True
    return normalized in {"你好啊", "嗨嗨", "hello啊"}


def is_brief_non_emergency_text(text: str) -> bool:
    from backend.services.risk import INCIDENT_DESCRIPTION_KEYWORDS, has_disturbance_signal
    normalized = normalize_brief_text(text)
    if not normalized:
        return False
    if is_greeting_or_opening_text(normalized):
        return True
    if len(normalized) > 8:
        return False
    emergency_markers = INCIDENT_DESCRIPTION_KEYWORDS | {
        "救命", "危險", "流血", "拿刀", "持刀", "受傷", "火災", "失火", "車禍", "昏倒", "沒呼吸",
    }
    if has_disturbance_signal(normalized):
        return False
    return not any(marker in normalized for marker in emergency_markers)


# ======================
# 上下文擷取
# ======================

def get_last_turn_context(messages: List[ChatMessage]) -> tuple:
    last_user_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last_user_index = index
            break

    if last_user_index is None:
        return "", ""

    latest_user_text = messages[last_user_index].content.strip()
    previous_assistant_text = ""

    for index in range(last_user_index - 1, -1, -1):
        if messages[index].role == "assistant":
            previous_assistant_text = messages[index].content.strip()
            break

    return latest_user_text, previous_assistant_text


# ======================
# 地點脈絡
# ======================

def dialogue_state_location_source(
    ex: Extracted,
    audio_context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    normalized_ex_location = normalize_location_candidate(ex.location) if ex.location else None
    tracked_location = get_client_location_text(audio_context)

    if tracked_location and normalized_ex_location:
        return "系統定位"
    if tracked_location:
        return "系統定位"
    if normalized_ex_location:
        return "對話提供"
    return None


def has_known_location_context(
    ex: Optional[Extracted],
    semantic: Optional[SemanticUnderstanding] = None,
    audio_context: Optional[Dict[str, Any]] = None,
) -> bool:
    if ex and ex.location and normalize_location_candidate(ex.location):
        return True
    if (
        semantic
        and semantic.entities.location
        and normalize_location_candidate(semantic.entities.location)
    ):
        return True
    return bool(get_client_location_text(audio_context))


# ======================
# 缺口判斷
# ======================

def determine_missing_slots(
    ex: Extracted,
    *,
    location_known: bool,
) -> List[str]:
    missing: List[str] = []
    category = normalize_category_name(ex.category) or "待確認"

    if not location_known:
        missing.append("事發地點")

    if category == "待確認":
        missing.append("事件內容")
        return missing

    if category == "醫療急症":
        if ex.conscious is None:
            missing.append("意識狀況")
        if ex.breathing_difficulty is None:
            missing.append("呼吸狀況")
        if ex.people_injured is None:
            missing.append("是否需要立即醫療協助")
        return missing

    if category == "暴力事件":
        if ex.weapon is None:
            missing.append("是否有武器")
        if ex.danger_active is None:
            missing.append("危險是否持續")
        if ex.people_injured is None:
            missing.append("是否有人受傷")
        return missing

    if category == "火災":
        if ex.danger_active is None:
            missing.append("火勢是否持續")
        if ex.people_injured is None:
            missing.append("是否有人受困或受傷")
        return missing

    if category == "交通事故":
        if ex.people_injured is None:
            missing.append("是否有人受傷")
        if ex.danger_active is None:
            missing.append("事故是否仍在危險位置")
        return missing

    if category == "可疑人士":
        if ex.danger_active is None:
            missing.append("對方是否仍在附近")
        return missing

    if category == "噪音":
        if ex.danger_active is None:
            missing.append("是否仍在持續或升高為威脅")
        return missing

    return missing


# ======================
# 階段推斷
# ======================

def infer_dialogue_stage(
    latest_user_text: str,
    ex: Extracted,
    missing_slots: List[str],
    risk_level: str,
) -> str:
    normalized = (latest_user_text or "").strip()

    if risk_level == "High":
        return "緊急確認中"
    if ex.category in [None, "待確認"]:
        if is_greeting_or_opening_text(normalized):
            return "開場接線"
        return "初步釐清"
    if missing_slots:
        return "資訊補齊中"
    return "可提供處置"


# ======================
# 狀態建構
# ======================

def build_dialogue_state(
    messages: List[ChatMessage],
    ex: Extracted,
    semantic: SemanticUnderstanding,
    risk_level: str,
    audio_context: Optional[Dict[str, Any]] = None,
) -> DialogueState:
    latest_user_text_value, previous_assistant_text = get_last_turn_context(messages)
    location_known = has_known_location_context(ex, semantic, audio_context)
    location_text = (
        (normalize_location_candidate(ex.location) if ex.location else None)
        or (
            normalize_location_candidate(semantic.entities.location)
            if semantic.entities.location
            else None
        )
        or get_client_location_text(audio_context)
    )
    missing_slots = determine_missing_slots(ex, location_known=location_known)
    stage = infer_dialogue_stage(latest_user_text_value, ex, missing_slots, risk_level)
    location_source = dialogue_state_location_source(ex, audio_context)
    incident_type = normalize_category_name(ex.category) or "待確認"

    summary_parts = [
        f"案件={incident_type}",
        f"風險={risk_level}",
        f"位置={'已知' if location_known else '未知'}",
        f"目標={semantic.primary_need or '釐清狀況'}",
    ]
    if missing_slots:
        summary_parts.append(f"缺口={'、'.join(missing_slots)}")
    if previous_assistant_text:
        summary_parts.append(f"上一題={shorten_debug_text(previous_assistant_text, 40)}")

    return DialogueState(
        incident_type=incident_type,
        risk_level=risk_level,
        location_known=location_known,
        location_source=location_source,
        location_text=location_text,
        latest_user_intent=semantic.intent or "未知",
        user_goal=semantic.primary_need or "釐清狀況",
        reporter_role=ex.reporter_role,
        stage=stage,
        last_assistant_question=previous_assistant_text or None,
        missing_slots=missing_slots,
        summary=" | ".join(summary_parts),
    )


# ======================
# 路徑選擇
# ======================

def should_use_compact_chat_path(
    messages: List[ChatMessage],
    dialogue_state: DialogueState,
    latest_text: str,
) -> bool:
    normalized = normalize_brief_text(latest_text)
    if not normalized:
        return False
    if dialogue_state.incident_type in [None, "待確認"]:
        return False
    if dialogue_state.stage in ["開場接線", "緊急確認中"]:
        return False
    if is_greeting_or_opening_text(normalized):
        return False

    _, previous_assistant_text = get_last_turn_context(messages)
    previous_assistant_text = previous_assistant_text.strip()
    if not previous_assistant_text:
        return False

    if any(
        checker(previous_assistant_text)
        for checker in [asks_about_location, asks_about_injury, asks_about_weapon, asks_about_danger]
    ):
        return True

    return len(normalized) <= 20 and dialogue_state.location_known


def should_skip_graph_lookup(
    compact_chat_path: bool,
    latest_text: str,
    conversation_state: Extracted,
) -> bool:
    if not compact_chat_path:
        return False
    if normalize_category_name(conversation_state.category) in [None, "待確認"]:
        return False
    if has_high_risk_context_signal(latest_text):
        return False
    return True


# ======================
# 接線腳本
# ======================

def apply_category_scripts(ex: Extracted, risk_level: str) -> str:
    from backend.services.extraction import subject_reference
    ref = subject_reference(ex)

    if ex.category == "醫療急症":
        if ex.conscious is None and ex.breathing_difficulty is None:
            return f"{ref}現在意識清楚嗎？有沒有呼吸困難、喘不過氣、昏倒，或需要立刻送醫？"
        if ex.conscious is None:
            return f"{ref}現在意識清楚嗎？有沒有昏倒、叫不太醒，或反應變慢？"
        if ex.breathing_difficulty is None:
            return f"{ref}有沒有呼吸困難、喘不過氣，或沒辦法正常說完整句子？"
        if ex.breathing_difficulty is True or ex.conscious is False:
            return medical_follow_up_question(ex, risk_level)
        if ex.fever is None:
            return f"{ref}有沒有發燒、胸痛、嘔吐，或其他症狀正在加重？"
        return medical_follow_up_question(ex, risk_level)

    if ex.category == "火災":
        if ex.danger_active is None:
            return "火勢或濃煙現在還在持續嗎？有沒有越燒越大？"
        if ex.people_injured is None:
            return "現場有人受困、嗆傷，或需要救護車嗎？"
        return "起火點大概是在住家、室內空間、店面，還是車輛附近？"

    if ex.category == "暴力事件":
        if ex.weapon is None:
            return "現場對方有持刀、棍棒或其他武器嗎？"
        if ex.danger_active is None:
            return "對方現在還在現場，或還在持續威脅嗎？"
        if ex.people_injured is None:
            return "現場有人受傷、流血，或需要立刻送醫嗎？"
        return "目前你們有沒有先移動到比較安全的位置？"

    if ex.category == "交通事故":
        if ex.people_injured is None:
            return "有人受傷、受困，或需要立刻叫救護車嗎？"
        if ex.danger_active is None:
            return "事故車輛現在還卡在車道上，或現場還有持續危險嗎？"
        return "事故大概是在路口、巷口，還是主要幹道？"

    if ex.category == "可疑人士":
        if ex.danger_active is None:
            return "那個人現在還在附近，或還在跟著你們嗎？"
        return "你可以描述一下對方的外觀、穿著，或目前在做什麼嗎？"

    if ex.category == "噪音":
        if ex.danger_active is None:
            return "現在吵鬧還在持續嗎？有沒有變成衝突或威脅？"
        return "聲音大概是來自住戶、施工，還是路邊聚眾？"

    return "可以再補充目前現場的狀況嗎？"


def next_question(ex: Extracted, risk_level: str) -> str:
    if risk_level == "High" and not ex.location:
        return "請問事發地點在哪裡？"

    if ex.category == "待確認":
        if not ex.location:
            return "請問事發地點在哪裡？"
        return "請直接告訴我現在發生什麼事，例如有人受傷、有人威脅、發生火災，或你身體不舒服。"

    return apply_category_scripts(ex, risk_level)


def next_question_from_semantic(
    default_question: str,
    semantic: SemanticUnderstanding,
    ex: Extracted,
    risk_level: str,
    audio_context: Optional[Dict[str, Any]] = None,
) -> str:
    from backend.services.semantic import has_high_urgency_audio_emotion
    location_known = has_known_location_context(ex, semantic, audio_context)

    if has_high_urgency_audio_emotion(audio_context):
        if not location_known:
            return "你現在人在哪裡？請先告訴我地址、明顯地標，或附近路名。"
        if ex.category in ["暴力事件", "可疑人士", "火災", "交通事故"] and ex.danger_active is None:
            return "你現在是否在安全位置？危險人物、火勢或事故還在現場嗎？"
        if semantic.entities.injured is None and ex.people_injured is None:
            return "現場有人受傷、流血，或需要立刻送醫嗎？"

    if risk_level == "High" and not location_known:
        return "你現在人在哪裡？請告訴我地址、明顯地標，或附近路名。"

    if ex.category == "醫療急症":
        return next_question(ex, risk_level)

    if ex.category in ["噪音", "可疑人士", "暴力事件", "火災", "交通事故"]:
        return default_question or next_question(ex, risk_level)

    if risk_level in ["Medium", "High"] and semantic.entities.injured is None and ex.people_injured is None:
        return "現場有人受傷、失去意識，或需要立刻送醫嗎？"

    if semantic.intent == "情緒支持":
        return "你現在身邊有沒有可以陪你的人，或你目前是不是一個人？"

    if semantic.intent == "詢問":
        return "你最想先知道哪一部分？我可以先直接回答你最急的問題。"

    return default_question


# ======================
# Debug 日誌
# ======================

def log_chat_debug(
    stage: str,
    latest_text: str,
    ex: Extracted,
    semantic: SemanticUnderstanding,
    dialogue_state: Optional[DialogueState],
    reply: str,
    next_q: str,
    risk_level: str,
    risk_score: float,
    *,
    llm_category: Optional[str] = None,
    reply_changed: bool = False,
    next_question_changed: bool = False,
) -> None:
    payload = {
        "stage": stage,
        "user": shorten_debug_text(latest_text),
        "llm_category": llm_category,
        "category": ex.category,
        "risk_level": risk_level,
        "risk_score": round(risk_score, 3),
        "intent": semantic.intent,
        "primary_need": semantic.primary_need,
        "dialogue_stage": dialogue_state.stage if dialogue_state else None,
        "location_known": dialogue_state.location_known if dialogue_state else None,
        "missing_slots": dialogue_state.missing_slots if dialogue_state else [],
        "dialogue_summary": dialogue_state.summary if dialogue_state else None,
        "injured": ex.people_injured,
        "weapon": ex.weapon,
        "danger_active": ex.danger_active,
        "reply_changed": reply_changed,
        "next_question_changed": next_question_changed,
        "reply": shorten_debug_text(reply),
        "next_question": shorten_debug_text(next_q),
    }
    print(f"E-CARE chat debug -> {json.dumps(payload, ensure_ascii=False)}")
