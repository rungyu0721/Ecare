"""
語意理解模組：啟發式分析 + LLM 語意理解。
"""

import json
from typing import Any, Dict, List, Optional

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
) -> SemanticUnderstanding:
    from backend.services.risk import INCIDENT_DESCRIPTION_KEYWORDS, has_disturbance_signal
    normalized_text = (text or "").strip()
    audio_emotion = get_audio_emotion(audio_context)

    if not normalized_text:
        return SemanticUnderstanding(emotion=audio_emotion, entities=fallback_entities)

    danger_keywords = ["救", "幫", "快點", "危險", "持刀", "拿刀", "流血", "火災", "失火"]
    emotional_support_keywords = ["好怕", "很怕", "不知道怎麼辦", "我快受不了", "我很崩潰"]
    question_keywords = ["怎麼辦", "要怎麼做", "是不是", "可不可以", "需要嗎"]
    disturbance_keywords = list(AGGRESSIVE_DISTURBANCE_KEYWORDS)

    if is_brief_non_emergency_text(normalized_text):
        intent = "詢問"
        primary_need = "開始描述狀況"
        reply_strategy = "先友善接住，再請對方直接描述發生的事"
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

    prompt = f"""
你是語意理解模組。請根據使用者文字、語音情緒與事件抽取結果，輸出語意理解 JSON。

規則：
- 只能輸出 JSON
- intent 只能是：求救、通報、詢問、情緒支持、資訊補充、未知
- primary_need 要簡短描述此刻最需要的協助
- emotion 可綜合文字語氣與語音情緒
- reply_strategy 要描述助理最適合的回應策略
- 如果語音情緒是 panic / fearful 且分數高，優先判斷是否需要立即安全協助
- 如果文字是在描述他人出事，primary_need 與 reply_strategy 也要反映「協助通報/確認現場」而不是只安撫本人
- 不要把「我旁邊、這裡、附近、現場」當成明確位置

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

文字：
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
