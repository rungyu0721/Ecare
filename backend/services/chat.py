"""
聊天服務：Prompt 組裝、LLM chat 呼叫、完整對話處理管線。
"""

import json
import string
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import (
    CHAT_CONTEXT_TURNS,
    COMPACT_LOCAL_LLM_MAX_TOKENS,
    FOLLOWUP_CONTEXT_TURNS,
)
from backend.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUserContext,
    Extracted,
    SemanticEntities,
    SemanticUnderstanding,
    latest_user_text,
    model_to_dict,
)
from backend.services.dialogue import (
    build_dialogue_state,
    log_chat_debug,
    next_question,
    should_skip_graph_lookup,
    should_use_compact_chat_path,
)
from backend.services.extraction import (
    apply_turn_context,
    extract_conversation_state,
    generate_incident_summary,
    get_client_location_text,
    get_dispatch_advice,
    merge_extracted,
    normalize_category_name,
    simple_extract,
)
from backend.services.llm import (
    COMPACT_LOCAL_LLM_MAX_TOKENS as _COMPACT_TOKENS,
    call_llm,
    llm_is_ready,
    parse_llm_json_text,
)
from backend.services.postprocess import (
    adapt_opening_turn_response,
    apply_semantic_tone,
    contextualize_reply_and_question,
    next_question_from_semantic,
    sanitize_reply_and_question,
)
from backend.services.risk import apply_structured_risk_floor, simple_risk
from backend.services.semantic import (
    heuristic_semantic_understanding,
    semantic_understanding_from_payload,
)


# ======================
# Prompt 模板載入（模組啟動時快取）
# ======================

def _load_template(name: str) -> string.Template:
    path = Path(__file__).parent.parent / "prompts" / name
    return string.Template(path.read_text(encoding="utf-8"))


_PROMPT_COMPACT = _load_template("chat_compact.txt")
_PROMPT_FULL = _load_template("chat_full.txt")
_PROMPT_SIMPLE = _load_template("chat_simple.txt")


# ======================
# Prompt 建構
# ======================

def build_chat_prompt(
    *,
    context: str,
    audio_context_text: str,
    known_context: str,
    dialogue_state_text: str,
    neo4j_hint: str,
    compact_mode: bool,
) -> str:
    if compact_mode:
        return _PROMPT_COMPACT.substitute(
            audio_context_text=audio_context_text,
            known_context=known_context,
            dialogue_state_text=dialogue_state_text,
            context=context,
        )
    return _PROMPT_FULL.substitute(
        audio_context_text=audio_context_text,
        known_context=known_context,
        dialogue_state_text=dialogue_state_text,
        neo4j_hint=neo4j_hint,
        context=context,
    )


# ======================
# 簡易 LLM 對話
# ======================

def llm_chat(messages: List[ChatMessage]) -> Dict[str, Any]:
    if not llm_is_ready():
        raise RuntimeError("LLM 未初始化")

    recent = messages[-CHAT_CONTEXT_TURNS:]
    context = "\n".join(
        f"{'使用者' if m.role == 'user' else '助手'}：{m.content}"
        for m in recent
    )

    prompt = _PROMPT_SIMPLE.substitute(context=context)

    resp = call_llm(prompt)
    text = (resp.text or "").strip()
    data = parse_llm_json_text(text)
    return data


# ======================
# 完整音頻對話處理
# ======================

def llm_chat_with_audio(
    messages: List[ChatMessage],
    audio_context: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    user_context: Optional[ChatUserContext] = None,
) -> Dict[str, Any]:
    from backend.db.neo4j_db import (
        build_fallback_graph_query_plan,
        build_neo4j_hint,
        graph_reasoning_from_context,
        query_neo4j_by_keyword,
        query_neo4j_by_plan,
        query_neo4j_user_context,
        build_graph_user_identity,
    )

    if not llm_is_ready():
        raise RuntimeError("LLM client not ready")

    conversation_state = extract_conversation_state(messages)
    user_identity = build_graph_user_identity(session_id, user_context)
    client_location_text = get_client_location_text(audio_context)
    if client_location_text and not conversation_state.location:
        conversation_state.location = client_location_text
        conversation_state.dispatch_advice = get_dispatch_advice(
            conversation_state.category,
            conversation_state.weapon,
            conversation_state.people_injured,
        )

    preview_risk_score, preview_risk_level = simple_risk(
        latest_user_text(messages) or " ".join(m.content for m in messages if m.role == "user")
    )
    preview_risk_score, preview_risk_level = apply_structured_risk_floor(
        " ".join(m.content for m in messages if m.role == "user"),
        conversation_state,
        preview_risk_score,
        preview_risk_level,
    )
    preview_semantic = heuristic_semantic_understanding(
        latest_user_text(messages),
        audio_context,
        SemanticEntities(
            location=conversation_state.location or client_location_text,
            injured=conversation_state.people_injured,
            weapon=conversation_state.weapon,
            danger_active=conversation_state.danger_active,
        ),
    )
    pre_dialogue_state = build_dialogue_state(
        messages,
        conversation_state,
        preview_semantic,
        preview_risk_level,
        audio_context,
    )
    latest_text = latest_user_text(messages)
    compact_chat_path = should_use_compact_chat_path(messages, pre_dialogue_state, latest_text)
    skip_graph_lookup = should_skip_graph_lookup(compact_chat_path, latest_text, conversation_state)
    context_turn_limit = FOLLOWUP_CONTEXT_TURNS if compact_chat_path else CHAT_CONTEXT_TURNS
    recent = messages[-context_turn_limit:]
    context = "\n".join(
        f"{'使用者' if m.role == 'user' else '助理'}：{m.content}"
        for m in recent
    )

    audio_context_text = "無"
    if audio_context:
        safe_audio_context = {
            "transcript": audio_context.get("transcript"),
            "emotion": audio_context.get("emotion"),
            "emotion_score": audio_context.get("emotion_score"),
            "situation": audio_context.get("situation"),
            "risk_level": audio_context.get("risk_level"),
            "risk_score": audio_context.get("risk_score"),
            "extracted": audio_context.get("extracted"),
            "client_location": audio_context.get("client_location"),
        }
        audio_context_text = json.dumps(safe_audio_context, ensure_ascii=False)

    graph_plan = build_fallback_graph_query_plan(messages, conversation_state, audio_context)
    neo4j_info: Dict[str, Any] = {}
    user_graph_context: Dict[str, Any] = {}
    if not skip_graph_lookup:
        graph_plan = graph_reasoning_from_context(messages, conversation_state, audio_context)
        neo4j_info = query_neo4j_by_plan(graph_plan)
        if not neo4j_info:
            neo4j_info = query_neo4j_by_keyword(context)
        user_graph_context = query_neo4j_user_context(user_identity)
    neo4j_hint = build_neo4j_hint(graph_plan, neo4j_info, user_graph_context)

    known_context = json.dumps(
        {
            "category": conversation_state.category,
            "location": conversation_state.location,
            "people_injured": conversation_state.people_injured,
            "weapon": conversation_state.weapon,
            "danger_active": conversation_state.danger_active,
            "dispatch_advice": conversation_state.dispatch_advice,
        },
        ensure_ascii=False,
    )
    dialogue_state_text = json.dumps(model_to_dict(pre_dialogue_state), ensure_ascii=False)
    prompt = build_chat_prompt(
        context=context,
        audio_context_text=audio_context_text,
        known_context=known_context,
        dialogue_state_text=dialogue_state_text,
        neo4j_hint=neo4j_hint,
        compact_mode=compact_chat_path,
    )
    llm_max_tokens = COMPACT_LOCAL_LLM_MAX_TOKENS if compact_chat_path else None
    print(
        "E-CARE chat path ->"
        f" mode={'compact' if compact_chat_path else 'full'},"
        f" skip_graph={str(skip_graph_lookup).lower()},"
        f" context_turns={len(recent)},"
        f" prompt_chars={len(prompt)}"
    )
    resp = call_llm(prompt, max_tokens=llm_max_tokens)
    text = (resp.text or "").strip()
    data = parse_llm_json_text(text)
    if isinstance(data, dict):
        data["_meta"] = {
            "chat_path": "compact" if compact_chat_path else "full",
            "skip_graph_lookup": skip_graph_lookup,
            "context_turns": len(recent),
        }
    return data


# ======================
# 對話請求處理管線
# ======================

_EMPTY_CONTEXT_RESPONSE = ChatResponse(
    reply="請先描述一下目前發生的情況，我會協助你整理資訊。",
    risk_score=0.1,
    risk_level="Low",
    should_escalate=False,
    next_question="請問目前發生了什麼事？",
    extracted=Extracted(
        category="待確認",
        location=None,
        people_injured=None,
        weapon=None,
        danger_active=None,
        dispatch_advice="建議派遣：待確認",
        description="案件類型：待確認 | 地點：未提供 | 風險等級：Low | 建議派遣：待確認",
    ),
    semantic=SemanticUnderstanding(),
)


def process_chat_request(
    messages: List[ChatMessage],
    audio_context: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    user_context: Optional[ChatUserContext] = None,
) -> ChatResponse:
    context = " ".join(m.content for m in messages if m.role == "user").strip()
    latest_text = latest_user_text(messages)
    conversation_state = extract_conversation_state(messages)

    if not context:
        return _EMPTY_CONTEXT_RESPONSE

    try:
        data = llm_chat_with_audio(messages, audio_context, session_id, user_context)
        extracted_raw = data.get("extracted", {}) or {}
        client_location_text = get_client_location_text(audio_context)

        ex = Extracted(
            category=extracted_raw.get("category"),
            location=extracted_raw.get("location"),
            people_injured=extracted_raw.get("people_injured"),
            weapon=extracted_raw.get("weapon"),
            danger_active=extracted_raw.get("danger_active"),
            reporter_role=extracted_raw.get("reporter_role"),
            conscious=extracted_raw.get("conscious"),
            breathing_difficulty=extracted_raw.get("breathing_difficulty"),
            fever=extracted_raw.get("fever"),
            symptom_summary=extracted_raw.get("symptom_summary"),
            dispatch_advice=extracted_raw.get("dispatch_advice"),
            description=extracted_raw.get("description"),
        )
        ex.category = normalize_category_name(ex.category)
        ex = apply_turn_context(messages, ex)
        if not ex.location and client_location_text:
            ex.location = client_location_text
        ex = merge_extracted(conversation_state, ex)

        risk_score = float(data.get("risk_score", 0.2))
        risk_score = max(0.0, min(1.0, risk_score))
        risk_level = data.get("risk_level", "Low")
        if risk_level not in ["Low", "Medium", "High"]:
            risk_level = "Low"
        risk_score, risk_level = apply_structured_risk_floor(context, ex, risk_score, risk_level)
        should_escalate = bool(data.get("should_escalate", False)) or risk_level == "High"

        if not ex.dispatch_advice:
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
        ex.description = generate_incident_summary(ex, risk_level)

        semantic_payload = data.get("semantic")
        semantic = semantic_understanding_from_payload(semantic_payload, audio_context, ex)
        if not isinstance(semantic_payload, dict):
            semantic = heuristic_semantic_understanding(
                context, audio_context, semantic.entities,
            )

        reply = data.get("reply") or "我會一步一步協助你整理資訊。"
        nq = data.get("next_question") or next_question(ex, risk_level)
        llm_reply, llm_nq = reply, nq
        llm_category = normalize_category_name(extracted_raw.get("category"))

        reply, nq = contextualize_reply_and_question(messages, ex, reply, nq, risk_level)
        reply, nq = adapt_opening_turn_response(messages, reply, nq, ex, semantic)
        reply = apply_semantic_tone(reply, semantic, risk_level, audio_context)
        nq = next_question_from_semantic(nq, semantic, ex, risk_level, audio_context)
        reply, nq = sanitize_reply_and_question(reply, nq, ex, risk_level)

        dialogue_state = build_dialogue_state(messages, ex, semantic, risk_level, audio_context)
        log_chat_debug(
            "final_success", latest_text, ex, semantic, dialogue_state,
            reply, nq, risk_level, risk_score,
            llm_category=llm_category,
            reply_changed=reply != llm_reply,
            next_question_changed=nq != llm_nq,
        )
        return ChatResponse(
            reply=reply,
            risk_score=risk_score,
            risk_level=risk_level,
            should_escalate=should_escalate,
            next_question=nq,
            extracted=ex,
            semantic=semantic,
        )

    except Exception as e:
        print("LLM fallback:", str(e))

        score, level = simple_risk(context)
        ex = simple_extract(context)
        ex = apply_turn_context(messages, ex)
        client_location_text = get_client_location_text(audio_context)
        if not ex.location and client_location_text:
            ex.location = client_location_text
        ex = merge_extracted(conversation_state, ex)
        score, level = apply_structured_risk_floor(context, ex, score, level)
        ex.description = generate_incident_summary(ex, level)

        semantic = heuristic_semantic_understanding(
            context, audio_context,
            SemanticEntities(
                location=ex.location,
                injured=ex.people_injured,
                weapon=ex.weapon,
                danger_active=ex.danger_active,
            ),
        )
        if level == "High":
            reply = "我了解你現在很緊張，我會快速協助你整理資訊並引導你進行通報。"
        elif level == "Medium":
            reply = "我了解你的狀況，我會一步步協助你整理必要資訊。"
        else:
            reply = "我在這裡，我會協助你把事情講清楚。"

        nq = next_question_from_semantic(next_question(ex, level), semantic, ex, level, audio_context)
        reply, nq = contextualize_reply_and_question(messages, ex, reply, nq, level)
        reply, nq = adapt_opening_turn_response(messages, reply, nq, ex, semantic)
        reply = apply_semantic_tone(reply, semantic, level, audio_context)
        reply, nq = sanitize_reply_and_question(reply, nq, ex, level)

        dialogue_state = build_dialogue_state(messages, ex, semantic, level, audio_context)
        log_chat_debug(
            "final_fallback", latest_text, ex, semantic, dialogue_state,
            reply, nq, level, score,
        )
        return ChatResponse(
            reply=reply,
            risk_score=score,
            risk_level=level,
            should_escalate=(level == "High"),
            next_question=nq,
            extracted=ex,
            semantic=semantic,
        )
