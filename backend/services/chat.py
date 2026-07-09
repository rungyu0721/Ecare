"""
聊天服務：Prompt 組裝、LLM chat 呼叫、完整對話處理管線。
"""

import json
import re
import string
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import (
    CHAT_CONTEXT_TURNS,
    COMPACT_LOCAL_LLM_MAX_TOKENS,
    FOLLOWUP_CONTEXT_TURNS,
    LLM_MODEL_NAME,
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
    call_llm,
    llm_is_ready,
    parse_llm_json_text,
)
from backend.services.incident_taxonomy import (
    has_remote_rescue_signal,
    is_remote_rescue_extracted,
    taxonomy_prompt_summary,
)
from backend.services.incident_response_guides import match_incident_response_guides
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


def _uses_natural_chat_model() -> bool:
    model_name = (LLM_MODEL_NAME or "").lower()
    return (
        model_name.startswith("ecare-local")
        or model_name.startswith("ecare-4080")
        or model_name.startswith("ecare-v4")
    )


def _build_natural_chat_prompt(
    *,
    recent: List[ChatMessage],
    known_context: str,
    dialogue_state_text: str,
    audio_context_text: str,
) -> str:
    conversation = "\n".join(
        f"{'使用者' if message.role == 'user' else '助理'}：{message.content}"
        for message in recent
    )
    return f"""你是 E-CARE 智慧緊急事件助手。請像真人對話一樣承接上下文，使用繁體中文回覆。

回覆原則：
- 先安撫並承接使用者剛剛說的內容。
- 不要重複問已經回答過的問題。
- 醫療急症：優先確認是否有反應、呼吸是否正常；無反應或呼吸異常時提醒立刻撥打 119。
- 偏鄉/山區/國家公園/步道/溪谷救援：優先提醒 119，並確認 GPS 座標或步道地標、同行人數、傷勢/可否移動、手機電量與訊號。
- 天然災害：先提醒遠離倒塌、淹水、土石流等危險區域，再確認是否有人受困或受傷；有人受困/受傷優先 119。
- 受困救援/自殺危機/失蹤走失：優先確認位置與立即危險；電梯受困偏 119，自殺危機同步 119/110，失蹤走失偏 110。
- 暴力/火災/交通事故：先提醒使用者保持安全距離，再問下一個最關鍵問題。
- 回覆保持簡短清楚，通常 1 到 2 句即可。
- 如果還需要資訊，只問下一個最重要的問題。

已知事件資訊：
{known_context}

對話狀態：
{dialogue_state_text}

音訊或位置資訊：
{audio_context_text}

目前對話：
{conversation}

請直接輸出助理下一句回覆，不要輸出 JSON，不要加「助理：」。
"""


def _clean_natural_reply(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    if cleaned.startswith("{"):
        try:
            payload = json.loads(extract_json_object_text(cleaned))
            reply = str(payload.get("reply") or "").strip()
            next_question_text = str(payload.get("next_question") or "").strip()
            cleaned = " ".join(part for part in [reply, next_question_text] if part)
        except Exception:
            pass

    for marker in ["</s>", "<|im_end|>", "<|endoftext|>"]:
        cleaned = cleaned.replace(marker, "")

    # Some instruct models echo the transcript. Keep the last assistant segment.
    for marker in ["助理：", "Assistant:", "assistant:"]:
        if marker in cleaned:
            cleaned = cleaned.split(marker)[-1].strip()

    for marker in ["使用者：", "User:", "user:"]:
        if marker in cleaned:
            cleaned = cleaned.split(marker)[0].strip()

    return _compact_natural_reply(cleaned)


def _sentence_key(sentence: str) -> str:
    return re.sub(r"[\s，,。！？!?、：:；;（）()【】\[\]「」『』\"'`*_]+", "", sentence)


def _split_sentences(text: str) -> List[str]:
    return [
        sentence.strip()
        for sentence in re.findall(r"[^。！？!?]+[。！？!?]?", text)
        if sentence.strip()
    ]


def _looks_repetitive(text: str) -> bool:
    sentences = _split_sentences(text)
    if len(sentences) < 4:
        return False
    keys = [_sentence_key(sentence) for sentence in sentences if _sentence_key(sentence)]
    return len(keys) - len(set(keys)) >= 2


def _compact_natural_reply(text: str, *, max_sentences: int = 3, max_chars: int = 180) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not cleaned:
        return ""

    sentences = _split_sentences(cleaned.replace("\n", " "))
    if not sentences:
        return cleaned[:max_chars].strip()

    unique_sentences: List[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        key = _sentence_key(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_sentences.append(sentence)
        candidate = "".join(unique_sentences).strip()
        if len(unique_sentences) >= max_sentences or len(candidate) >= max_chars:
            break

    compact = "".join(unique_sentences).strip()
    if len(compact) <= max_chars:
        return compact

    complete = "".join(
        sentence for sentence in unique_sentences if sentence[-1:] in "。！？!?"
    ).strip()
    return (complete or compact[:max_chars]).strip()


def _has_any(text: str, terms: List[str]) -> bool:
    return any(term in text for term in terms)


_CHILD_PROTECTION_TERMS = [
    "小孩",
    "孩子",
    "兒童",
    "幼童",
    "嬰兒",
    "哭叫",
    "哀號",
    "尖叫",
    "求救",
    "家暴",
    "虐待",
    "受虐",
    "打小孩",
    "摔東西",
    "隔壁",
]


def _has_child_protection_signal(text: str) -> bool:
    has_child = _has_any(text, ["小孩", "孩子", "兒童", "幼童", "嬰兒"])
    has_distress = _has_any(
        text,
        ["哭", "哭聲", "哀號", "哭叫", "尖叫", "求救", "慘叫", "哭很大聲", "一直哭"],
    )
    has_family_violence = _has_any(
        text,
        ["家暴", "虐待", "受虐", "打小孩", "打罵", "摔東西", "砸東西"],
    )
    has_neighbor_context = _has_any(text, ["隔壁", "樓上", "樓下", "鄰居"])
    return has_family_violence or (has_child and has_distress) or (has_neighbor_context and has_distress)


def _is_child_protection_context(messages: List[ChatMessage]) -> bool:
    return _has_child_protection_signal(_joined_user_text(messages))


def _is_negative_turn(text: str) -> bool:
    normalized = text.strip().lower()
    return _has_any(normalized, ["沒有", "沒", "無", "不是", "沒有其他", "沒有人"])


def _is_positive_turn(text: str) -> bool:
    normalized = text.strip().lower()
    return _has_any(normalized, ["有", "是", "還在", "持續", "正在", "需要"])


def _last_assistant_text(messages: List[ChatMessage]) -> str:
    for message in reversed(messages[:-1]):
        if message.role == "assistant":
            return message.content.strip()
    return ""


def _is_violence_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "暴力事件":
        return True
    joined_user_text = " ".join(
        message.content for message in messages if message.role == "user"
    )
    if _has_child_protection_signal(joined_user_text):
        return True
    return _has_any(
        joined_user_text,
        ["打架", "互毆", "拳頭", "揮拳", "衝突", "暴力", "被打", "鬥毆", "家暴", "打罵"],
    )


def _joined_user_text(messages: List[ChatMessage]) -> str:
    return " ".join(message.content for message in messages if message.role == "user")


def _is_medical_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "醫療急症":
        return True
    text = _joined_user_text(messages)
    return _has_any(
        text,
        [
            "昏倒", "倒地", "沒反應", "叫不醒", "意識", "呼吸",
            "喘", "胸痛", "抽搐", "流血", "受傷", "發燒", "不舒服",
        ],
    )


def _is_fire_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "火災":
        return True
    text = _joined_user_text(messages)
    return _has_any(text, ["火災", "失火", "著火", "起火", "冒煙", "濃煙", "焦味", "瓦斯味"])


def _is_traffic_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "交通事故":
        return True
    text = _joined_user_text(messages)
    return _has_any(text, ["車禍", "撞車", "擦撞", "追撞", "機車", "汽車", "被撞", "路口事故"])


def _is_natural_disaster_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "天然災害":
        return True
    text = _joined_user_text(messages)
    return _has_any(
        text,
        [
            "天然災害", "地震", "強震", "餘震", "颱風", "豪雨", "水災", "淹水", "積水",
            "土石流", "坡地崩塌", "坍方", "建築物倒塌", "房屋倒塌", "大樓倒塌",
            "牆倒塌", "橋斷", "道路中斷", "瓦礫", "被壓住", "有人被埋",
        ],
    )


def _is_trapped_rescue_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "受困救援":
        return True
    text = _joined_user_text(messages)
    return _has_any(text, ["電梯受困", "困在電梯", "卡在電梯", "電梯卡住", "電梯故障", "電梯打不開", "出不了電梯", "出不來電梯"])


def _is_self_harm_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "自殺危機":
        return True
    text = _joined_user_text(messages)
    return _has_any(text, ["自殺", "想死", "不想活", "輕生", "尋短", "跳樓", "要跳樓", "準備跳樓", "站在頂樓", "站在陽台外", "割腕", "吞藥", "燒炭", "上吊"])


def _is_missing_person_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    if normalize_category_name(state.category) == "失蹤走失":
        return True
    text = _joined_user_text(messages)
    return _has_any(text, ["失蹤", "走失", "找不到人", "找不到小孩", "找不到老人", "老人走失", "小孩走失", "小孩失蹤", "長輩走失", "家人失聯", "聯絡不上", "不見了"])


def _is_remote_rescue_context(state: Extracted, messages: List[ChatMessage]) -> bool:
    return is_remote_rescue_extracted(state.symptom_summary) or has_remote_rescue_signal(
        _joined_user_text(messages)
    )


def _apply_natural_turn_context(state: Extracted, messages: List[ChatMessage]) -> Extracted:
    latest_text = latest_user_text(messages)
    previous_assistant = _last_assistant_text(messages)
    if not latest_text:
        return state

    if _is_remote_rescue_context(state, messages):
        state = _apply_remote_rescue_turn_context(state, latest_text, previous_assistant)
    elif _is_violence_context(state, messages):
        state = _apply_violence_turn_context(state, latest_text, previous_assistant)
    elif _is_fire_context(state, messages):
        state = _apply_fire_turn_context(state, latest_text, previous_assistant)
    elif _is_traffic_context(state, messages):
        state = _apply_traffic_turn_context(state, latest_text, previous_assistant)
    elif _is_trapped_rescue_context(state, messages):
        state = _apply_trapped_rescue_turn_context(state, latest_text, previous_assistant)
    elif _is_self_harm_context(state, messages):
        state = _apply_self_harm_turn_context(state, latest_text, previous_assistant)
    elif _is_missing_person_context(state, messages):
        state = _apply_missing_person_turn_context(state, latest_text, previous_assistant)
    elif _is_natural_disaster_context(state, messages):
        state = _apply_natural_disaster_turn_context(state, latest_text, previous_assistant)
    elif _is_medical_context(state, messages):
        state = _apply_medical_turn_context(state, latest_text, previous_assistant)

    # Final pass: fill any remaining None slots from short affirmation/negation replies
    if previous_assistant:
        from backend.services.slot_resolver import apply_slot_resolver
        state = apply_slot_resolver(latest_text, previous_assistant, state)

    state.dispatch_advice = get_dispatch_advice(
        state.category,
        state.weapon,
        state.people_injured,
    )
    return state


def _apply_violence_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "暴力事件"
    if _has_child_protection_signal(latest_text):
        state.danger_active = True
    asked_weapon = _has_any(previous_assistant, ["武器", "持刀", "棍棒", "槍", "刀"])
    asked_injury = _has_any(previous_assistant, ["受傷", "流血", "傷者", "有人受傷"])
    asked_danger = _has_any(previous_assistant, ["還在", "持續", "繼續", "現場衝突", "還在打"])

    if asked_weapon or _has_any(latest_text, ["武器", "持刀", "棍棒", "槍", "刀"]):
        if _is_negative_turn(latest_text):
            state.weapon = False
        elif _has_any(latest_text, ["持刀", "拿刀", "刀", "棍棒", "槍", "武器"]):
            state.weapon = True
        elif asked_weapon and _is_positive_turn(latest_text):
            state.weapon = True

    if asked_injury or _has_any(latest_text, ["受傷", "流血", "傷者"]):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, ["受傷", "流血", "倒地", "昏倒", "傷者"]):
            state.people_injured = True
        elif asked_injury and _is_positive_turn(latest_text):
            state.people_injured = True

    if asked_danger or _has_any(latest_text, ["還在", "持續", "正在", "停了", "散了", "結束"]):
        if _has_any(latest_text, ["停了", "散了", "結束", "沒有繼續", "沒在打"]):
            state.danger_active = False
        elif _has_any(latest_text, ["還在", "持續", "正在", "繼續", "還沒停"]):
            state.danger_active = True
        elif asked_danger and _is_negative_turn(latest_text):
            state.danger_active = False
        elif asked_danger and _is_positive_turn(latest_text):
            state.danger_active = True

    return state


def _apply_medical_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "醫療急症"
    asked_conscious = _has_any(previous_assistant, ["意識", "反應", "叫得醒", "清醒"])
    asked_breathing = _has_any(previous_assistant, ["呼吸", "喘", "喘不過氣", "沒呼吸"])
    asked_symptoms = _has_any(previous_assistant, ["症狀", "受傷", "流血", "胸痛", "發燒", "抽搐"])

    if asked_conscious or _has_any(latest_text, ["意識", "反應", "叫得醒", "清醒", "昏倒", "叫不醒", "沒反應"]):
        if _has_any(latest_text, ["沒反應", "沒有反應", "叫不醒", "昏倒", "意識不清", "失去意識"]):
            state.conscious = False
        elif _has_any(latest_text, ["清醒", "有反應", "叫得醒", "意識清楚"]):
            state.conscious = True
        elif asked_conscious and _is_negative_turn(latest_text):
            state.conscious = False
        elif asked_conscious and _is_positive_turn(latest_text):
            state.conscious = True

    if asked_breathing or _has_any(latest_text, ["呼吸", "喘", "喘不過氣", "沒呼吸", "呼吸困難"]):
        if _has_any(latest_text, ["呼吸正常", "正常呼吸", "沒有呼吸困難", "沒有喘", "不喘"]):
            state.breathing_difficulty = False
        elif _has_any(latest_text, ["呼吸困難", "喘不過氣", "很喘", "沒呼吸", "沒有呼吸", "嘴唇發紫"]):
            state.breathing_difficulty = True
        elif asked_breathing and _is_negative_turn(latest_text):
            state.breathing_difficulty = False
        elif asked_breathing and _is_positive_turn(latest_text):
            state.breathing_difficulty = True

    if asked_symptoms or _has_any(latest_text, ["受傷", "流血", "胸痛", "發燒", "抽搐", "骨折"]):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, ["受傷", "流血", "胸痛", "抽搐", "骨折", "大量出血"]):
            state.people_injured = True
        elif asked_symptoms and _is_positive_turn(latest_text):
            state.people_injured = True
        if _has_any(latest_text, ["發燒", "燒到", "高燒"]):
            state.fever = True

    return state


def _apply_fire_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "火災"
    asked_fire_active = _has_any(previous_assistant, ["火勢", "濃煙", "冒煙", "還在燒", "持續"])
    asked_trapped = _has_any(previous_assistant, ["受困", "受傷", "裡面有人", "吸入濃煙"])

    if asked_fire_active or _has_any(latest_text, ["火勢", "濃煙", "冒煙", "還在燒", "燒起來", "焦味"]):
        if _has_any(latest_text, ["沒有火", "沒看到火", "沒有濃煙", "只聞到焦味", "已經滅了", "火滅了"]):
            state.danger_active = False
        elif _has_any(latest_text, ["還在燒", "火很大", "濃煙", "冒煙", "火勢", "燒起來"]):
            state.danger_active = True
        elif asked_fire_active and _is_negative_turn(latest_text):
            state.danger_active = False
        elif asked_fire_active and _is_positive_turn(latest_text):
            state.danger_active = True

    if asked_trapped or _has_any(latest_text, ["受困", "裡面有人", "受傷", "吸入濃煙", "嗆到"]):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, ["受困", "裡面有人", "受傷", "吸入濃煙", "嗆到"]):
            state.people_injured = True
        elif asked_trapped and _is_positive_turn(latest_text):
            state.people_injured = True

    return state


def _apply_traffic_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "交通事故"
    asked_injury = _has_any(previous_assistant, ["受傷", "受困", "流血", "有人倒地"])
    asked_road_danger = _has_any(previous_assistant, ["車道", "路中間", "漏油", "冒煙", "阻擋"])

    if asked_injury or _has_any(latest_text, ["受傷", "受困", "流血", "倒地", "摔倒"]):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, ["受傷", "受困", "流血", "倒地", "摔倒", "卡在車內"]):
            state.people_injured = True
        elif asked_injury and _is_positive_turn(latest_text):
            state.people_injured = True

    if asked_road_danger or _has_any(latest_text, ["車道", "路中間", "漏油", "冒煙", "阻擋", "還在路上"]):
        if _has_any(latest_text, ["沒有阻擋", "移到旁邊", "不在車道", "沒有漏油", "沒有冒煙"]):
            state.danger_active = False
        elif _has_any(latest_text, ["路中間", "車道", "漏油", "冒煙", "阻擋", "還在路上"]):
            state.danger_active = True
        elif asked_road_danger and _is_negative_turn(latest_text):
            state.danger_active = False
        elif asked_road_danger and _is_positive_turn(latest_text):
            state.danger_active = True

    return state


def _apply_natural_disaster_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "天然災害"
    asked_danger = _has_any(previous_assistant, ["還在", "持續", "危險", "倒塌", "淹水", "土石流", "坍方"])
    asked_trapped = _has_any(previous_assistant, ["受困", "受傷", "被壓住", "被埋", "有人"])

    danger_terms = [
        "地震", "強震", "還在搖", "餘震", "淹水", "積水", "水位上升", "土石流",
        "坡地崩塌", "坍方", "倒塌", "橋斷", "道路中斷", "瓦斯外洩", "停電",
    ]
    safe_terms = ["水退了", "已經撤離", "已經避難", "現在安全", "救援到了", "消防到了"]
    trapped_or_injured_terms = [
        "受困", "受傷", "流血", "倒地", "骨折", "被壓住", "有人被埋", "瓦礫壓住", "困在裡面", "出不來",
    ]

    if asked_danger or _has_any(latest_text, danger_terms):
        if _has_any(latest_text, safe_terms):
            state.danger_active = False
        elif _has_any(latest_text, danger_terms):
            state.danger_active = True
        elif asked_danger and _is_negative_turn(latest_text):
            state.danger_active = False
        elif asked_danger and _is_positive_turn(latest_text):
            state.danger_active = True

    if asked_trapped or _has_any(latest_text, trapped_or_injured_terms):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, trapped_or_injured_terms):
            state.people_injured = True
        elif asked_trapped and _is_positive_turn(latest_text):
            state.people_injured = True

    return state


def _apply_trapped_rescue_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "受困救援"
    asked_injury = _has_any(previous_assistant, ["受傷", "不舒服", "呼吸", "昏倒", "老人", "小孩"])
    asked_still_trapped = _has_any(previous_assistant, ["還在", "受困", "電梯", "出來", "打開"])

    if asked_injury or _has_any(latest_text, ["受傷", "不舒服", "昏倒", "呼吸困難", "喘不過氣"]):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, ["受傷", "不舒服", "昏倒", "呼吸困難", "喘不過氣"]):
            state.people_injured = True
        elif asked_injury and _is_positive_turn(latest_text):
            state.people_injured = True

    if asked_still_trapped or _has_any(latest_text, ["電梯受困", "困在電梯", "卡在電梯", "電梯卡住", "電梯打不開", "出不來", "已經出來"]):
        if _has_any(latest_text, ["已經出來", "電梯開了", "消防到了", "管理員到了", "現在安全"]):
            state.danger_active = False
        elif _has_any(latest_text, ["電梯受困", "困在電梯", "卡在電梯", "電梯卡住", "電梯打不開", "出不來"]):
            state.danger_active = True
        elif asked_still_trapped and _is_negative_turn(latest_text):
            state.danger_active = False
        elif asked_still_trapped and _is_positive_turn(latest_text):
            state.danger_active = True

    return state


def _apply_self_harm_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "自殺危機"
    asked_active = _has_any(previous_assistant, ["危險位置", "頂樓", "陽台", "刀", "藥", "一個人", "現在"])
    asked_injury = _has_any(previous_assistant, ["受傷", "流血", "吞藥", "割腕", "沒反應"])

    if asked_active or _has_any(latest_text, ["要跳樓", "準備跳樓", "站在頂樓", "站在陽台外", "拿刀", "割腕", "吞藥", "燒炭", "上吊", "一個人"]):
        if _has_any(latest_text, ["已經有人陪", "已經離開危險位置", "警察到了", "救護車到了", "現在安全"]):
            state.danger_active = False
        elif _has_any(latest_text, ["自殺", "想死", "要跳樓", "站在頂樓", "站在陽台外", "拿刀", "割腕", "吞藥", "燒炭", "上吊", "一個人"]):
            state.danger_active = True
        elif asked_active and _is_negative_turn(latest_text):
            state.danger_active = False
        elif asked_active and _is_positive_turn(latest_text):
            state.danger_active = True

    if asked_injury or _has_any(latest_text, ["割腕", "流血", "吞藥", "吃藥", "昏倒", "沒反應", "受傷"]):
        if _is_negative_turn(latest_text):
            state.people_injured = False
        elif _has_any(latest_text, ["割腕", "流血", "吞藥", "吃藥", "昏倒", "沒反應", "受傷"]):
            state.people_injured = True
        elif asked_injury and _is_positive_turn(latest_text):
            state.people_injured = True

    return state


def _apply_missing_person_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    state.category = "失蹤走失"
    asked_found = _has_any(previous_assistant, ["找到", "聯絡", "最後", "還沒回來"])

    if _has_any(latest_text, ["找到了", "回來了", "已經聯絡上", "警察到了", "現在安全"]):
        state.danger_active = False
    elif asked_found or _has_any(latest_text, ["失蹤", "走失", "失聯", "找不到", "聯絡不上", "不見了", "手機關機"]):
        if _is_negative_turn(latest_text):
            state.danger_active = False
        else:
            state.danger_active = True

    if _has_any(latest_text, ["小孩", "幼兒", "老人", "長輩", "失智", "身心障礙", "需要服藥"]):
        state.people_injured = True

    return state


def _apply_remote_rescue_turn_context(
    state: Extracted,
    latest_text: str,
    previous_assistant: str,
) -> Extracted:
    if state.category in [None, "待確認"]:
        state.category = "山域水域救援"
    if not is_remote_rescue_extracted(state.symptom_summary):
        state.symptom_summary = (
            f"{state.symptom_summary}、疑似山域水域救援"
            if state.symptom_summary
            else "疑似山域水域救援"
        )

    if _has_any(latest_text, ["受傷", "摔落", "滑落", "墜落", "墜谷", "骨折", "不能走", "無法走", "無法行走", "流血", "溺水", "被水沖走", "被沖走", "沖走", "失溫", "高山症", "中暑", "熱衰竭", "蛇咬", "蜂螫"]):
        state.people_injured = True
    if _has_any(latest_text, ["沒受傷", "沒有受傷", "無人受傷"]):
        state.people_injured = False
    if _has_any(latest_text, ["受困", "迷路", "迷途", "溪水暴漲", "溪水變大", "溪水變急", "水位上升", "被水沖走", "被沖走", "沖走", "卡在對岸", "過不了溪", "過不了河", "漂走", "水變深", "渡溪失敗", "坍方", "落石", "土石流", "失聯", "手機快沒電", "手機沒電", "快沒電", "電量不足", "剩一格電", "只剩一格電", "剩5%", "剩 5%", "剩不到10%", "剩不到 10%", "沒訊號", "沒有訊號", "訊號不好", "定位跑掉", "GPS不準", "GPS 不準", "找不到座標", "不知道座標", "沒有座標", "下大雨", "大雨", "起霧", "濃霧", "氣溫很低", "低溫", "很冷", "天黑", "天色變暗"]):
        state.danger_active = True
    if _has_any(latest_text, ["已經下山", "已經脫困", "救援到了", "消防到了", "現在安全"]):
        state.danger_active = False

    if _has_any(previous_assistant, ["同行", "幾個人"]) and _is_positive_turn(latest_text):
        state.people_injured = state.people_injured
    return state


def _remote_rescue_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "山域水域救援" and not is_remote_rescue_extracted(state.symptom_summary):
        return None
    if state.conscious is False or state.breathing_difficulty is True:
        return "這是高風險山域救援狀況，請立刻撥打 119，開擴音依照指示處理，並準備回報 GPS 座標、步道地標、同行人數和傷者狀況。"
    return "這比較像山域或偏鄉救援情境，請優先撥打 119，並準備 GPS 座標、步道地標、同行人數、傷勢和手機電量。"


def _violence_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "暴力事件":
        return None
    if state.weapon is None:
        return "請先保持安全距離，不要靠近衝突中的人。你有看到對方或現場的人拿刀、棍棒或其他武器嗎？"
    if state.people_injured is None:
        return "了解，先不要靠近他們。現場有沒有人受傷或流血？"
    if state.danger_active is None:
        return "了解。請先保持安全距離，並通知站務人員或警方。現場衝突還在持續嗎？"
    if state.danger_active:
        return "目前衝突還在持續，請不要介入或靠近，盡快通知站務人員或警方，並移到安全位置等候協助。"
    return "了解，目前衝突已經停下來。請仍然保持距離，確認周圍安全，並把現場位置與狀況告知站務人員或警方。"


def _child_protection_next_reply(state: Extracted, messages: List[ChatMessage]) -> Optional[str]:
    if not _is_child_protection_context(messages):
        return None
    if normalize_category_name(state.category) not in [None, "暴力事件", "待確認"]:
        return None

    latest_text = latest_user_text(messages)
    previous_assistant = _last_assistant_text(messages)
    asked_active = _has_any(previous_assistant, ["還在持續", "仍在持續", "現在還聽得到"])
    asked_help = _has_any(previous_assistant, ["求救", "打罵", "摔東西", "受傷"])

    if state.weapon is True:
        return "這是高風險情況，請不要靠近或介入。請在安全位置立即通知警察或管理員，並告知疑似兒少受害、現場有人持有武器。"
    if not asked_active and state.danger_active is None:
        return "這可能涉及家暴或兒少安全，請先不要靠近或敲門。你現在還聽得到小孩哀號、哭叫或摔東西的聲音嗎？"
    if asked_active and _is_negative_turn(latest_text):
        return "了解，聲音暫時停止仍需要保持警覺。請記下時間與位置，若再次聽到求救、打罵或摔東西，請立即通知警察或管理員。"
    if not asked_help:
        return "請保持安全距離，不要自行介入。你有聽到求救、打罵、摔東西，或看到小孩可能受傷的跡象嗎？"
    return "這是高風險情況，請在安全位置立即通知警察或管理員，並提供你聽到的位置、時間和聲音狀況。"


def _medical_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "醫療急症":
        return None
    if is_remote_rescue_extracted(state.symptom_summary):
        if state.conscious is False or state.breathing_difficulty is True:
            return "這是高風險山域救援狀況，請立刻撥打 119，開擴音依照指示處理，並準備回報 GPS 座標、步道地標、同行人數和傷者狀況。"
        return "這比較像山域或偏鄉救援情境，請優先撥打 119，並準備 GPS 座標、步道地標、同行人數、傷勢和手機電量。"
    if state.conscious is None:
        return "請先確認他是否有反應、叫得醒嗎？如果叫不醒，請立刻請旁邊的人協助撥打 119。"
    if state.breathing_difficulty is None:
        return "他目前呼吸是否正常？有沒有喘不過氣、嘴唇發紫，或沒有呼吸？"
    if state.people_injured is None and state.fever is None:
        return "除了目前狀況外，還有大量出血、胸痛、抽搐、高燒，或其他症狀正在加重嗎？"
    if state.conscious is False or state.breathing_difficulty is True:
        return "這屬於需要立即處理的狀況。請立刻撥打 119，讓旁邊的人協助找 AED，並依照 119 指示處理。"
    return "了解。請讓他先保持休息並持續觀察，如果症狀加重、意識變差或呼吸異常，請立即撥打 119。"


def _fire_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "火災":
        return None
    if state.danger_active is None:
        return "請先離開火場並避開濃煙，不要搭電梯。現場火勢或濃煙還在持續嗎？"
    if state.people_injured is None:
        return "現場有沒有人受困、受傷，或吸入濃煙感到不舒服？"
    if state.danger_active or state.people_injured:
        return "請立刻撥打 119，移到安全位置等待消防人員，並告知起火位置、是否有人受困。"
    return "了解，目前看起來沒有明顯火勢或人員受傷。請仍保持警覺，通知管理員或消防單位確認來源。"


def _traffic_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "交通事故":
        return None
    if state.people_injured is None:
        return "請先移到安全位置，不要站在車道上。現場有沒有人受傷、流血或被困住？"
    if state.danger_active is None:
        return "車輛是否還在車道中，或有漏油、冒煙、阻擋交通的情況？"
    if state.people_injured or state.danger_active:
        return "請保持安全距離，盡快通知警方；如果有人受傷或受困，請同時撥打 119。"
    return "了解，目前沒有人受傷且沒有明顯二次事故風險。請仍記錄位置與車況，必要時通知警方協助。"


def _natural_disaster_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "天然災害":
        return None
    if state.danger_active is None:
        return "請先遠離倒塌、淹水、土石流或瓦斯味等危險區域。現場危險還在持續嗎？"
    if state.people_injured is None:
        return "現場有沒有人受困、被壓住、受傷，或需要救護車？"
    if state.danger_active or state.people_injured:
        return "請優先撥打 119，告知災害類型、位置、是否有人受困或受傷；如果也有人身威脅，再同步通報 110。"
    return "了解，目前看起來已經離開主要危險。請仍保持警覺，留在安全處並依地方災害應變或消防指示行動。"


def _trapped_rescue_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "受困救援":
        return None
    if state.danger_active is None:
        return "請不要強行開電梯門或攀爬。人現在還困在電梯裡嗎？"
    if state.people_injured is None:
        return "電梯裡有幾個人？有沒有人受傷、不舒服、呼吸困難，或有老人小孩孕婦？"
    if state.danger_active or state.people_injured:
        return "請撥打 119 或請管理員同步通知消防，告知地址、樓層、電梯編號與是否有人不適。"
    return "了解，若已經脫困仍請確認人員狀況；若電梯異常未排除，請通知管理員或消防協助。"


def _self_harm_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "自殺危機":
        return None
    if state.danger_active is None:
        return "請先不要刺激或拉扯對方，保持陪伴與安全距離。對方現在還在頂樓、陽台邊、持刀或已經吞藥嗎？"
    if state.people_injured is None:
        return "對方目前有受傷、流血、吞藥、昏倒或沒有反應嗎？"
    return "這是高風險狀況，請立刻同步撥打 119 和 110，告知位置、樓層、現場危險物與對方目前狀態。"


def _missing_person_next_reply(state: Extracted) -> Optional[str]:
    if normalize_category_name(state.category) != "失蹤走失":
        return None
    if state.danger_active is None:
        return "請先確認最後看到人的時間、地點與穿著。現在還聯絡不上或找不到人嗎？"
    if state.people_injured is None:
        return "走失的人是小孩、長輩、失智或需要服藥的人嗎？有沒有可能受傷或受困？"
    return "建議盡快通報 110，提供最後出現地點、時間、穿著、照片與聯絡方式；若在山區水域或可能受困受傷，請同步 119。"


def _category_flow_reply(state: Extracted) -> Optional[str]:
    for builder in [
        _remote_rescue_next_reply,
        _violence_next_reply,
        _medical_next_reply,
        _fire_next_reply,
        _traffic_next_reply,
        _trapped_rescue_next_reply,
        _self_harm_next_reply,
        _missing_person_next_reply,
        _natural_disaster_next_reply,
    ]:
        reply = builder(state)
        if reply:
            return reply
    return None


def _refine_natural_reply_for_context(
    reply: str,
    state: Extracted,
    messages: Optional[List[ChatMessage]] = None,
) -> str:
    text = _compact_natural_reply(reply.strip())
    category = normalize_category_name(state.category)
    child_flow_reply = _child_protection_next_reply(state, messages or [])
    if child_flow_reply:
        generic_child_question = any(
            token in text
            for token in ["哪個小孩", "最擔心", "哪一部分", "想先知道"]
        )
        if generic_child_question or _looks_repetitive(reply) or len(reply) > 180:
            return child_flow_reply
    asks_medical_followup = any(
        token in text
        for token in ["呼吸", "昏倒", "意識", "送醫", "喘不過氣"]
    )
    asks_weapon_again = any(
        token in text
        for token in ["武器", "持刀", "棍棒", "拿刀", "槍"]
    )
    asks_injury_again = any(
        token in text
        for token in ["受傷", "流血", "傷者", "有人受傷"]
    )
    asks_danger_again = any(
        token in text
        for token in ["還在持續", "還在打", "衝突還在", "是否持續"]
    )
    if category == "暴力事件":
        flow_reply = _violence_next_reply(state)
        if flow_reply and (_looks_repetitive(reply) or len(reply) > 220):
            return flow_reply
        if state.weapon is not None and asks_weapon_again and flow_reply:
            return flow_reply
        if state.people_injured is not None and (asks_injury_again or asks_medical_followup) and flow_reply:
            return flow_reply
        if state.danger_active is not None and asks_danger_again and flow_reply:
            return flow_reply
    if category == "暴力事件" and state.people_injured is False and asks_medical_followup:
        flow_reply = _violence_next_reply(state)
        if flow_reply:
            return flow_reply
    if category == "山域水域救援" or is_remote_rescue_extracted(state.symptom_summary):
        flow_reply = _remote_rescue_next_reply(state)
        if flow_reply and (_looks_repetitive(reply) or len(reply) > 220):
            return flow_reply
    if category == "醫療急症":
        flow_reply = _medical_next_reply(state)
        if flow_reply and (_looks_repetitive(reply) or len(reply) > 220):
            return flow_reply
        asks_conscious_again = state.conscious is not None and any(token in text for token in ["意識", "反應", "叫得醒"])
        asks_breathing_again = state.breathing_difficulty is not None and any(token in text for token in ["呼吸", "喘", "沒呼吸"])
        asks_symptoms_again = (state.people_injured is not None or state.fever is not None) and any(
            token in text for token in ["大量出血", "胸痛", "抽搐", "發燒", "症狀"]
        )
        if flow_reply and (asks_conscious_again or asks_breathing_again or asks_symptoms_again):
            return flow_reply
    if category == "火災":
        flow_reply = _fire_next_reply(state)
        if flow_reply and (_looks_repetitive(reply) or len(reply) > 220):
            return flow_reply
        asks_fire_again = state.danger_active is not None and any(token in text for token in ["火勢", "濃煙", "冒煙"])
        asks_trapped_again = state.people_injured is not None and any(token in text for token in ["受困", "受傷", "吸入濃煙"])
        if flow_reply and (asks_fire_again or asks_trapped_again):
            return flow_reply
    if category == "交通事故":
        flow_reply = _traffic_next_reply(state)
        if flow_reply and (_looks_repetitive(reply) or len(reply) > 220):
            return flow_reply
        asks_injury_again = state.people_injured is not None and any(token in text for token in ["受傷", "受困", "流血"])
        asks_road_again = state.danger_active is not None and any(token in text for token in ["車道", "路中間", "漏油", "冒煙"])
        if flow_reply and (asks_injury_again or asks_road_again):
            return flow_reply
    return text


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
    report_created: bool = False,
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
    if client_location_text:
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
    conversation_state = _apply_natural_turn_context(conversation_state, messages)
    preview_risk_score, preview_risk_level = apply_structured_risk_floor(
        " ".join(m.content for m in messages if m.role == "user"),
        conversation_state,
        preview_risk_score,
        preview_risk_level,
    )
    preview_semantic = heuristic_semantic_understanding(
        latest_text,
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
    compact_chat_path = should_use_compact_chat_path(messages, pre_dialogue_state, latest_text)
    skip_graph_lookup = should_skip_graph_lookup(compact_chat_path, latest_text, conversation_state)
    if _uses_natural_chat_model():
        skip_graph_lookup = True
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

    response_guides = match_incident_response_guides(context, conversation_state)
    known_context = json.dumps(
        {
            "category": conversation_state.category,
            "location": conversation_state.location,
            "people_injured": conversation_state.people_injured,
            "weapon": conversation_state.weapon,
            "danger_active": conversation_state.danger_active,
            "dispatch_advice": conversation_state.dispatch_advice,
            "response_guides": response_guides,
            "report_created": report_created,
            "report_note": "通報已建立，系統已協助聯繫救援，不需要再叫使用者撥打119或110" if report_created else None,
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

    meta = {
        "chat_path": "compact" if compact_chat_path else "full",
        "skip_graph_lookup": skip_graph_lookup,
        "context_turns": len(recent),
    }

    if _uses_natural_chat_model():
        natural_prompt = _build_natural_chat_prompt(
            recent=recent,
            known_context=known_context,
            dialogue_state_text=dialogue_state_text,
            audio_context_text=audio_context_text,
        )
        natural_resp = call_llm(
            natural_prompt,
            max_tokens=min(llm_max_tokens or 192, 192),
        )
        natural_reply = _clean_natural_reply(natural_resp.text or "")
        if natural_reply:
            natural_reply = _refine_natural_reply_for_context(
                natural_reply,
                conversation_state,
                messages,
            )
            return {
                "reply": natural_reply,
                "next_question": None,
                "risk_score": preview_risk_score,
                "risk_level": preview_risk_level,
                "should_escalate": preview_risk_level == "High",
                "extracted": model_to_dict(conversation_state),
                "semantic": model_to_dict(preview_semantic),
                "_meta": {
                    **meta,
                    "natural_chat": True,
                },
            }

    resp = call_llm(prompt, max_tokens=llm_max_tokens)
    text = (resp.text or "").strip()
    try:
        data = parse_llm_json_text(text)
    except RuntimeError:
        # If the LLM returned truncated JSON, try extracting the reply field directly.
        reply_match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if reply_match:
            natural_reply = reply_match.group(1).replace('\\"', '"').replace('\\n', '\n').strip()
        else:
            natural_reply = _clean_natural_reply(text)
        if not natural_reply:
            raise
        natural_reply = _refine_natural_reply_for_context(
            natural_reply,
            conversation_state,
            messages,
        )
        return {
            "reply": natural_reply,
            "next_question": None,
            "risk_score": preview_risk_score,
            "risk_level": preview_risk_level,
            "should_escalate": preview_risk_level == "High",
            "extracted": model_to_dict(conversation_state),
            "semantic": model_to_dict(preview_semantic),
            "_meta": {
                **meta,
                "natural_chat": True,
                "json_parse_failed": True,
            },
        }
    if isinstance(data, dict):
        data["_meta"] = meta
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


def _voice_prompt_for_tts(text: str) -> str:
    prompt = (text or "").strip()
    if not prompt:
        return ""

    replacements = {
        "CPR": "胸外按壓",
        "cpr": "胸外按壓",
        "AED": "自動體外心臟電擊器",
        "aed": "自動體外心臟電擊器",
        "119": "一一九",
        "110": "一一零",
    }
    for old, new in replacements.items():
        prompt = prompt.replace(old, new)

    prompt = prompt.replace("是否有", "有沒有")
    prompt = prompt.replace("是否", "有沒有")
    prompt = prompt.replace("有沒有有", "有沒有")
    prompt = prompt.replace("系統已列為高風險通報。", "")
    prompt = prompt.replace("高風險通報。", "")
    prompt = re.sub(r"\s+", " ", prompt)
    prompt = re.sub(r"[;；]+", "。", prompt)
    return prompt.strip()


def _trim_voice_prompt(prompt: str, *, max_chars: int = 38) -> str:
    prompt = prompt.strip()
    if len(prompt) <= max_chars:
        return prompt
    sentences = _split_sentences(prompt)
    shortened = ""
    for sentence in sentences:
        if len(shortened + sentence) > max_chars:
            break
        shortened += sentence
    return shortened.strip() or prompt[:max_chars].rstrip("，、。") + "。"


def _finalize_voice_prompt(prompt: str) -> str:
    """Normalize the final prompt before it is sent to TTS."""
    return _voice_prompt_for_tts(prompt)


def _with_voice_empathy(prompt: str, *, urgent: bool = False) -> str:
    prompt = prompt.strip()
    if not prompt:
        return ""

    prompt = re.sub(r"^我在[，,。]?", "", prompt).strip()
    if urgent:
        prefix = "我在，先別慌。我會陪你確認。"
    else:
        prefix = "我在，我會協助你。"
    return _trim_voice_prompt(_finalize_voice_prompt(prefix + prompt))


def _build_dynamic_voice_prompt(
    reply: str,
    next_question_text: Optional[str],
    *,
    urgent: bool = False,
) -> str:
    combined = " ".join(part.strip() for part in [reply, next_question_text or ""] if part and part.strip())
    combined = _voice_prompt_for_tts(combined)
    if not combined:
        return ""

    sentences = _split_sentences(combined)
    action_terms = [
        "請",
        "確認",
        "保持",
        "準備",
        "撤離",
        "遠離",
        "不要",
        "開擴音",
        "觀察",
        "回報",
        "如果沒有",
        "如果情況",
        "有沒有",
        "先",
        "現在",
        "告訴我",
    ]
    action_sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and _has_any(sentence, action_terms)
    ]
    candidate_sentences = action_sentences or sentences

    picked: List[str] = []
    for sentence in candidate_sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        if _has_any(normalized, ["收到", "目前這比較像", "我先幫你", "我在這裡"]):
            continue
        if "系統已列為" in normalized and not _has_any(normalized, ["請", "確認", "保持"]):
            continue
        normalized = normalized.replace("你的家人目前沒有反應，", "")
        normalized = normalized.replace("患者目前沒有反應，", "")
        normalized = normalized.replace("傷者目前沒有反應，", "")
        normalized = normalized.replace("請保持手機可接通，現在確認", "先確認")
        normalized = normalized.replace("請保持手機可接通。現在確認", "先確認")
        normalized = normalized.replace("請保持手機可接通，", "")
        normalized = normalized.replace("現在確認", "先確認")
        picked.append(normalized)
        if len("".join(picked)) >= 48 or len(picked) >= 2:
            break

    prompt = "".join(picked).strip() or combined
    return _with_voice_empathy(prompt, urgent=urgent)


def _build_medical_step_voice_prompt(
    ex: Extracted,
    reply: str,
    next_question_text: Optional[str],
) -> str:
    """Return one CPR/AED voice step instead of reading a whole paragraph."""
    if ex.category != "醫療急症":
        return ""

    combined = " ".join(
        part.strip()
        for part in [reply, next_question_text or ""]
        if part and part.strip()
    )
    if not combined:
        return ""

    if _has_any(combined, ["打開 AED", "AED 已經到現場", "AED 電源", "貼上電極片"]):
        return "好，打開機器，照著語音，一步一步來。分析的時候，不要碰他。"

    if _has_any(combined, ["找 AED", "尋找 AED", "旁邊的人找 AED"]):
        return "我在，請旁邊的人，去找自動體外心臟電擊器。你先看他，有沒有在呼吸。"

    if _has_any(combined, ["CPR", "胸外按壓", "開始按壓"]):
        return "我在陪你，不要怕。雙手交疊，放在胸口中央，用力往下壓，速度穩定——你做得到的。"

    if _has_any(combined, ["胸口", "正常呼吸", "沒有正常呼吸", "呼吸可能不正常"]):
        return "我在，深呼吸一下。看他的胸口，有沒有起伏，有沒有在呼吸。"

    return ""


def _build_voice_fields(
    ex: Extracted,
    risk_level: str,
    should_escalate: bool,
    reply: str = "",
    next_question_text: Optional[str] = None,
) -> tuple:
    """產生語音播報欄位 (voice_prompt, voice_priority, should_speak)。

    只在高風險或需立即行動時啟用。voice_prompt 設計為短句，適合 TTS 朗讀。
    """
    is_immediate = (
        (ex.category == "醫療急症" and (ex.conscious is False or ex.breathing_difficulty is True))
        or (ex.category in ["暴力事件", "可疑人士"] and ex.weapon is True)
        or (ex.category == "火災" and ex.danger_active is True)
        or (ex.category == "天然災害" and (ex.danger_active is True or ex.people_injured is True))
        or (ex.category in ["受困救援", "自殺危機"] and (ex.danger_active is True or ex.people_injured is True))
    )
    should_speak = bool(should_escalate or risk_level == "High" or is_immediate)
    if not should_speak:
        return None, None, False

    cat = ex.category or ""
    dynamic_prompt = _build_dynamic_voice_prompt(
        reply,
        next_question_text,
        urgent=bool(risk_level == "High" or is_immediate),
    )
    step_prompt = _build_medical_step_voice_prompt(ex, reply, next_question_text)
    if cat == "醫療急症":
        if ex.conscious is False or ex.breathing_difficulty is True:
            prompt = "我在，深呼吸一下。看他的胸口，有沒有起伏，有沒有在呼吸。"
            priority = "high"
        else:
            prompt = "我在，請持續觀察他的狀況。有任何變化，隨時告訴我。"
            priority = "high"
    elif cat == "火災":
        prompt = "我在，請現在就離開，遠離濃煙，彎低身體移動，不要搭電梯。"
        priority = "high"
    elif cat == "天然災害":
        prompt = "我在，請先離開倒塌、淹水或土石流危險區，保持手機可接通。"
        priority = "high"
    elif cat == "受困救援":
        prompt = "我在，請不要強行開門或攀爬，保持通話，等待消防或管理員協助。"
        priority = "high"
    elif cat == "自殺危機":
        prompt = "我在，請保持安全距離陪著對方，立刻同步撥打 119 和 110。"
        priority = "high"
    elif cat == "失蹤走失":
        prompt = "我在，請先記下最後看到的時間、地點、穿著，並盡快通報警方。"
        priority = "medium"
    elif cat in ["暴力事件", "可疑人士"]:
        if ex.weapon is True:
            prompt = "我在，請先離開現場，移到安全的地方，不要回頭。"
            priority = "high"
        else:
            prompt = "我在，你先確認自己安全，保持手機可接通。"
            priority = "medium"
    elif cat == "交通事故":
        prompt = "我在，請先移到安全的位置，確認現場有沒有人需要幫忙。"
        priority = "medium"
    else:
        prompt = "我在，請保持手機可接通，有任何變化，隨時告訴我。"
        priority = "medium"

    is_critical_medical = cat == "醫療急症" and (
        ex.conscious is False or ex.breathing_difficulty is True
    )
    if step_prompt:
        # Specific CPR/AED guidance always takes priority
        prompt = step_prompt
    elif dynamic_prompt and not is_critical_medical:
        # For critical medical (no breathing / unconscious), keep the structured
        # prompt instead of echoing the LLM's clarifying question back as audio.
        prompt = dynamic_prompt

    return _finalize_voice_prompt(prompt), priority, True


def _build_report_status_hint(
    ex: Extracted,
    risk_level: str,
    should_escalate: bool,
) -> str:
    """回傳通報狀態提示字串，前端可用於 UI 或狀態列。

    目前不實際建立通報，故不回 report_created。
    """
    if risk_level == "High" or should_escalate:
        if ex.location and ex.category and ex.category not in ("待確認", None):
            return "report_recommended"
        return "high_risk_detected"
    if risk_level == "Medium":
        return "monitoring"
    return "none"


def process_chat_request(
    messages: List[ChatMessage],
    audio_context: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    user_context: Optional[ChatUserContext] = None,
    report_created: bool = False,
) -> ChatResponse:
    context = " ".join(m.content for m in messages if m.role == "user").strip()
    latest_text = latest_user_text(messages)
    conversation_state = extract_conversation_state(messages)
    conversation_state = _apply_natural_turn_context(conversation_state, messages)

    if not context:
        return _EMPTY_CONTEXT_RESPONSE

    try:
        data = llm_chat_with_audio(messages, audio_context, session_id, user_context,
                                   report_created=report_created)
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
        ex = merge_extracted(conversation_state, ex)
        # Re-apply slot resolver after merge so it fills any slots the LLM left as None
        ex = _apply_natural_turn_context(ex, messages)
        # Plan B: LLM slot extractor for phrasing variants rule-based system missed.
        # Skip for natural-language models (ecare-v4): _apply_natural_turn_context already handles slots.
        if llm_is_ready() and len(latest_text.strip()) > 4 and not _uses_natural_chat_model():
            from backend.services.semantic import llm_extract_slots
            ex = llm_extract_slots(latest_text, _last_assistant_text(messages), ex)
        if client_location_text:
            ex.location = client_location_text
        if not any(token in context for token in ["發燒", "高燒", "發熱", "沒有發燒"]):
            ex.fever = None
        if (
            any(token in context for token in ["不知道他有沒有呼吸", "不知道有沒有呼吸", "不確定有沒有呼吸"])
            and not any(token in context for token in ["不能呼吸", "喘不過氣", "呼吸困難"])
            and not ("沒呼吸" in context and "有沒有呼吸" not in context)
            and not ("沒有呼吸" in context and "有沒有呼吸" not in context)
        ):
            ex.breathing_difficulty = None

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
                context, audio_context, semantic.entities, extracted=ex,
            )

        reply = data.get("reply") or "我會一步一步協助你整理資訊。"
        nq = data.get("next_question") or next_question(ex, risk_level)
        llm_reply, llm_nq = reply, nq
        llm_category = normalize_category_name(extracted_raw.get("category"))

        reply, nq = contextualize_reply_and_question(messages, ex, reply, nq, risk_level)
        reply, nq = adapt_opening_turn_response(messages, reply, nq, ex, semantic)
        reply = apply_semantic_tone(reply, semantic, risk_level, audio_context,
                                    previous_assistant_text=_last_assistant_text(messages))
        nq = next_question_from_semantic(nq, semantic, ex, risk_level, audio_context,
                                         messages=messages)
        reply, nq = sanitize_reply_and_question(reply, nq, ex, risk_level, messages=messages)

        dialogue_state = build_dialogue_state(messages, ex, semantic, risk_level, audio_context)
        log_chat_debug(
            "final_success", latest_text, ex, semantic, dialogue_state,
            reply, nq, risk_level, risk_score,
            llm_category=llm_category,
            reply_changed=reply != llm_reply,
            next_question_changed=nq != llm_nq,
        )
        voice_prompt, voice_priority, should_speak = _build_voice_fields(
            ex,
            risk_level,
            should_escalate,
            reply,
            nq,
        )
        return ChatResponse(
            reply=reply,
            risk_score=risk_score,
            risk_level=risk_level,
            should_escalate=should_escalate,
            next_question=nq,
            extracted=ex,
            semantic=semantic,
            voice_prompt=voice_prompt,
            voice_priority=voice_priority,
            should_speak=should_speak,
            report_status_hint=_build_report_status_hint(ex, risk_level, should_escalate),
        )

    except Exception as e:
        print("LLM fallback:", str(e))

        score, level = simple_risk(context)
        ex = simple_extract(context)
        ex = apply_turn_context(messages, ex)
        client_location_text = get_client_location_text(audio_context)
        ex = merge_extracted(conversation_state, ex)
        if client_location_text:
            ex.location = client_location_text
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
            extracted=ex,
        )
        if level == "High":
            reply = "我了解你現在很緊張，我會快速協助你整理資訊並引導你進行通報。"
        elif level == "Medium":
            reply = "我了解你的狀況，我會一步步協助你整理必要資訊。"
        else:
            reply = "我在這裡，我會協助你把事情講清楚。"

        nq = next_question_from_semantic(next_question(ex, level), semantic, ex, level,
                                         audio_context, messages=messages)
        reply, nq = contextualize_reply_and_question(messages, ex, reply, nq, level)
        reply, nq = adapt_opening_turn_response(messages, reply, nq, ex, semantic)
        reply = apply_semantic_tone(reply, semantic, level, audio_context,
                                    previous_assistant_text=_last_assistant_text(messages))
        reply, nq = sanitize_reply_and_question(reply, nq, ex, level, messages=messages)

        dialogue_state = build_dialogue_state(messages, ex, semantic, level, audio_context)
        log_chat_debug(
            "final_fallback", latest_text, ex, semantic, dialogue_state,
            reply, nq, level, score,
        )
        escalate = (level == "High")
        voice_prompt, voice_priority, should_speak = _build_voice_fields(
            ex,
            level,
            escalate,
            reply,
            nq,
        )
        return ChatResponse(
            reply=reply,
            risk_score=score,
            risk_level=level,
            should_escalate=escalate,
            next_question=nq,
            extracted=ex,
            semantic=semantic,
            voice_prompt=voice_prompt,
            voice_priority=voice_priority,
            should_speak=should_speak,
            report_status_hint=_build_report_status_hint(ex, level, escalate),
        )
