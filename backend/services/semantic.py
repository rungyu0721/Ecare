"""
語意理解模組：啟發式分析 + LLM 語意理解。
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from backend.config import ENABLE_LLM_SEMANTIC_UNDERSTANDING
from backend.models import (
    ChatMessage,
    Extracted,
    SemanticEntities,
    SemanticUnderstanding,
)
from backend.services.emotion import (
    has_high_urgency_emotion_value,
    normalize_emotion_score,
)
from backend.services.extraction import get_client_location_text
from backend.services.llm import call_llm, llm_is_ready, parse_llm_json_text
from backend.services.risk import AGGRESSIVE_DISTURBANCE_KEYWORDS, has_aggressive_disturbance_signal


# ======================
# 音頻情緒工具
# ======================

def get_audio_emotion(audio_context: Optional[Dict[str, Any]]) -> str:
    if not audio_context:
        return "neutral"
    emotion = (audio_context.get("emotion") or "neutral").strip().lower()
    return emotion or "neutral"


def get_audio_emotion_score(audio_context: Optional[Dict[str, Any]]) -> float:
    if not audio_context:
        return 0.0
    return normalize_emotion_score(audio_context.get("emotion_score") or 0.0)


def has_high_urgency_audio_emotion(audio_context: Optional[Dict[str, Any]]) -> bool:
    return has_high_urgency_emotion_value(
        get_audio_emotion(audio_context),
        get_audio_emotion_score(audio_context),
    )


# ======================
# 位置脈絡（canonical 定義在 dialogue.py）
# ======================

from backend.services.dialogue import has_known_location_context  # noqa: F401


# ======================
# 啟發式語意理解
# ======================

def is_brief_non_emergency_text(text: str) -> bool:
    from backend.services.dialogue import is_brief_non_emergency_text as _fn
    return _fn(text)


def heuristic_semantic_understanding(
    text: str,
    audio_context: Optional[Dict[str, Any]],
    fallback_entities: SemanticEntities,
    extracted: Optional[Extracted] = None,
) -> SemanticUnderstanding:
    from backend.services.risk import INCIDENT_DESCRIPTION_KEYWORDS, has_disturbance_signal
    normalized_text = (text or "").strip()
    audio_emotion = get_audio_emotion(audio_context)

    if not normalized_text:
        return SemanticUnderstanding(emotion=audio_emotion, entities=fallback_entities)

    danger_keywords = [
        "救", "幫", "快點", "危險",
        "持刀", "拿刀", "有刀", "刀", "武器", "揮刀",
        "流血", "大量流血", "受傷",
        "燙傷", "燒傷", "灼傷", "燙到", "燒到", "水泡",
        "火災", "失火", "著火", "起火",
        "暈倒", "昏倒", "暈過去", "昏過去", "倒地", "倒下", "倒在地上", "倒在路邊",
        "沒反應", "沒有反應", "無反應", "叫不醒",
        "沒呼吸", "沒有呼吸", "呼吸困難", "喘不過氣", "吸不到氣", "很喘",
        "胸痛", "胸悶", "心臟痛", "抽搐", "半邊無力", "嘴歪", "講話不清楚", "失去意識", "意識不清",
    ]
    emotional_support_keywords = [
        "好怕", "很怕", "不知道怎麼辦", "我快受不了", "我很崩潰",
        "心疼", "好難受", "我很擔心", "嚇到了", "嚇壞了",
        "怎麼會這樣", "我不知道該怎麼辦", "我手抖", "我腦袋空白",
        "好無助", "我好慌", "不知所措", "我好害怕", "我嚇到了",
        "我很害怕", "我好緊張", "我不知道怎麼辦才好", "好緊張",
    ]
    question_keywords = ["怎麼辦", "要怎麼做", "是不是", "可不可以", "需要嗎"]
    disturbance_keywords = list(AGGRESSIVE_DISTURBANCE_KEYWORDS)

    if is_brief_non_emergency_text(normalized_text):
        intent = "詢問"
        primary_need = "開始描述狀況"
        reply_strategy = "先友善接住，再請對方直接描述發生的事"
    elif any(keyword in normalized_text for keyword in [
        "AED", "aed", "找到AED", "找到aed", "拿到AED", "拿到aed",
        "已打119", "已撥119", "打了119", "撥了119", "119來了",
        "救護車來了", "救護車到了", "救援到了", "消防來了",
        "開始CPR", "在做CPR", "已經在做", "已開始按壓",
    ]):
        intent = "進展回報"
        primary_need = "確認下一步行動"
        reply_strategy = "先肯定對方做得好，直接給下一個最關鍵的指示，不重述之前說過的步驟"
    elif has_aggressive_disturbance_signal(normalized_text) or any(
        keyword in normalized_text for keyword in disturbance_keywords
    ):
        intent = "求助"
        primary_need = "確認是否有威脅"
        reply_strategy = "先確認對方是否仍在現場，以及是否已經影響安全"
    elif has_high_urgency_audio_emotion(audio_context) or any(
        keyword in normalized_text for keyword in danger_keywords
    ):
        intent = "求救"
        if any(keyword in normalized_text for keyword in ["暈倒", "昏倒", "暈過去", "昏過去", "倒下", "沒反應", "沒有反應", "無反應", "叫不醒", "沒呼吸", "沒有呼吸", "呼吸困難", "喘不過氣", "吸不到氣", "胸痛", "胸悶", "心臟痛", "抽搐", "半邊無力", "嘴歪", "講話不清楚", "失去意識", "意識不清", "燙傷", "燒傷", "灼傷", "燙到", "燒到", "水泡"]):
            primary_need = "立即醫療確認"
            if any(keyword in normalized_text for keyword in ["燙傷", "燒傷", "灼傷", "燙到", "燒到", "水泡"]):
                reply_strategy = "先確認燒燙傷範圍與嚴重程度，提醒冷水沖洗與就醫條件"
            else:
                reply_strategy = "先確認意識與呼吸，必要時提醒撥打 119"
        else:
            primary_need = "立即安全協助"
            reply_strategy = "先穩定情緒，再確認安全與位置"
    elif any(keyword in normalized_text for keyword in emotional_support_keywords):
        intent = "情緒支持"
        primary_need = "先穩定情緒"
        reply_strategy = "先接住情緒，再確認眼前最需要的協助"
    elif any(keyword in normalized_text for keyword in question_keywords):
        intent = "詢問"
        primary_need = "快速回答眼前問題"
        reply_strategy = "先直接回答，再補最必要的確認"
    else:
        intent = "資訊補充"
        primary_need = "釐清狀況"
        reply_strategy = "先確認事件重點"

    # 依 reporter_role 調整 reply_strategy
    reporter_role = (extracted.reporter_role or "") if extracted else ""
    if "照顧者" in reporter_role or "家屬" in reporter_role:
        if intent in ["求救", "進展回報"]:
            reply_strategy = (
                "先給照顧者情感支持與肯定，用「你的家人」稱呼傷病者，"
                "確認傷病者意識/呼吸，語氣要同時照顧照顧者與傷病者"
            )
        elif intent == "情緒支持":
            reply_strategy = "先接住照顧者的擔心與心疼，再陪他一步一步整理目前狀況"
    elif "本人受害" in reporter_role or reporter_role == "本人":
        if intent == "求救":
            reply_strategy = "先確認本人目前是否安全、有沒有受傷，再問事件細節，不要用旁觀者語氣"
        elif intent == "情緒支持":
            reply_strategy = "先直接承接本人的恐懼或痛苦，告訴他我在、不要一個人扛，再確認安全"
    elif "旁觀者" in reporter_role:
        if intent == "求救":
            reply_strategy = "語氣鎮定，先給明確行動指引（不要靠近、撥 119），再問能安全觀察到的資訊"

    return SemanticUnderstanding(
        intent=intent,
        primary_need=primary_need,
        emotion=audio_emotion,
        reply_strategy=reply_strategy,
        entities=fallback_entities,
    )


# ======================
# Payload 解析
# ======================

def semantic_understanding_from_payload(
    payload: Optional[Dict[str, Any]],
    audio_context: Optional[Dict[str, Any]] = None,
    extracted: Optional[Extracted] = None,
) -> SemanticUnderstanding:
    client_location_text = get_client_location_text(audio_context)
    fallback_entities = SemanticEntities(
        location=(extracted.location if extracted and extracted.location else client_location_text),
        injured=(extracted.people_injured if extracted else None),
        weapon=(extracted.weapon if extracted else None),
        danger_active=(extracted.danger_active if extracted else None),
    )

    if not isinstance(payload, dict):
        return SemanticUnderstanding(
            emotion=get_audio_emotion(audio_context),
            entities=fallback_entities,
        )

    entities = payload.get("entities", {}) or {}
    return SemanticUnderstanding(
        intent=payload.get("intent") or "未知",
        primary_need=payload.get("primary_need") or "釐清狀況",
        emotion=payload.get("emotion") or get_audio_emotion(audio_context),
        reply_strategy=payload.get("reply_strategy") or "先確認事件重點",
        entities=SemanticEntities(
            location=entities.get("location", fallback_entities.location),
            injured=entities.get("injured", fallback_entities.injured),
            weapon=entities.get("weapon", fallback_entities.weapon),
            danger_active=entities.get("danger_active", fallback_entities.danger_active),
        ),
    )


# ======================
# LLM 語意理解
# ======================

def should_use_llm_semantic_understanding(
    messages: Optional[List[ChatMessage]],
    text: str,
    audio_context: Optional[Dict[str, Any]],
    extracted: Optional[Extracted],
) -> bool:
    from backend.models import latest_user_text
    if not llm_is_ready() or not ENABLE_LLM_SEMANTIC_UNDERSTANDING:
        return False
    latest_text = latest_user_text(messages or []).strip()
    candidate_text = latest_text or (text or "").strip()
    return bool(candidate_text)


def semantic_understanding_from_text(
    messages: Optional[List[ChatMessage]],
    text: str,
    audio_context: Optional[Dict[str, Any]] = None,
    extracted: Optional[Extracted] = None,
) -> SemanticUnderstanding:
    client_location_text = get_client_location_text(audio_context)
    fallback_entities = SemanticEntities(
        location=(extracted.location if extracted and extracted.location else client_location_text),
        injured=(extracted.people_injured if extracted else None),
        weapon=(extracted.weapon if extracted else None),
        danger_active=(extracted.danger_active if extracted else None),
    )

    if not text.strip():
        return SemanticUnderstanding(entities=fallback_entities)

    fallback_semantic = heuristic_semantic_understanding(text, audio_context, fallback_entities)
    if not should_use_llm_semantic_understanding(messages, text, audio_context, extracted):
        return fallback_semantic

    safe_audio_context = {
        "transcript": (audio_context or {}).get("transcript"),
        "emotion": (audio_context or {}).get("emotion"),
        "emotion_score": (audio_context or {}).get("emotion_score"),
        "risk_level": (audio_context or {}).get("risk_level"),
        "risk_score": (audio_context or {}).get("risk_score"),
        "client_location": client_location_text,
    }
    safe_extracted = extracted.model_dump() if extracted else {}

    # Build recent conversation context (last 2 turns = up to 4 messages)
    context_lines = []
    if messages:
        recent_msgs = [m for m in messages if m.content.strip()][-4:]
        for msg in recent_msgs:
            role_name = "使用者" if msg.role == "user" else "助理"
            context_lines.append(f"{role_name}：{msg.content[:120]}")
    context_text = "\n".join(context_lines) if context_lines else "（首次開口）"

    prompt = f"""
你是語意理解模組。請根據使用者文字、語音情緒、近期對話與事件抽取結果，輸出語意理解 JSON。

規則：
- 只能輸出 JSON
- intent 只能是：求救、通報、詢問、情緒支持、資訊補充、進展回報、未知
- 「進展回報」用於使用者回報新進展，例如找到AED、已打119、開始CPR、救護車到了
- primary_need 要簡短描述此刻最需要的協助
- emotion 可綜合文字語氣與語音情緒
- reply_strategy 要描述助理最適合的回應策略
- 如果語音情緒是 panic / fearful 且分數高，優先判斷是否需要立即安全協助
- 如果文字是在描述他人出事，primary_need 與 reply_strategy 也要反映「協助通報/確認現場」而不是只安撫本人
- 不要把「我旁邊、這裡、附近、現場」當成明確位置
- 如果最新一句是「有」「沒有」「是」「對」等短回覆，請結合近期對話判斷它在回答什麼、意思是什麼
- reporter_role 為「照顧者/家屬」時：reply_strategy 要同時照顧照顧者情緒與傷病者狀態，稱呼傷病者為「你的家人」
- reporter_role 為「本人」或「本人受害」時：reply_strategy 優先確認本人安全，不要用旁觀者語氣
- reporter_role 為「旁觀者」時：reply_strategy 先給行動指引再問細節，強調不要靠近

輸出格式：
{{
  "intent": "string",
  "primary_need": "string",
  "emotion": "string",
  "reply_strategy": "string",
  "entities": {{
    "location": "string|null",
    "injured": true,
    "weapon": false,
    "danger_active": true
  }}
}}

近期對話（用來解讀短回覆）：
{context_text}

最新文字：
{text}

語音脈絡：
{json.dumps(safe_audio_context, ensure_ascii=False)}

事件抽取：
{json.dumps(safe_extracted, ensure_ascii=False)}
"""
    try:
        resp = call_llm(prompt)
        result_text = (resp.text or "").strip()
        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "").replace("```", "").strip()

        data = parse_llm_json_text(result_text)
        entities = data.get("entities", {}) or {}
        return SemanticUnderstanding(
            intent=data.get("intent") or "未知",
            primary_need=data.get("primary_need") or "釐清狀況",
            emotion=data.get("emotion") or ((audio_context or {}).get("emotion") or "neutral"),
            reply_strategy=data.get("reply_strategy") or "先確認事件重點",
            entities=SemanticEntities(
                location=entities.get("location", fallback_entities.location),
                injured=entities.get("injured", fallback_entities.injured),
                weapon=entities.get("weapon", fallback_entities.weapon),
                danger_active=entities.get("danger_active", fallback_entities.danger_active),
            ),
        )
    except Exception:
        return fallback_semantic


# ======================
# LLM slot 填值（Plan B）
# 在規則系統之後，填補仍為 None 的 slot
# ======================

_SLOT_RELEVANT_BY_CATEGORY: Dict[str, List[str]] = {
    "暴力事件": ["weapon", "people_injured", "danger_active"],
    "醫療急症": ["conscious", "breathing_difficulty", "people_injured"],
    "火災":     ["danger_active", "people_injured"],
    "交通事故": ["people_injured", "danger_active"],
    "可疑人士": ["danger_active"],
    "噪音":     ["danger_active", "people_injured"],
}


def _pending_slots(extracted: Extracted) -> List[str]:
    category = (extracted.category or "").strip()
    relevant = _SLOT_RELEVANT_BY_CATEGORY.get(category, [])
    slot_values: Dict[str, Optional[bool]] = {
        "weapon": extracted.weapon,
        "people_injured": extracted.people_injured,
        "danger_active": extracted.danger_active,
        "conscious": extracted.conscious,
        "breathing_difficulty": extracted.breathing_difficulty,
    }
    return [s for s in relevant if slot_values.get(s) is None]


def llm_extract_slots(
    user_text: str,
    last_question: str,
    extracted: Extracted,
) -> Extracted:
    """
    Focused LLM call to fill remaining None slots.
    Only invoked when rule-based pipeline left slots unfilled and user text
    is long enough that vocabulary matching likely missed nuanced phrasing.
    """
    if not llm_is_ready():
        return extracted

    text = user_text.strip()
    # Very short replies (≤4 chars) are already handled by slot_resolver
    if len(text) <= 4:
        return extracted

    pending = _pending_slots(extracted)
    if not pending:
        return extracted

    category = extracted.category or "未知"
    q_text = (last_question or "（無）")[:100]
    pending_json = json.dumps({s: None for s in pending}, ensure_ascii=False)

    prompt = (
        f"緊急事件 slot 填值。只輸出 JSON，不要解釋。\n"
        f"事件類別：{category}\n"
        f"助理問：{q_text}\n"
        f"使用者說：{text[:150]}\n\n"
        f"根據使用者的話判斷以下 slot（true/false/null，null=無法判斷）：\n"
        f"{pending_json}\n"
        f"輸出 JSON："
    )

    try:
        resp = call_llm(prompt, max_tokens=80)
        result_text = (resp.text or "").strip()
        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "").replace("```", "").strip()

        data = parse_llm_json_text(result_text)
        if not isinstance(data, dict):
            return extracted

        def _safe_bool(val) -> Optional[bool]:
            if val is None:
                return None
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                low = val.lower()
                if low in ("true", "yes", "是", "有"):
                    return True
                if low in ("false", "no", "否", "沒有", "沒"):
                    return False
            return None

        for slot in pending:
            raw = data.get(slot)
            value = _safe_bool(raw)
            if value is None:
                continue
            if slot == "people_injured" and extracted.people_injured is None:
                extracted.people_injured = value
            elif slot == "weapon" and extracted.weapon is None:
                extracted.weapon = value
            elif slot == "danger_active" and extracted.danger_active is None:
                extracted.danger_active = value
            elif slot == "conscious" and extracted.conscious is None:
                extracted.conscious = value
                if value is False:
                    extracted.people_injured = True
            elif slot == "breathing_difficulty" and extracted.breathing_difficulty is None:
                extracted.breathing_difficulty = value
                if value is True:
                    extracted.people_injured = True
    except Exception:
        pass

    return extracted