"""欄位抽取、醫療回應腳本、對話狀態重建、摘要生成。"""

from typing import Any, Dict, List, Optional

from backend.models import ChatMessage, Extracted
from backend.services.risk import (
    ACUTE_MEDICAL_HIGH_KEYWORDS,
    AGGRESSIVE_DISTURBANCE_KEYWORDS,
    DISTURBANCE_KEYWORDS,
    INCIDENT_DESCRIPTION_KEYWORDS,
    MINOR_INJURY_KEYWORDS,
    SUSPICIOUS_ACTIVITY_KEYWORDS,
    VIOLENCE_SIGNAL_KEYWORDS,
    has_active_violence_emergency,
    has_acute_medical_signal,
    has_aggressive_disturbance_signal,
    has_critical_injury_signal,
    has_disturbance_signal,
    has_medical_urgency_signal,
    has_minor_injury_signal,
)
from .classify import (
    asks_about_location,
    get_dispatch_advice,
    normalize_category_name,
)
from .location import (
    extract_location_from_text,
    is_likely_location_response,
    location_quality_score,
    normalize_location_candidate,
)


# ======================
# 抽取輔助
# ======================

def is_likely_incident_detail(text: str, ex: Optional[Extracted] = None) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if ex and ex.category and ex.category != "待確認":
        return True
    return has_disturbance_signal(normalized) or any(
        token in normalized for token in INCIDENT_DESCRIPTION_KEYWORDS
    )


def infer_reporter_role(text: str) -> Optional[str]:
    normalized = text.strip()
    if not normalized:
        return None

    self_markers = ["我發燒", "我不舒服", "我胸痛", "我喘不過氣", "我呼吸困難", "我昏倒", "我受傷"]
    other_markers = [
        "他", "她", "對方", "有人", "我朋友", "我同學", "我家人",
        "我爸", "我媽", "我先生", "我太太", "我兒子", "我女兒",
    ]

    if any(marker in normalized for marker in self_markers):
        return "本人"
    if any(marker in normalized for marker in other_markers):
        return "代他人通報"
    return None


def subject_reference(ex: Extracted) -> str:
    return "你" if ex.reporter_role == "本人" else "對方"


def subject_possessive_reference(ex: Extracted) -> str:
    return "你的" if ex.reporter_role == "本人" else "對方的"


def collect_symptoms(text: str) -> List[str]:
    symptom_pairs = [
        ("發燒", "發燒"), ("高燒", "高燒"), ("呼吸困難", "呼吸困難"),
        ("喘不過氣", "喘不過氣"), ("胸痛", "胸痛"), ("抽搐", "抽搐"),
        ("昏倒", "昏倒"), ("失去意識", "失去意識"), ("意識不清", "意識不清"),
        ("頭暈", "頭暈"), ("嘔吐", "嘔吐"), ("流血", "流血"), ("受傷", "受傷"),
        ("小擦傷", "擦傷"), ("擦傷", "擦傷"), ("小傷口", "小傷口"),
        ("輕傷", "輕傷"), ("咳", "咳嗽"),
    ]
    symptoms: List[str] = []
    for keyword, label in symptom_pairs:
        if keyword in text and label not in symptoms:
            symptoms.append(label)
    return symptoms


def merge_symptom_summary(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
    tokens: List[str] = []
    for summary in [existing, incoming]:
        if not summary:
            continue
        for token in [part.strip() for part in summary.split("、")]:
            if token and token not in tokens:
                tokens.append(token)
    return "、".join(tokens) if tokens else (incoming or existing)


# ======================
# 醫療回應腳本
# ======================

def build_medical_acknowledgement(ex: Extracted, text: str) -> str:
    ref = subject_reference(ex)
    if ex.conscious is True and ex.breathing_difficulty is True:
        return f"收到，{ref}目前意識清楚，但有呼吸困難等急性症狀，需要優先留意。"
    if ex.conscious is False:
        return f"收到，{ref}目前意識不清，這屬於需要立即處理的醫療急症。"
    if ex.conscious is True and has_minor_injury_signal(text):
        return f"了解，{ref}目前意識清醒，看起來像輕微擦傷，我先幫你確認是否需要進一步處理。"
    if has_acute_medical_signal(text) or ex.breathing_difficulty is True:
        if ex.breathing_difficulty is True:
            return f"收到，{ref}有呼吸困難等急性症狀，這屬於需要優先處理的醫療急症。"
        return f"收到，{ref}有明顯急性症狀，這屬於需要優先處理的醫療急症。"
    return f"收到，我先幫你確認{subject_possessive_reference(ex)}醫療狀況。"


def medical_follow_up_question(ex: Extracted, risk_level: str) -> str:
    ref = subject_reference(ex)
    symptom_summary = ex.symptom_summary or ""

    if ex.conscious is True and any(token in symptom_summary for token in ["擦傷", "小傷口", "輕傷"]):
        return f"{ref}傷口現在有持續流血、需要止血包紮，或還有頭暈、想吐、明顯疼痛加重嗎？"
    if ex.breathing_difficulty is True or ex.conscious is False or risk_level == "High":
        return f"{ref}現在能正常說完整句子嗎？症狀有在加重，或需要立刻送醫嗎？如果越來越喘，請立刻撥 119。"
    return f"除了目前提到的症狀外，{ref}還有發燒、胸痛、嘔吐，或其他不舒服正在加重嗎？"


# ======================
# 詳細資訊擴充
# ======================

def enrich_extracted_details(ex: Extracted, text: str) -> Extracted:
    role = infer_reporter_role(text)
    if role:
        ex.reporter_role = role

    if any(keyword in text for keyword in ["意識清楚", "意識清醒", "人是清醒的", "目前清醒", "叫得醒"]):
        ex.conscious = True
    elif any(keyword in text for keyword in ["意識不清", "昏迷", "失去意識", "叫不醒"]):
        ex.conscious = False

    if any(keyword in text for keyword in ["呼吸困難", "喘不過氣", "沒辦法呼吸", "呼吸很喘"]):
        ex.breathing_difficulty = True
    elif any(keyword in text for keyword in ["呼吸正常", "沒有呼吸困難", "沒有喘", "呼吸沒問題", "看起來呼吸正常"]):
        ex.breathing_difficulty = False

    if any(keyword in text for keyword in ["發燒", "高燒"]):
        ex.fever = True
    elif "沒有發燒" in text:
        ex.fever = False

    symptoms = collect_symptoms(text)
    if symptoms:
        ex.symptom_summary = merge_symptom_summary(ex.symptom_summary, "、".join(symptoms))

    if has_minor_injury_signal(text):
        ex.people_injured = True
        ex.symptom_summary = merge_symptom_summary(ex.symptom_summary, "擦傷")

    if ex.category == "醫療急症":
        if ex.breathing_difficulty is True or ex.conscious is False:
            ex.people_injured = True
        elif ex.people_injured is None and (ex.fever is True or bool(symptoms)):
            ex.people_injured = True

    return ex


# ======================
# 核心抽取
# ======================

def simple_extract(text: str) -> Extracted:
    ex = Extracted(description=text)
    has_disturbance = has_disturbance_signal(text)
    has_aggressive_disturbance = has_aggressive_disturbance_signal(text)
    has_suspicious_activity = any(keyword in text for keyword in SUSPICIOUS_ACTIVITY_KEYWORDS)
    has_violence_signal = any(keyword in text for keyword in VIOLENCE_SIGNAL_KEYWORDS)

    if any(k in text for k in ["火災", "失火", "著火", "起火", "冒煙", "燒起來"]):
        ex.category = "火災"
    elif has_violence_signal or (
        has_aggressive_disturbance
        and any(keyword in text for keyword in ["威脅", "逼近", "靠近", "要打", "要砍", "攻擊"])
    ):
        ex.category = "暴力事件"
    elif has_suspicious_activity:
        ex.category = "可疑人士"
    elif has_disturbance:
        ex.category = "噪音"
    elif any(k in text for k in ["昏倒", "流血", "受傷", "沒呼吸", "抽搐", "心臟痛", "頭暈", "胸痛", "呼吸困難", "喘不過氣", "不舒服", "發燒", "嘔吐"]):
        ex.category = "醫療急症"
    elif any(k in text for k in ["車禍", "撞車", "翻車", "追撞"]):
        ex.category = "交通事故"
    else:
        ex.category = "待確認"

    if any(k in text for k in ["流血", "受傷", "昏倒", "沒呼吸", "抽搐", "骨折", "頭暈", "胸痛", "呼吸困難", "喘不過氣", "嘔吐"]):
        ex.people_injured = True
    else:
        ex.people_injured = None

    ex.weapon = True if any(k in text for k in ["刀", "槍", "武器", "棍棒"]) else None
    ex.danger_active = True if any(k in text for k in ["還在", "持續", "正在", "還沒結束", "還在現場"]) else None
    ex.location = extract_location_from_text(text)
    ex = enrich_extracted_details(ex, text)
    ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
    return ex


def merge_extracted(base: Extracted, incoming: Extracted) -> Extracted:
    base.category = normalize_category_name(base.category)
    incoming.category = normalize_category_name(incoming.category)

    if incoming.category and incoming.category != "待確認":
        base.category = incoming.category
    elif not base.category:
        base.category = incoming.category

    if incoming.location and location_quality_score(incoming.location) >= location_quality_score(base.location):
        base.location = incoming.location
    if incoming.people_injured is not None:
        base.people_injured = incoming.people_injured
    if incoming.weapon is not None:
        base.weapon = incoming.weapon
    if incoming.danger_active is not None:
        base.danger_active = incoming.danger_active
    if incoming.reporter_role:
        base.reporter_role = incoming.reporter_role
    if incoming.conscious is not None:
        base.conscious = incoming.conscious
    if incoming.breathing_difficulty is not None:
        base.breathing_difficulty = incoming.breathing_difficulty
    if incoming.fever is not None:
        base.fever = incoming.fever
    if incoming.symptom_summary:
        base.symptom_summary = merge_symptom_summary(base.symptom_summary, incoming.symptom_summary)
    if incoming.description:
        base.description = incoming.description

    base.dispatch_advice = get_dispatch_advice(base.category, base.weapon, base.people_injured)
    return base


def apply_turn_context(messages: List[ChatMessage], ex: Extracted) -> Extracted:
    last_user_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last_user_index = index
            break

    if last_user_index is None:
        return ex

    latest_user_text_val = messages[last_user_index].content.strip()
    previous_assistant_text = ""

    for index in range(last_user_index - 1, -1, -1):
        if messages[index].role == "assistant":
            previous_assistant_text = messages[index].content.strip()
            break

    normalized_location = normalize_location_candidate(latest_user_text_val)
    extracted_location = extract_location_from_text(latest_user_text_val)
    asked_for_location = asks_about_location(previous_assistant_text)

    if (
        not ex.location
        and latest_user_text_val
        and asked_for_location
        and is_likely_location_response(latest_user_text_val)
        and normalized_location
    ):
        ex.location = normalized_location

    current_location = normalize_location_candidate(ex.location or "")
    if extracted_location:
        current_has_incident_noise = bool(current_location) and any(
            token in current_location for token in INCIDENT_DESCRIPTION_KEYWORDS
        )
        if (
            not current_location
            or current_has_incident_noise
            or location_quality_score(extracted_location) > location_quality_score(current_location)
        ):
            ex.location = extracted_location

    ex = enrich_extracted_details(ex, latest_user_text_val)

    latest_turn_extracted = simple_extract(latest_user_text_val) if latest_user_text_val else Extracted()
    if ex.category == "待確認" and latest_turn_extracted.category not in [None, "待確認"]:
        ex.category = latest_turn_extracted.category
    if ex.weapon is None and latest_turn_extracted.weapon is not None:
        ex.weapon = latest_turn_extracted.weapon
    if ex.people_injured is None and latest_turn_extracted.people_injured is not None:
        ex.people_injured = latest_turn_extracted.people_injured
    if ex.danger_active is None and latest_turn_extracted.danger_active is not None:
        ex.danger_active = latest_turn_extracted.danger_active

    if ex.category == "待確認" and latest_user_text_val:
        category_map = {
            "火災": "火災", "失火": "火災", "可疑人士": "可疑人士", "可疑": "可疑人士",
            "噪音": "噪音", "醫療": "醫療急症", "急症": "醫療急症",
            "暴力": "暴力事件", "打架": "暴力事件", "車禍": "交通事故", "交通事故": "交通事故",
        }
        mapped = category_map.get(latest_user_text_val)
        if mapped:
            ex.category = mapped

    if not ex.dispatch_advice:
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)

    return ex


def extract_conversation_state(messages: List[ChatMessage]) -> Extracted:
    merged = Extracted(
        category="待確認",
        location=None,
        people_injured=None,
        weapon=None,
        danger_active=None,
        reporter_role=None,
        conscious=None,
        breathing_difficulty=None,
        fever=None,
        symptom_summary=None,
        dispatch_advice="建議派遣：待確認",
        description=None,
    )

    for index, message in enumerate(messages):
        if message.role != "user":
            continue
        turn_extracted = simple_extract(message.content)
        turn_extracted = apply_turn_context(messages[: index + 1], turn_extracted)
        merged = merge_extracted(merged, turn_extracted)

    return merged


# ======================
# 摘要生成
# ======================

def generate_incident_summary(ex: Extracted, risk_level: str) -> str:
    summary = []
    summary.append(f"案件類型：{ex.category or '待確認'}")
    summary.append(f"地點：{ex.location or '未提供'}")
    if ex.reporter_role:
        summary.append(f"通報角色：{ex.reporter_role}")
    if ex.people_injured:
        summary.append("傷勢：現場有人受傷或需要醫療協助")
    if ex.conscious is True:
        summary.append("意識：目前清楚")
    elif ex.conscious is False:
        summary.append("意識：不清或無反應")
    if ex.breathing_difficulty is True:
        summary.append("呼吸：有呼吸困難")
    if ex.fever is True:
        summary.append("症狀：有發燒")
    if ex.symptom_summary:
        summary.append(f"症狀摘要：{ex.symptom_summary}")
    if ex.weapon:
        summary.append("注意：現場可能有武器")
    if ex.danger_active:
        summary.append("危險狀況：事件仍在持續")
    summary.append(f"風險等級：{risk_level}")
    summary.append(ex.dispatch_advice or "建議派遣：待確認")
    return " | ".join(summary)
