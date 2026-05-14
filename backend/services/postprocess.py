"""
回應後處理模組：脈絡化、消毒、語氣調整、追問優化。
"""

import re
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


QUESTION_INTENT_KEYWORDS = {
    "burn_severity": [
        "燙傷", "燒傷", "灼傷", "燙到", "燒到", "水泡", "面積", "焦黑", "發白",
        "手掌", "關節", "沖洗", "範圍",
    ],
    "consciousness": ["意識", "清醒", "反應", "叫得醒", "叫不醒", "昏倒", "暈倒"],
    "breathing": ["呼吸", "喘", "喘不過氣", "吸不到氣", "沒呼吸", "說完整句子"],
    "injury": ["受傷", "傷者", "流血", "傷勢", "送醫", "救護車", "受困"],
    "weapon": ["武器", "刀", "持刀", "棍棒", "槍"],
    "danger_active": [
        "危險", "還在現場", "還在持續", "持續威脅", "威脅", "對方現在",
        "火勢", "濃煙", "車道", "求救", "打鬥", "衝突", "還在吵",
    ],
    "fire_active": ["火勢", "濃煙", "冒煙", "越燒越大", "起火點"],
    "trapped": ["受困", "困在", "裡面", "出不來"],
    "traffic_blocking": ["車道", "車流", "危險位置", "卡在", "事故車輛", "路中間", "路邊", "移到旁邊"],
}


def previous_question_intent(text: str, category: Optional[str] = None) -> Optional[str]:
    normalized = (text or "").strip()
    if not normalized:
        return None

    hits = {
        intent
        for intent, keywords in QUESTION_INTENT_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    }
    if not hits:
        return None

    category = category or ""
    if category == "醫療急症":
        for intent in ["burn_severity", "consciousness", "breathing", "injury"]:
            if intent in hits:
                return intent
    if category == "火災":
        for intent in ["trapped", "fire_active", "injury", "danger_active"]:
            if intent in hits:
                return intent
    if category == "交通事故":
        for intent in ["injury", "traffic_blocking", "danger_active"]:
            if intent in hits:
                return intent
    if category in ["暴力事件", "可疑人士", "噪音"]:
        for intent in ["weapon", "injury", "danger_active"]:
            if intent in hits:
                return intent

    priority = [
        "burn_severity", "consciousness", "breathing", "weapon", "trapped",
        "traffic_blocking", "fire_active", "injury", "danger_active",
    ]
    for intent in priority:
        if intent in hits:
            return intent
    return None


def apply_short_answer_to_event_slot(
    ex: Extracted,
    latest_user_text: str,
    previous_assistant_text: str,
    risk_level: str,
    *,
    is_yes,
    is_no,
    is_unknown,
) -> Optional[tuple]:
    if not (is_yes(latest_user_text) or is_no(latest_user_text) or is_unknown(latest_user_text)):
        return None

    intent = previous_question_intent(previous_assistant_text, ex.category)
    if not intent:
        return None

    from backend.services.extraction.entities import has_burn_symptom
    answered_yes = is_yes(latest_user_text)
    answered_unknown = is_unknown(latest_user_text)

    if intent == "burn_severity" and ex.category == "醫療急症" and has_burn_symptom(ex):
        ex.people_injured = True
        if answered_unknown:
            reply = (
                "不確定也沒關係，先當作需要觀察處理。"
                "如果安全，請先用流動清水沖洗燙傷處至少 10 分鐘，不要刺破水泡或塗抹偏方。"
            )
            next_q = "你能看到燙傷範圍是否變大、出現水泡，或在臉、手掌、關節附近嗎？"
            return reply, next_q
        if answered_yes:
            ex.dispatch_advice = (
                "建議處置：冷水沖洗並評估嚴重度；嚴重燒燙傷請立刻就醫或撥 119"
            )
            reply = (
                "收到，這可能不是單純輕微燙傷。"
                "請先讓傷者離開熱源，用流動清水沖洗，避免刺破水泡或撕開黏住的衣物。"
            )
            next_q = "燙傷範圍大約多大？是在臉、手掌、關節附近，或皮膚有焦黑、發白嗎？"
        else:
            ex.dispatch_advice = (
                "建議處置：先冷水沖洗並觀察；若範圍大、起水泡或疼痛加劇再就醫/119"
            )
            reply = (
                "了解，目前沒有明顯嚴重燒燙傷徵象。"
                "請先持續用流動清水沖洗燙傷處至少 10 分鐘，保持傷處乾淨，不要塗抹偏方。"
            )
            next_q = "疼痛有加劇、範圍變大，或後來出現水泡嗎？"
        return reply, next_q

    if intent == "consciousness" and ex.category == "醫療急症":
        ex.people_injured = True
        if answered_unknown:
            reply = "不確定意識狀況時，先把它當作可能危險來處理。"
            next_q = "如果你能安全靠近，請看傷者胸口是否有起伏、是否能出聲回應；若沒有反應或呼吸不正常，請立刻撥 119。"
            return reply, next_q
        ex.conscious = answered_yes
        if answered_yes:
            reply = "了解，傷者目前還有反應。"
            next_q = "呼吸是否正常？有沒有喘不過氣、嘴唇發紫，或症狀快速加重？"
        else:
            reply = "收到，傷者目前沒有明確反應，這需要立即處理。"
            next_q = "請立刻撥打 119；如果你能安全靠近，請確認胸口是否有起伏或有沒有正常呼吸。"
        return reply, next_q

    if intent == "breathing" and ex.category == "醫療急症":
        ex.people_injured = True
        if answered_unknown:
            reply = "不確定呼吸狀況時，請先觀察胸口是否有規律起伏。"
            next_q = "如果看不出正常呼吸、嘴唇發紫或沒有反應，請立刻撥 119，並照 119 指示處理。"
            return reply, next_q
        ex.breathing_difficulty = not answered_yes
        if answered_yes:
            reply = "了解，目前呼吸看起來正常。"
            next_q = "症狀有加重、胸痛、再次昏倒，或需要送醫嗎？"
        else:
            reply = "收到，呼吸可能不正常，這是高風險狀況。"
            next_q = "請立刻撥打 119，並依照 119 指示確認呼吸與是否需要 AED。"
        return reply, next_q

    if intent in ["injury", "trapped"]:
        if answered_unknown:
            reply = "不確定也可以，先不要冒險靠近。"
            next_q = "請從安全位置觀察，現場看起來有人倒地、受困、流血，或需要救護車嗎？"
            return reply, next_q
        ex.people_injured = answered_yes
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
        if answered_yes:
            reply = "收到，現場有人受傷或受困，我會以需要優先協助來整理。"
            next_q = next_question(ex, risk_level)
        else:
            reply = "了解，目前沒有明確受傷或受困。"
            next_q = next_question(ex, risk_level)
        return reply, next_q

    if intent == "weapon":
        if answered_unknown:
            reply = "不確定是否有武器時，先當作有風險處理，請保持距離並避免介入。"
            next_q = next_question(ex, risk_level)
            return reply, next_q
        ex.weapon = answered_yes
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
        if answered_yes:
            reply = "收到，現場可能有武器，請先保持距離並確保自身安全。"
        else:
            reply = "了解，目前沒有提到武器。"
        next_q = next_question(ex, risk_level)
        return reply, next_q

    if intent in ["danger_active", "fire_active", "traffic_blocking"]:
        if answered_unknown:
            reply = "不確定現場是否還有危險時，請先保持安全距離。"
            next_q = "如果你能安全觀察，請回報危險是否還在持續，例如火勢、衝突、車流阻塞或有人求救。"
            return reply, next_q
        ex.danger_active = answered_yes
        if answered_yes:
            reply = "收到，危險目前還在持續，請先以自身安全為優先。"
        else:
            reply = "了解，目前危險看起來沒有持續擴大。"
        next_q = next_question(ex, risk_level)
        return reply, next_q

    return None


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
    from backend.services.extraction.entities import burn_dispatch_advice, has_burn_symptom
    burn_advice = burn_dispatch_advice(latest_user_text, ex)
    if burn_advice:
        ex.dispatch_advice = burn_advice

    def is_yes(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["有", "是", "對", "會", "需要", "有的", "有喔", "有啊", "對啊", "對喔", "嗯", "恩", "要"]

    def is_no(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["沒有", "沒", "不是", "不會", "不用", "沒有喔", "沒有啊", "沒有呢"]

    def is_unknown(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["不確定", "不知道", "不清楚", "看不出來", "不太確定", "我不知道", "我不清楚"]

    normalized_user_location = normalize_location_candidate(latest_user_text) or latest_user_text.strip()
    answered_location = is_likely_location_response(latest_user_text)
    answered_incident_detail = is_likely_incident_detail(latest_user_text, ex)
    reply_is_generic = is_generic_intake_text(reply)
    next_question_is_generic = is_generic_intake_text(next_q)

    slot_result = apply_short_answer_to_event_slot(
        ex,
        latest_user_text,
        previous_assistant_text,
        risk_level,
        is_yes=is_yes,
        is_no=is_no,
        is_unknown=is_unknown,
    )
    if slot_result:
        return slot_result

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


REPORT_STYLE_MARKERS = (
    "案件類型：",
    "地點：",
    "通報角色：",
    "傷勢：",
    "意識：",
    "呼吸：",
    "症狀摘要：",
    "危險狀況：",
    "風險等級：",
    "建議派遣：",
)


def looks_like_report_style_reply(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    marker_hits = sum(marker in normalized for marker in REPORT_STYLE_MARKERS)
    return marker_hits >= 2 or normalized.count(" | ") >= 2


def _question_sentences(text: str) -> List[str]:
    return [
        sentence.strip()
        for sentence in re.findall(r"[^。！？!?]+[。！？!?]?", text or "")
        if sentence.strip().endswith(("?", "？"))
    ]


def _question_topics(text: str) -> set:
    normalized = re.sub(r"[\s，,。！？!?、：:；;（）()「」『』]+", "", text or "")
    topic_groups = {
        "location": ["地點", "位置", "在哪", "哪裡", "地址", "路口"],
        "injury": ["受傷", "傷者", "流血", "送醫", "救護車"],
        "weapon": ["武器", "刀", "槍", "棍棒", "持刀"],
        "danger": ["危險", "威脅", "攻擊", "衝突", "靠近", "追", "還在現場"],
        "ongoing": ["持續", "還在", "仍在", "沒有停", "現在還", "平靜", "緩和", "停下"],
        "disturbance": ["吵架", "爭吵", "吵鬧", "噪音", "大叫", "吼叫", "摔東西"],
        "breathing": ["呼吸", "喘", "沒呼吸", "吸不到氣"],
        "conscious": ["意識", "反應", "叫得醒", "叫不醒", "清醒"],
        "fire": ["火", "火勢", "濃煙", "冒煙", "燃燒"],
        "traffic": ["車禍", "車道", "車流", "撞", "事故"],
        "detail": ["狀況", "發生什麼", "補充", "描述", "看到", "聽到"],
    }
    return {
        topic
        for topic, keywords in topic_groups.items()
        if any(keyword in normalized for keyword in keywords)
    }


def _questions_are_similar(a: str, b: str) -> bool:
    topics_a = _question_topics(a)
    topics_b = _question_topics(b)
    if not topics_a or not topics_b:
        return False

    overlap = topics_a & topics_b
    if len(overlap) >= 2:
        return True
    if "detail" in overlap:
        return True
    if "disturbance" in overlap and ("ongoing" in topics_a or "ongoing" in topics_b):
        return True
    if "danger" in overlap and ("ongoing" in topics_a or "ongoing" in topics_b):
        return True
    return False


def remove_duplicate_next_question(reply: str, next_q: str) -> str:
    next_q = (next_q or "").strip()
    if not next_q:
        return ""
    for question in _question_sentences(reply):
        if _questions_are_similar(question, next_q):
            return ""
    return next_q


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

    if looks_like_report_style_reply(reply):
        if ex.category == "醫療急症":
            reply = build_medical_acknowledgement(ex, ex.description or "")
        else:
            reply = build_incident_acknowledgement(ex)

    if looks_like_report_style_reply(next_q):
        next_q = next_question(ex, risk_level)

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

    next_q = remove_duplicate_next_question(reply, next_q)

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
            next_q = "請直接告訴我現在發生什麼事，或你看到、聽到什麼狀況。"
        elif not next_q:
            next_q = "你可以直接說現在發生什麼事，我會幫你整理重點。"

    return reply, next_q
