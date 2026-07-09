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
    has_child_distress_signal,
    has_child_unresponsive_signal,
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
from backend.services.incident_taxonomy import has_remote_rescue_signal, match_incident_taxonomy
from backend.services.incident_taxonomy import is_remote_rescue_extracted
from backend.services.v4_event_semantics import (
    apply_v4_slot_hints,
    best_category_from_text,
    contains_negated,
    contains_uncertain,
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

    self_victim_markers = [
        "打我", "追我", "堵我", "威脅我", "闖進我", "我被打", "我被搶",
        "我被追", "我被威脅", "我被困", "我躲", "我逃", "我出不去",
        "在打我", "對我動手", "把我推", "我受傷", "我流血",
    ]
    self_medical_markers = [
        "我發燒", "我不舒服", "我胸痛", "我喘不過氣", "我呼吸困難",
        "我昏倒", "我暈倒", "我暈過去", "我倒下", "我頭暈", "我嘔吐",
    ]
    witness_markers = ["我看到", "我聽到", "目擊", "隔壁", "樓上", "樓下", "鄰居", "旁邊"]
    caregiver_markers = [
        "我爸", "我媽", "爸爸", "媽媽", "爺爺", "奶奶", "阿公", "阿嬤",
        "我先生", "我太太", "我老婆", "我老公", "我兒子", "我女兒",
        "我小孩", "我的孩子", "家人",
    ]
    third_party_markers = ["他", "她", "對方", "有人", "朋友", "同學", "同事", "我朋友", "我同學"]

    if any(marker in normalized for marker in self_victim_markers):
        return "本人受害"
    if any(marker in normalized for marker in self_medical_markers):
        return "本人"
    if any(marker in normalized for marker in witness_markers):
        return "旁觀者"
    if any(marker in normalized for marker in caregiver_markers):
        return "照顧者/家屬"
    if any(marker in normalized for marker in third_party_markers):
        return "代他人通報"
    return None


def subject_reference(ex: Extracted) -> str:
    return "你" if ex.reporter_role in ["本人", "本人受害"] else "對方"


def subject_possessive_reference(ex: Extracted) -> str:
    return "你的" if ex.reporter_role in ["本人", "本人受害"] else "對方的"


def collect_symptoms(text: str) -> List[str]:
    symptom_pairs = [
        ("發燒", "發燒"), ("高燒", "高燒"), ("呼吸困難", "呼吸困難"),
        ("喘不過氣", "喘不過氣"), ("吸不到氣", "吸不到氣"), ("很喘", "很喘"),
        ("胸痛", "胸痛"), ("胸悶", "胸悶"), ("心臟痛", "心臟痛"), ("抽搐", "抽搐"),
        ("昏倒", "昏倒"), ("暈倒", "暈倒"), ("暈過去", "暈過去"), ("倒下", "倒下"),
        ("失去意識", "失去意識"), ("意識不清", "意識不清"),
        ("半邊無力", "半邊無力"), ("嘴歪", "嘴歪"), ("講話不清楚", "講話不清楚"),
        ("頭暈", "頭暈"), ("嘔吐", "嘔吐"), ("流血", "流血"), ("受傷", "受傷"),
        ("燙傷", "燙傷"), ("燒傷", "燒傷"), ("灼傷", "灼傷"), ("燙到", "燙傷"),
        ("燒到", "燒傷"), ("水泡", "水泡"),
        ("噎到", "異物哽塞"), ("哽塞", "異物哽塞"), ("噎住", "異物哽塞"),
        ("中暑", "中暑"), ("熱衰竭", "熱衰竭"), ("癲癇", "癲癇"),
        ("失溫", "失溫"), ("高山症", "高山症"), ("脫水", "脫水"),
        ("蛇咬", "蛇咬"), ("蜂螫", "蜂螫"),
        ("小擦傷", "擦傷"), ("擦傷", "擦傷"), ("小傷口", "小傷口"),
        ("輕傷", "輕傷"), ("咳", "咳嗽"),
    ]
    symptoms: List[str] = []
    for keyword, label in symptom_pairs:
        if label == "水泡" and any(term in text for term in ["沒有起水泡", "沒起水泡", "沒有水泡", "沒水泡"]):
            continue
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


def has_burn_symptom(ex: Extracted) -> bool:
    symptom_summary = ex.symptom_summary or ""
    return any(token in symptom_summary for token in ["燙傷", "燒傷", "灼傷", "水泡"])


def is_mild_burn_text(text: str) -> bool:
    return any(token in text for token in ["紅紅", "沒有起水泡", "沒起水泡", "沒有水泡", "沒水泡", "輕微燙傷", "輕微燒傷"])


def burn_dispatch_advice(text: str, ex: Extracted) -> Optional[str]:
    if ex.category != "醫療急症" or not has_burn_symptom(ex):
        return None
    if is_mild_burn_text(text):
        return "建議處置：先冷水沖洗並觀察；若範圍大、起水泡或疼痛加劇再就醫/119"
    return "建議處置：冷水沖洗並評估嚴重度；嚴重燒燙傷請立刻就醫或撥 119"


# ======================
# 醫療回應腳本
# ======================

def build_medical_acknowledgement(ex: Extracted, text: str) -> str:
    ref = subject_reference(ex)
    symptom_summary = ex.symptom_summary or ""
    if any(token in symptom_summary for token in ["燙傷", "燒傷", "灼傷", "水泡"]):
        if any(token in text for token in ["沒有起水泡", "沒起水泡", "沒有水泡", "沒水泡", "紅紅"]):
            return f"收到，{ref}目前像是較輕微的燒燙傷，我先幫你確認是否需要進一步處理。"
        return f"收到，{ref}有燒燙傷狀況，我先幫你確認範圍和嚴重程度。"
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

    if any(token in symptom_summary for token in ["燙傷", "燒傷", "灼傷", "水泡"]):
        if risk_level == "High":
            return f"請先讓{ref}離開熱源並撥打 119；如果安全，先用流動清水沖洗燙傷處，不要刺破水泡或撕黏住的衣物。"
        return f"請先用流動清水沖洗燙傷處至少 10 分鐘。燙傷面積大嗎？有水泡、皮膚焦黑或發白，或在臉、手掌、關節附近嗎？"
    if is_remote_rescue_extracted(symptom_summary):
        if risk_level == "High":
            return "請立刻撥打 119，告知 GPS 座標或步道地標；保留手機電力，不要冒險移動或搬動疑似骨折/墜落傷者。"
        return "請準備 GPS 座標、步道地標、同行人數、傷勢、手機電量與訊號，提供給 119 或救援人員。"
    if ex.conscious is True and any(token in symptom_summary for token in ["擦傷", "小傷口", "輕傷"]):
        return f"{ref}傷口現在有持續流血、需要止血包紮，或還有頭暈、想吐、明顯疼痛加重嗎？"
    if ex.conscious is False:
        if ex.aed_confirmed:
            return "請依照 AED 語音指示繼續操作，不要中斷；電擊後立刻繼續按壓，直到救護人員接手。"
        if ex.reporter_role == "照顧者/家屬":
            return "你的家人目前沒有反應，系統已列為高風險通報。請保持手機可接通，現在確認胸口是否有起伏、是否有正常呼吸；如果沒有正常呼吸，請開擴音聽救援指示，並請旁邊的人找 AED。"
        return f"{ref}目前沒有反應，系統已列為高風險通報。請先確認你自己安全；如果你就在傷者旁邊，請確認胸口是否有起伏或有沒有正常呼吸。周圍有車流、火煙、暴力或其他明顯危險時，不要靠近。"
    if ex.breathing_difficulty is True:
        return f"{ref}現在能正常說完整句子嗎？症狀有在加重嗎？如果越來越喘，系統會列為高風險通報，請保持手機可接通。"
    if risk_level == "High":
        return f"{ref}現在最危急的症狀是什麼？如果有胸痛、喘不過氣、昏倒或意識不清，系統會優先整理成高風險通報。"
    return f"除了目前提到的症狀外，{ref}還有發燒、胸痛、嘔吐，或其他不舒服正在加重嗎？"


# ======================
# 詳細資訊擴充
# ======================

def enrich_extracted_details(ex: Extracted, text: str) -> Extracted:
    role = infer_reporter_role(text)
    if role:
        ex.reporter_role = role

    if any(keyword in text for keyword in ["意識清楚", "意識清醒", "人是清醒的", "目前清醒", "叫得醒", "有在動"]):
        ex.conscious = True
    elif any(keyword in text for keyword in ["意識不清", "昏迷", "失去意識", "叫不醒", "沒反應", "沒有反應", "無反應", "暈過去", "昏過去", "沒有在呼吸", "沒在呼吸", "好像沒有在呼吸"]):
        ex.conscious = False

    if any(keyword in text for keyword in ["呼吸困難", "喘不過氣", "吸不到氣", "沒辦法呼吸", "呼吸很喘", "很喘", "沒呼吸", "沒有呼吸", "快沒氣", "沒有在呼吸", "沒在呼吸", "好像沒有在呼吸"]):
        ex.breathing_difficulty = True
    elif any(keyword in text for keyword in ["呼吸正常", "沒有呼吸困難", "沒有喘", "呼吸沒問題", "看起來呼吸正常"]):
        ex.breathing_difficulty = False

    # AED/CPR usage implies an unresponsive patient
    if any(k in text for k in ["CPR", "胸外按壓", "AED"]) and ex.conscious is None:
        ex.conscious = False

    # Safety confirmed → danger no longer active
    if any(k in text for k in ["在安全的地方", "已經安全", "到安全的", "現在安全", "已到安全"]):
        ex.danger_active = False

    if any(keyword in text for keyword in ["發燒", "高燒"]):
        ex.fever = True
    elif "沒有發燒" in text:
        ex.fever = False

    symptoms = collect_symptoms(text)
    if symptoms:
        ex.symptom_summary = merge_symptom_summary(ex.symptom_summary, "、".join(symptoms))

    if has_remote_rescue_signal(text):
        ex.symptom_summary = merge_symptom_summary(ex.symptom_summary, "疑似山域水域救援")
        if ex.category in [None, "待確認"]:
            ex.category = "山域水域救援"

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
    taxonomy_match = match_incident_taxonomy(text)
    has_disturbance = has_disturbance_signal(text)
    has_aggressive_disturbance = has_aggressive_disturbance_signal(text)
    has_suspicious_activity = any(keyword in text for keyword in SUSPICIOUS_ACTIVITY_KEYWORDS)
    has_violence_signal = any(
        keyword in text and not contains_negated(text, [keyword]) and not contains_uncertain(text, [keyword])
        for keyword in VIOLENCE_SIGNAL_KEYWORDS
    )
    has_explicit_violence_signal = any(
        keyword in text and not contains_negated(text, [keyword]) and not contains_uncertain(text, [keyword])
        for keyword in ["打架", "被打", "威脅", "砍", "家暴", "攻擊", "毆打", "要打", "要砍", "傷害"]
    )
    has_weapon_threat_context = (
        any(keyword in text for keyword in ["拿刀", "持刀", "有刀", "拿槍", "持槍", "有槍", "有武器"])
        and not any(keyword in text for keyword in ["割傷", "切到", "刀傷", "削到"])
    )
    has_child_protection_signal = (
        any(k in text for k in ["家暴", "虐待", "受虐", "打小孩", "打罵", "摔東西", "砸東西"])
        or has_child_distress_signal(text)
    )

    v4_category = best_category_from_text(text)
    if has_child_protection_signal or has_explicit_violence_signal or has_weapon_threat_context or (
        has_aggressive_disturbance
        and any(keyword in text for keyword in ["威脅", "逼近", "靠近", "要打", "要砍", "攻擊"])
    ):
        ex.category = "暴力事件"
    elif v4_category in ["交通事故", "可疑人士", "火災", "暴力事件"]:
        ex.category = v4_category
    elif taxonomy_match and taxonomy_match.get("app_category"):
        ex.category = taxonomy_match["app_category"]
        subtype = taxonomy_match.get("subtype")
        if subtype:
            ex.symptom_summary = f"疑似{subtype}"
    elif v4_category:
        ex.category = v4_category
    elif any(k in text for k in ["火災", "失火", "著火", "起火", "冒煙", "濃煙", "煙很大", "燒起來"]):
        ex.category = "火災"
    elif has_suspicious_activity:
        ex.category = "可疑人士"
    elif has_disturbance:
        ex.category = "噪音"
    elif any(k in text for k in ["車禍", "撞車", "翻車", "追撞", "被車撞", "撞到人", "機車倒", "汽車撞"]):
        ex.category = "交通事故"
    elif any(
        k in text and not contains_negated(text, [k])
        for k in [
            "昏倒", "暈倒", "暈過去", "昏過去", "倒地", "倒下", "倒在地上",
            "倒在路邊", "流血", "大量流血", "血流不停", "受傷", "燙傷",
            "燒傷", "灼傷", "燙到", "燒到", "水泡", "沒反應", "沒有反應",
            "無反應", "叫不醒", "沒呼吸", "抽搐", "心臟痛", "胸悶",
            "半邊無力", "嘴歪", "講話不清楚", "頭暈", "胸痛", "呼吸困難",
            "喘不過氣", "吸不到氣", "不舒服", "發燒", "嘔吐",
            "AED", "CPR", "胸外按壓", "救護車", "登山迷路", "爬山迷路",
            "山難", "山上迷路", "步道迷路", "國家公園迷路", "偏鄉受困",
            "林道受困", "山區受困", "受困", "失聯", "墜落", "摔落",
            "滑落", "墜谷", "溪水暴漲", "溪水變大", "溪水變急", "水位上升",
            "被水沖走", "被沖走", "沖走", "卡在對岸", "過不了溪", "過不了河",
            "漂走", "水變深", "渡溪失敗", "溯溪", "溪谷", "失溫",
            "高山症", "中暑", "熱衰竭", "脫水", "蛇咬", "蜂螫",
        ]
    ):
        ex.category = "醫療急症"
    elif any(k in text for k in ["沒有在呼吸", "沒在呼吸"]):
        ex.category = "醫療急症"
    else:
        ex.category = "待確認"

    injury_terms = ["流血", "大量流血", "血流不停", "受傷", "燙傷", "燒傷", "灼傷", "燙到", "燒到", "水泡", "昏倒", "暈倒", "暈過去", "昏過去", "倒地", "倒下", "倒在地上", "倒在路邊", "沒反應", "沒有反應", "無反應", "叫不醒", "沒呼吸", "抽搐", "骨折", "頭暈", "胸痛", "胸悶", "心臟痛", "半邊無力", "嘴歪", "講話不清楚", "呼吸困難", "喘不過氣", "吸不到氣", "嘔吐", "噎到", "哽塞", "噎住", "臉發紫", "中暑", "熱衰竭", "癲癇", "失溫", "高山症", "脫水", "蛇咬", "蜂螫", "墜落", "摔落", "滑落", "墜谷", "被水沖走", "被沖走", "沖走", "不能走", "無法走", "無法行走", "走不動", "AED", "CPR", "胸外按壓", "救護車", "沒有在呼吸", "沒在呼吸"]
    if contains_negated(text, ["受傷", "流血", "昏倒", "呼吸困難", "嘔吐"]):
        ex.people_injured = False
    elif any(k in text for k in injury_terms):
        ex.people_injured = True
    else:
        ex.people_injured = None

    weapon_terms = ["刀", "槍", "武器", "棍棒", "球棒", "鐵棍"]
    if contains_negated(text, weapon_terms):
        ex.weapon = False
    elif contains_uncertain(text, weapon_terms):
        ex.weapon = None
    else:
        ex.weapon = True if any(k in text for k in weapon_terms) else None
    ex.danger_active = True if has_child_protection_signal or any(k in text for k in ["還在", "持續", "正在", "還沒結束", "還在現場", "追人", "追我", "揮刀", "攻擊", "毆打", "攻擊中", "迷路", "迷途", "受困", "失聯", "溪水暴漲", "溪水變大", "溪水變急", "水位上升", "被水沖走", "被沖走", "沖走", "卡在對岸", "過不了溪", "過不了河", "漂走", "水變深", "渡溪失敗", "坍方", "落石", "土石流", "手機快沒電", "手機沒電", "快沒電", "電量不足", "剩一格電", "只剩一格電", "剩5%", "剩 5%", "剩不到10%", "剩不到 10%", "沒訊號", "沒有訊號", "訊號不好", "定位跑掉", "GPS不準", "GPS 不準", "找不到座標", "不知道座標", "沒有座標", "下大雨", "大雨", "起霧", "濃霧", "氣溫很低", "低溫", "很冷", "天黑", "天色變暗", "不能走", "無法走", "無法行走", "走不動"]) else None
    if has_child_unresponsive_signal(text):
        ex.conscious = False
        ex.people_injured = True
        ex.danger_active = True
    ex.location = extract_location_from_text(text)
    ex = enrich_extracted_details(ex, text)
    ex = apply_v4_slot_hints(text, ex)
    burn_advice = burn_dispatch_advice(text, ex)
    if burn_advice:
        ex.dispatch_advice = burn_advice
    elif taxonomy_match and taxonomy_match.get("advice") and ex.category == taxonomy_match.get("app_category"):
        ex.dispatch_advice = taxonomy_match["advice"]
    else:
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
    return ex


def merge_extracted(base: Extracted, incoming: Extracted) -> Extracted:
    base.category = normalize_category_name(base.category)
    incoming.category = normalize_category_name(incoming.category)

    if incoming.category and incoming.category != "待確認":
        if not base.category or base.category == "待確認":
            base.category = incoming.category
        # Don't overwrite an established category with a different one:
        # e.g., "救命" in a fire context should not flip 火災 → 暴力事件.
        # Same-category reinforcement is still fine.
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
    if incoming.aed_confirmed:
        base.aed_confirmed = True
    if incoming.symptom_summary:
        base.symptom_summary = merge_symptom_summary(base.symptom_summary, incoming.symptom_summary)
    if incoming.description:
        base.description = incoming.description

    if incoming.dispatch_advice:
        base.dispatch_advice = incoming.dispatch_advice
    else:
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
    ex = apply_v4_slot_hints(latest_user_text_val, ex)

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
        # Detect AED-found phrasing across all user turns so the state is preserved
        if not merged.aed_confirmed:
            compact = message.content.replace(" ", "")
            aed_found_terms = ["找到AED", "拿到AED", "AED到了", "有AED", "AED在旁邊"]
            if any(t in compact for t in aed_found_terms):
                turn_extracted.aed_confirmed = True
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
