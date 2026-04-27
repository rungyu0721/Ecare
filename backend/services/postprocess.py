"""
回應後處理模組：脈絡化、消毒、語氣調整、追問優化。
"""

from typing import Any, Dict, List, Optional

from backend.models import ChatMessage, Extracted, SemanticUnderstanding
from backend.services.extraction import (
    asks_about_danger,
    asks_about_injury,
    asks_about_location,
    asks_about_weapon,
    build_incident_acknowledgement,
    build_medical_acknowledgement,
    get_client_location_text,
    get_dispatch_advice,
    is_likely_incident_detail,
    is_likely_location_response,
    medical_follow_up_question,
    normalize_location_candidate,
    should_ask_scene_danger,
)
from backend.services.emotion import has_high_urgency_emotion_value, normalize_emotion_score
from backend.services.dialogue import (
    get_last_turn_context,
    is_generic_intake_text,
    next_question,
    next_question_from_semantic,  # noqa: F401  re-export for backward compat
)
from backend.services.semantic import (
    get_audio_emotion,
    get_audio_emotion_score,
    has_high_urgency_audio_emotion,
    has_known_location_context,
)


# ======================
# 脈絡化回應
# ======================

def contextualize_reply_and_question(
    messages: List[ChatMessage],
    ex: Extracted,
    reply: str,
    next_q: str,
    risk_level: str,
) -> tuple:
    latest_user_text, previous_assistant_text = get_last_turn_context(messages)
    latest_user_text = latest_user_text.strip()
    previous_assistant_text = previous_assistant_text.strip()
    from backend.services.extraction import enrich_extracted_details
    ex = enrich_extracted_details(ex, latest_user_text)

    def is_yes(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["有", "是", "對", "會", "需要", "有的", "有喔", "有啊", "對啊", "對喔", "嗯", "恩", "要"]

    def is_no(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["沒有", "沒", "不是", "不會", "不用", "沒有喔", "沒有啊", "沒有呢"]

    normalized_user_location = normalize_location_candidate(latest_user_text) or latest_user_text.strip()
    answered_location = is_likely_location_response(latest_user_text)
    answered_incident_detail = is_likely_incident_detail(latest_user_text, ex)
    reply_is_generic = is_generic_intake_text(reply)
    next_question_is_generic = is_generic_intake_text(next_q)

    if (
        ex.location
        and latest_user_text
        and answered_location
        and normalized_user_location == ex.location
        and asks_about_location(previous_assistant_text)
    ):
        if reply_is_generic or asks_about_location(reply) or ex.location not in reply:
            reply = f"收到，地點是在{ex.location}。"
        if next_question_is_generic or asks_about_location(next_q):
            if ex.category == "待確認":
                next_q = "那現場現在是發生了什麼事？像是火災、衝突、車禍，還是有人身體不舒服？"
            else:
                next_q = next_question(ex, risk_level)

    elif asks_about_location(previous_assistant_text) and answered_incident_detail:
        if reply_is_generic or asks_about_location(reply):
            reply = build_incident_acknowledgement(ex)
        if next_question_is_generic or asks_about_location(next_q):
            next_q = next_question(ex, risk_level)

    elif (
        ex.category == "醫療急症"
        and ex.people_injured is True
        and not asks_about_injury(previous_assistant_text)
    ):
        if reply_is_generic or asks_about_injury(reply):
            reply = "收到，現場已經有人受傷，我先幫你確認傷勢和目前危險。"
        if next_question_is_generic or asks_about_injury(next_q):
            next_q = next_question(ex, risk_level)

    elif (
        ex.category
        and ex.category != "待確認"
        and latest_user_text
        and any(kw in previous_assistant_text for kw in ["火災", "可疑人士", "噪音", "醫療急症", "暴力事件", "交通事故"])
        and reply_is_generic
    ):
        reply = f"了解，這看起來是{ex.category}。"
        if next_question_is_generic:
            next_q = next_question(ex, risk_level)

    elif asks_about_injury(previous_assistant_text):
        if ex.category == "醫療急症" and (
            from_medical_signals(latest_user_text)
        ):
            ex.people_injured = True
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            needs_medical_ack = (
                reply_is_generic
                or asks_about_injury(reply)
                or (ex.breathing_difficulty is True and "呼吸困難" not in reply)
                or (ex.conscious is False and "意識不清" not in reply)
            )
            if needs_medical_ack:
                reply = build_medical_acknowledgement(ex, latest_user_text)
            next_q = medical_follow_up_question(ex, risk_level)
        elif is_yes(latest_user_text):
            ex.people_injured = True
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            if reply_is_generic:
                reply = "收到，現場有人受傷，我會優先以需要醫療協助的情況來處理。"
            if next_question_is_generic or asks_about_injury(next_q):
                if should_ask_scene_danger(ex, risk_level):
                    next_q = "目前危險還在持續嗎？例如火勢、衝突，或肇事者還在現場嗎？"
                else:
                    next_q = "請再告訴我現場目前最危急的狀況，我幫你整理成通報內容。"
        elif is_no(latest_user_text):
            ex.people_injured = False
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            if reply_is_generic:
                reply = "了解，目前沒有明確提到有人受傷。"
            if next_question_is_generic or asks_about_injury(next_q):
                if ex.category == "暴力事件" and ex.weapon is None:
                    next_q = "現場對方有持刀、棍棒或其他武器嗎？"
                elif should_ask_scene_danger(ex, risk_level):
                    next_q = "目前危險還在持續嗎？對方或事件還在現場嗎？"

    elif asks_about_weapon(previous_assistant_text):
        if is_yes(latest_user_text):
            ex.weapon = True
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            if reply_is_generic:
                reply = "收到，現場可能有武器，風險會比較高。"
            if next_question_is_generic or asks_about_weapon(next_q):
                next_q = "現在對方或危險因素還在現場嗎？請先確認你自己是否安全。"
        elif is_no(latest_user_text):
            ex.weapon = False
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            if reply_is_generic:
                reply = "了解，目前沒有提到武器。"
            if (next_question_is_generic or asks_about_weapon(next_q)) and should_ask_scene_danger(ex, risk_level):
                next_q = "目前危險還在持續嗎？對方或事件還在現場嗎？"

    elif asks_about_danger(previous_assistant_text):
        if is_yes(latest_user_text):
            ex.danger_active = True
            if reply_is_generic:
                reply = "收到，危險目前還在持續。你先以自身安全為優先，盡量移動到安全的位置。"
            if next_question_is_generic or asks_about_danger(next_q):
                next_q = "如果方便，請再補充現場有幾個人、目前最危急的是什麼，我會幫你整理成通報重點。"
        elif is_no(latest_user_text):
            ex.danger_active = False
            if reply_is_generic:
                reply = "了解，目前危險看起來沒有持續擴大。"
            if next_question_is_generic or asks_about_danger(next_q):
                next_q = "請再補充一下現場的狀況，我會幫你整理後續通報內容。"

    return reply, next_q


def from_medical_signals(text: str) -> bool:
    from backend.services.risk import has_medical_urgency_signal, has_minor_injury_signal
    return (
        has_medical_urgency_signal(text)
        or "意識清楚" in text
        or "意識清醒" in text
        or "意識不清" in text
        or has_minor_injury_signal(text)
        or any(kw in text for kw in ["呼吸正常", "沒有呼吸困難", "沒有喘", "呼吸沒問題", "看起來呼吸正常"])
    )


# ======================
# 消毒回應
# ======================

def sanitize_reply_and_question(
    reply: str,
    next_q: str,
    ex: Extracted,
    risk_level: str,
) -> tuple:
    from backend.services.extraction import normalize_category_name
    reply = (reply or "").strip()
    next_q = (next_q or "").strip()
    ex.category = normalize_category_name(ex.category)

    if ex.location:
        normalized_location = normalize_location_candidate(ex.location)
        if normalized_location:
            ex.location = normalized_location

    for _ in range(4):
        changed = False

        if ex.category == "醫療急症" and reply and asks_about_danger(reply):
            reply = "收到，目前這比較像是醫療急症，我先幫你確認症狀變化。"
            changed = True
        elif ex.location and reply and asks_about_location(reply):
            reply = build_incident_acknowledgement(ex)
            changed = True

        replacement = None
        if ex.category == "醫療急症" and asks_about_danger(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.location and asks_about_location(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.category and ex.category != "待確認" and asks_about_location(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.people_injured is not None and asks_about_injury(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.weapon is not None and asks_about_weapon(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.danger_active is not None and asks_about_danger(next_q):
            replacement = next_question(ex, risk_level)

        if replacement and replacement != next_q:
            next_q = replacement
            changed = True

        if not changed:
            break

    return reply, next_q


# ======================
# 語氣調整
# ======================

def apply_semantic_tone(
    reply: str,
    semantic: SemanticUnderstanding,
    risk_level: str,
    audio_context: Optional[Dict[str, Any]] = None,
) -> str:
    prefix = ""
    audio_emotion = get_audio_emotion(audio_context)
    audio_emotion_score = get_audio_emotion_score(audio_context)
    effective_emotion = semantic.emotion or audio_emotion
    location_known = has_known_location_context(None, semantic, audio_context)

    if has_high_urgency_emotion_value(effective_emotion, audio_emotion_score):
        prefix = "我知道你現在非常慌張，我先幫你抓最重要的事。"
    elif effective_emotion == "fearful":
        prefix = "我知道你現在很害怕，我會先陪你確認安全。"
    elif effective_emotion == "sad":
        prefix = "我有注意到你現在很難受，我會陪你一步一步整理。"
    elif effective_emotion == "angry":
        prefix = "我知道你現在很激動，我先幫你抓重點，避免漏掉最重要的資訊。"
    elif semantic.intent == "情緒支持":
        prefix = "我在，你可以慢慢說，我會陪你一起整理。"

    if has_high_urgency_audio_emotion(audio_context) and risk_level in ["Medium", "High"]:
        if not location_known and "安全" not in reply and "位置" not in reply and "在哪" not in reply:
            suffix = " 你先確認自己是否在安全位置，如果方便，請立刻告訴我目前位置。"
        else:
            suffix = ""
    elif risk_level == "High" and "安全" not in reply:
        if semantic.primary_need and "通報" in semantic.primary_need:
            suffix = (
                " 先留意現場安全。"
                if location_known
                else " 先留意現場安全，如果方便，請立刻告訴我目前位置。"
            )
        else:
            suffix = (
                " 先確認你現在是否安全。"
                if location_known
                else " 先確認你現在是否安全，如果方便，請立刻告訴我目前位置。"
            )
    elif semantic.reply_strategy and "安撫" in semantic.reply_strategy and semantic.primary_need:
        suffix = f" 我會先以{semantic.primary_need}為主。"
    else:
        suffix = ""

    return f"{prefix}{reply}{suffix}".strip()


# ======================
# 開場回應調整
# ======================

def adapt_opening_turn_response(
    messages: List[ChatMessage],
    reply: str,
    next_q: str,
    ex: Extracted,
    semantic: SemanticUnderstanding,
) -> tuple:
    latest_user_text, _ = get_last_turn_context(messages)
    latest_user_text = latest_user_text.strip()

    if not latest_user_text:
        return reply, next_q

    from backend.services.dialogue import is_brief_non_emergency_text
    if (
        ex.category == "待確認"
        and is_brief_non_emergency_text(latest_user_text)
        and (is_generic_intake_text(reply) or is_generic_intake_text(next_q))
    ):
        if "幫" in latest_user_text:
            reply = "可以，我會陪你一步一步整理。"
        else:
            reply = "你好，我在這裡。"

        if semantic.primary_need == "開始描述狀況":
            next_q = "請直接告訴我現在發生什麼事，或你最需要我幫什麼。"
        elif not next_q:
            next_q = "你可以直接說現在發生什麼事，我會幫你整理重點。"

    return reply, next_q
