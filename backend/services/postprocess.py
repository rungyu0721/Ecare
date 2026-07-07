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
from backend.services.first_aid_guides import get_guide
from backend.services.incident_taxonomy import is_remote_rescue_extracted


# 已說過就不再重複的固定句型
_REPEATED_PHRASE_PATTERNS = [
    "系統已列為高風險通報",
    "請保持手機可接通",
    "先確認你現在是否安全",
    "先留意現場安全",
    "先確認自己是否安全",
]


def _remove_repeated_phrases(text: str, assistant_history: List[str]) -> str:
    """移除在最近幾輪 assistant 訊息中已出現過的固定句型片段。"""
    if not text or not assistant_history:
        return text
    combined = "".join(assistant_history[-4:])
    result = text
    for phrase in _REPEATED_PHRASE_PATTERNS:
        if phrase in combined and phrase in result:
            # 嘗試移除整個含該片語的子句（以，或。分隔）
            result = re.sub(
                r"[^，。！？]*" + re.escape(phrase) + r"[^，。！？]*[，。！？]?",
                "",
                result,
            )
    return result.strip("，。！？ ")


def _build_unresponsive_next_q(previous_assistant_text: str, *, remote_rescue: bool = False) -> str:
    """根據前一輪已說的內容，決定意識喪失時的下一步引導，避免重複。"""
    if remote_rescue:
        return (
            "請保持手機可接通並保留電力；如果已接通 119，請開擴音依照指示處理，"
            "同時準備回報 GPS 座標、步道地標、同行人數和傷者狀況。"
        )

    prev = previous_assistant_text or ""
    already_aed = "AED" in prev
    already_cpr = "CPR" in prev or "胸外按壓" in prev
    already_breathing = "正常呼吸" in prev or "胸口起伏" in prev or "胸口是否有起伏" in prev

    if already_aed and already_cpr:
        return "AED 有找到了嗎？旁邊有人可以幫忙嗎？"
    if already_cpr:
        return "CPR 繼續做，每次按壓讓胸口下壓約 5 公分，速度大約每秒兩下。AED 有找到嗎？"
    if already_breathing:
        return "請依救援指示開始 CPR，並請旁邊的人找 AED。"
    return (
        "系統已列為高風險通報，請保持手機可接通。"
        "請確認胸口是否有起伏、有沒有正常呼吸；"
        "如果沒有正常呼吸，請依救援指示開始 CPR，並請旁邊的人找 AED。"
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
        "還在附近", "跟著", "尾隨", "在附近",
    ],
    "fire_active": ["火勢", "濃煙", "冒煙", "越燒越大", "起火點"],
    "trapped": ["受困", "困在", "裡面", "出不來"],
    "traffic_blocking": ["車道", "車流", "危險位置", "卡在", "事故車輛", "路中間", "路邊", "移到旁邊"],
}


NO_NORMAL_BREATHING_TERMS = [
    "沒呼吸", "沒有呼吸", "不呼吸", "呼吸不正常", "看不出呼吸",
    "胸口沒有起伏", "胸口沒起伏", "只有喘一下", "像打鼾", "瀕死式呼吸",
]
CALLED_119_TERMS = ["已經撥119", "已撥119", "打119了", "撥了119", "正在跟119", "119接了"]
AED_ARRIVED_TERMS = [
    "AED到了", "aed到了", "拿到AED", "拿到aed", "找到AED", "找到aed",
    "有AED", "有aed", "AED在旁邊", "aed在旁邊",
]
CHOKING_TERMS = ["噎到", "哽塞", "噎住", "卡住喉嚨", "異物卡住", "說不出話", "臉發紫"]
BLEEDING_TERMS = ["大量流血", "血流不止", "血流不停", "流血不止", "止不住血", "噴血", "割傷", "刀割傷"]
FOREIGN_OBJECT_TERMS = ["玻璃插", "玻璃碎片", "刀插", "異物插", "東西插著", "插在傷口"]
SEIZURE_TERMS = ["抽搐", "癲癇", "口吐白沫", "眼睛上翻", "眼睛往上翻", "全身抖"]
STROKE_TERMS = ["嘴歪", "臉歪", "半邊無力", "一側無力", "手腳無力", "說話不清楚", "口齒不清", "突然說不出話", "走路不穩"]
CHEST_PAIN_TERMS = ["胸痛", "胸悶", "胸口悶", "胸口痛", "心臟痛", "胸部壓迫", "胸口壓迫"]
CHEST_PAIN_HIGH_TERMS = ["冒冷汗", "冷汗", "喘", "喘不過氣", "左手", "左手臂", "下巴痛", "臉色發白", "超過五分鐘", "超過5分鐘"]
HEAT_ILLNESS_TERMS = ["中暑", "熱衰竭", "曬太陽昏倒", "皮膚很燙", "沒有流汗", "沒流汗", "熱到昏倒"]
FRACTURE_TERMS = ["骨折", "骨裂", "骨頭斷", "骨頭變形", "手臂變形", "腿變形", "腫很大", "不能動", "骨頭穿出"]


def has_no_normal_breathing(text: str) -> bool:
    return any(term in text for term in NO_NORMAL_BREATHING_TERMS)


def has_called_119(text: str) -> bool:
    compact = text.replace(" ", "")
    return any(term in compact for term in CALLED_119_TERMS)


def has_aed_arrived(text: str) -> bool:
    compact = text.replace(" ", "")
    return any(term in compact for term in AED_ARRIVED_TERMS)


def cpr_guidance_for_unresponsive(ex: Extracted, *, aed_ready: bool = False) -> tuple[str, str]:
    if aed_ready:
        return get_guide("cpr_aed_ready")
    if is_remote_rescue_extracted(ex.symptom_summary):
        subject = "你的家人" if ex.reporter_role == "照顧者/家屬" else "傷者"
        reply = f"收到，{subject}目前沒有正常反應或呼吸，這是高風險狀況，請立刻撥打 119。"
        advice = (
            "請保持手機可接通並保留電力；如果已接通 119，請開擴音依照指示處理，"
            "同時準備回報 GPS 座標、步道地標、同行人數和傷者狀況。"
        )
        return reply, advice
    subject = "你的家人" if ex.reporter_role == "照顧者/家屬" else "傷者"
    reply, advice = get_guide("cpr_no_aed")
    return reply.format(subject=subject), advice


def has_any_term(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def first_aid_guidance_for_text(text: str, ex: Extracted) -> Optional[tuple[str, str]]:
    if not text:
        return None

    if has_any_term(text, CHOKING_TERMS):
        ex.category = "醫療急症"
        ex.people_injured = True
        if "嬰兒" in text or "寶寶" in text or "未滿1歲" in text or "未滿一歲" in text:
            return get_guide("choking_infant")
        return get_guide("choking")

    if has_any_term(text, BLEEDING_TERMS) or (
        has_any_term(text, FOREIGN_OBJECT_TERMS) and ("流血" in text or "出血" in text)
    ):
        ex.category = "醫療急症"
        ex.people_injured = True
        if has_any_term(text, FOREIGN_OBJECT_TERMS):
            return get_guide("bleeding_foreign_object")
        return get_guide("bleeding")

    if has_any_term(text, SEIZURE_TERMS):
        ex.category = "醫療急症"
        ex.people_injured = True
        return get_guide("seizure")

    if has_any_term(text, STROKE_TERMS):
        ex.category = "醫療急症"
        ex.people_injured = True
        return get_guide("stroke")

    if has_any_term(text, CHEST_PAIN_TERMS) and (
        has_any_term(text, CHEST_PAIN_HIGH_TERMS) or ex.breathing_difficulty is True
    ):
        ex.category = "醫療急症"
        ex.people_injured = True
        return get_guide("chest_pain")

    if has_any_term(text, HEAT_ILLNESS_TERMS):
        ex.category = "醫療急症"
        ex.people_injured = True
        return get_guide("heat_illness")

    if has_any_term(text, FRACTURE_TERMS):
        ex.category = "醫療急症"
        ex.people_injured = True
        if "車禍" in text or "被車撞" in text or "撞車" in text:
            return get_guide("fracture_traffic")
        return get_guide("fracture")

    return None


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
            next_q = "請先確認你自己安全；如果你就在傷者旁邊，請看胸口是否有起伏、是否能出聲回應。周圍有車流、火煙、暴力或其他明顯危險時不要靠近；如果沒有反應或呼吸不正常，請保持手機可接通並準備依救援指示處理。"
            return reply, next_q
        ex.conscious = answered_yes
        if answered_yes:
            reply = "了解，傷者目前還有反應。"
            next_q = "呼吸是否正常？有沒有喘不過氣、嘴唇發紫，或症狀快速加重？"
        else:
            reply = "收到，傷者目前沒有明確反應，這需要立即處理。"
            next_q = _build_unresponsive_next_q(
                previous_assistant_text,
                remote_rescue=is_remote_rescue_extracted(ex.symptom_summary),
            )
        return reply, next_q

    if intent == "breathing" and ex.category == "醫療急症":
        ex.people_injured = True
        if answered_unknown:
            reply = "不確定呼吸狀況時，請先觀察胸口是否有規律起伏。"
            next_q = "如果看不出正常呼吸、嘴唇發紫或沒有反應，請保持手機可接通，並準備依救援指示處理。"
            return reply, next_q
        ex.breathing_difficulty = not answered_yes
        if answered_yes:
            reply = "了解，目前呼吸看起來正常。"
            next_q = "症狀有加重、胸痛、再次昏倒，或需要送醫嗎？"
        else:
            reply, next_q = cpr_guidance_for_unresponsive(ex)
        return reply, next_q

    if intent in ["injury", "trapped"]:
        if answered_unknown:
            ex.people_injured = None
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
            ex.weapon = None
            reply = "不確定是否有武器也沒關係，先把它當作有風險處理。請你先保持距離、不要介入，保護自己最重要。"
            next_q = next_question(ex, risk_level)
            return reply, next_q
        ex.weapon = answered_yes
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
        if answered_yes:
            reply = "收到，現場可能有武器，這會讓人很緊張。請先不要靠近，確保自己在安全位置。"
        else:
            reply = "了解，目前沒有提到武器。"
        next_q = next_question(ex, risk_level)
        return reply, next_q

    if intent in ["danger_active", "fire_active", "traffic_blocking"]:
        if answered_unknown:
            ex.danger_active = None
            reply = "不確定現場是否還有危險時，請先保持安全距離。"
            next_q = "如果你能安全觀察，請回報危險是否還在持續，例如火勢、衝突、車流阻塞或有人求救。"
            return reply, next_q
        ex.danger_active = answered_yes
        if answered_yes:
            reply = "收到，危險目前還在持續。你先以自身安全為優先，不要勉強靠近或介入。"
            if ex.category == "暴力事件" and ex.weapon is None:
                next_q = "請先往安全方向離開現場，保持距離。現場有沒有持刀、棍棒或其他武器？"
            else:
                next_q = next_question(ex, risk_level)
        else:
            # "沒有了" carries the nuance that danger has already gone; plain "沒有" just denies it
            if latest_user_text.strip() in ["沒有了", "沒了", "不在了", "走了", "離開了"]:
                reply = "了解，情況看起來已經緩和，對方應該已離開，不在附近了。"
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
        return normalized in ["沒有", "沒", "不是", "不會", "不用", "沒有喔", "沒有啊", "沒有呢", "沒有了", "沒了", "不在了", "沒了呢"]

    def is_unknown(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["不確定", "不知道", "不清楚", "看不出來", "不太確定", "我不知道", "我不清楚"]

    normalized_user_location = normalize_location_candidate(latest_user_text) or latest_user_text.strip()
    answered_location = is_likely_location_response(latest_user_text)
    answered_incident_detail = is_likely_incident_detail(latest_user_text, ex)
    reply_is_generic = is_generic_intake_text(reply)
    next_question_is_generic = is_generic_intake_text(next_q)

    # Ambulance arrived — hand-off guidance supersedes everything else
    AMBULANCE_ARRIVED_TERMS = ["救護車到了", "救護車來了", "救護車到達", "救護車抵達"]
    if any(term in latest_user_text for term in AMBULANCE_ARRIVED_TERMS):
        reply = "好，收到！救護車已到，繼續做直到他們接手。"
        next_q = "請準備和救護人員交接，告訴救護人員目前狀況，以及有沒有使用 AED。"
        return reply, next_q

    if has_aed_arrived(latest_user_text) and (
        ex.category == "醫療急症"
        or any(term in previous_assistant_text for term in ["AED", "CPR", "無反應", "沒有反應", "正常呼吸", "胸口"])
    ):
        ex.category = "醫療急症"
        ex.people_injured = True
        ex.aed_confirmed = True
        return cpr_guidance_for_unresponsive(ex, aed_ready=True)

    if ex.category == "醫療急症" and (ex.conscious is False or ex.breathing_difficulty is True):
        if has_aed_arrived(latest_user_text):
            ex.people_injured = True
            ex.aed_confirmed = True
            return cpr_guidance_for_unresponsive(ex, aed_ready=True)
        # CPR already in progress — acknowledge and guide
        CPR_STARTED_TERMS = ["已經開始CPR", "已開始CPR", "正在做CPR", "在做CPR", "已經在做CPR"]
        if any(term in latest_user_text for term in CPR_STARTED_TERMS):
            ex.people_injured = True
            ex.conscious = False
            ex.breathing_difficulty = True
            reply = "好，做得好！繼續保持按壓節奏。"
            if is_remote_rescue_extracted(ex.symptom_summary):
                next_q = "請保持手機可接通並保留電力；如果已接通 119，請開擴音依照救援指示繼續。"
            else:
                next_q = "AED 有找到了嗎？請保持按壓速度每秒兩下，深度約 5 公分，直到 AED 或救援人員到位。"
            return reply, next_q
        # User acknowledged CPR instructions ("好") — continue guidance
        _CPR_INSTRUCTION_TERMS = ["胸口中央", "往下壓", "按壓", "胸外按壓"]
        _simple_yes = latest_user_text.strip() in ["好", "好的", "好啊", "好喔", "嗯", "恩", "OK", "ok"]
        if (is_yes(latest_user_text) or _simple_yes) and any(
            term in previous_assistant_text for term in _CPR_INSTRUCTION_TERMS
        ):
            if is_remote_rescue_extracted(ex.symptom_summary):
                reply = "好，繼續照 119 指示做，保持節奏。"
                next_q = "請保留手機電力並開擴音，持續回報傷者呼吸、意識和你們的位置。"
            else:
                reply = "好，繼續做，保持節奏。旁邊有人去找 AED 了嗎？"
                next_q = "AED 找到了嗎？按壓速度每秒兩下，深度約 5 公分，繼續直到 AED 或救援人員到位。"
            return reply, next_q
        if has_no_normal_breathing(latest_user_text):
            ex.people_injured = True
            ex.breathing_difficulty = True
            return cpr_guidance_for_unresponsive(ex)
        if has_called_119(latest_user_text):
            reply = "收到，很好！119 已通報，救援流程已啟動，請保持通話或手機可接通。"
            if is_remote_rescue_extracted(ex.symptom_summary):
                next_q = "請回報 GPS 座標、步道地標、同行人數、手機電量，以及傷者目前意識和呼吸狀況。"
            else:
                next_q = "請回報傷者目前意識和正常呼吸狀況；如果沒有正常呼吸，請依救援指示開始 CPR，並請旁邊的人找 AED。"
            return reply, next_q

    first_aid_result = first_aid_guidance_for_text(latest_user_text, ex)
    if first_aid_result:
        return first_aid_result

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
                reply = "收到，現場可能有武器，這會讓情況變得很危險。請先不要靠近，保護自己最重要。"
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
                reply = "收到，危險目前還在持續。你先保護自己是對的，請盡量移動到安全的位置。"
            if next_question_is_generic or asks_about_danger(next_q):
                next_q = "如果方便，請再補充現場有幾個人、目前最危急的是什麼，我會幫你整理成通報重點。"
        elif is_no(latest_user_text):
            ex.danger_active = False
            if reply_is_generic:
                if latest_user_text.strip() in ["沒有了", "沒了", "不在了", "走了", "離開了"]:
                    reply = "了解，情況看起來已經緩和，對方應該已離開，不在附近了。"
                else:
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


def looks_like_generic_open_question(text: str) -> bool:
    """判斷 reply 是否是空泛的開放式問句，無法對使用者提供具體引導。"""
    generic_patterns = [
        "目前的情況是什麼樣的",
        "有沒有其他人需要幫助",
        "可以告訴我更多",
        "請告訴我目前",
        "目前狀況如何",
        "有什麼需要補充",
        "還有什麼要說",
    ]
    normalized = (text or "").strip()
    return any(p in normalized for p in generic_patterns)


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


_SLOT_TOPICS = frozenset({"weapon", "injury", "conscious", "breathing"})


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
    # Slot-specific topics: single overlap is enough (e.g., both asking about weapon)
    if overlap & _SLOT_TOPICS:
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
    messages: Optional[List[ChatMessage]] = None,
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

        _reply_is_action_guide = any(
            t in reply for t in ["AED", "CPR", "胸外按壓", "電擊", "按壓", "電極片", "照機器語音", "急救"]
        )
        if ex.category == "醫療急症" and reply and asks_about_danger(reply) and not _reply_is_action_guide:
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

        # 暴力事件全部 slot 填完，但 reply 還是空泛開放式問句，替換成具體引導
        if (
            ex.category == "暴力事件"
            and ex.weapon is not None
            and ex.danger_active is not None
            and ex.people_injured is not None
            and looks_like_generic_open_question(reply)
        ):
            if ex.danger_active is False:
                reply = "收到，情況已緩和。對方離開了嗎？你們現在在安全的位置嗎？"
            elif ex.weapon is True:
                reply = "收到，請先離開現場，移到安全的地方，不要跟對方正面接觸。"
            else:
                reply = "收到，請先確認你們都在安全的位置。"
            changed = True

        if replacement and replacement != next_q:
            next_q = replacement
            changed = True

        if not changed:
            break

    next_q = remove_duplicate_next_question(reply, next_q)

    # 全局去重：移除在最近幾輪 assistant 訊息中已說過的固定句型
    if messages:
        assistant_history = [m.content for m in messages if m.role == "assistant"]
        reply = _remove_repeated_phrases(reply, assistant_history)
        next_q = _remove_repeated_phrases(next_q, assistant_history)

    return reply, next_q


# ======================
# 語氣調整
# ======================

def apply_semantic_tone(
    reply: str,
    semantic: SemanticUnderstanding,
    risk_level: str,
    audio_context: Optional[Dict[str, Any]] = None,
    previous_assistant_text: str = "",
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

    _is_action_mode = any(
        t in reply for t in ["AED", "CPR", "胸外按壓", "電擊", "按壓", "貼上電極片", "照機器語音"]
    )
    if has_high_urgency_audio_emotion(audio_context) and risk_level in ["Medium", "High"]:
        if _is_action_mode:
            suffix = ""
        elif not location_known and "安全" not in reply and "位置" not in reply and "在哪" not in reply:
            suffix = " 你先確認自己是否在安全位置，如果方便，請立刻告訴我目前位置。"
        else:
            suffix = ""
    elif risk_level == "High" and "安全" not in reply:
        if _is_action_mode:
            suffix = ""
        elif semantic.primary_need and "通報" in semantic.primary_need:
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

    # 若 suffix 的核心內容在前一輪已說過，就不重複
    if suffix and previous_assistant_text:
        suffix_core = suffix.strip(" 。，")
        if any(phrase in previous_assistant_text for phrase in _REPEATED_PHRASE_PATTERNS if phrase in suffix_core):
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
