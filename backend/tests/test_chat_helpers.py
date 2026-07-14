"""_build_voice_fields 與 _build_report_status_hint 的單元測試。"""
import pytest

from backend.models import Extracted
from backend.services.chat import (
    _build_dynamic_voice_prompt,
    _build_medical_step_voice_prompt,
    _build_report_status_hint,
    _build_voice_fields,
    _fire_next_reply,
    _medical_next_reply,
    _missing_person_next_reply,
    _natural_disaster_next_reply,
    _noise_next_reply,
    _refine_natural_reply_for_context,
    _remote_rescue_next_reply,
    _self_harm_next_reply,
    _suspicious_next_reply,
    _trapped_rescue_next_reply,
)


# ======================
# _build_voice_fields
# ======================

def test_voice_low_risk_no_speak():
    ex = Extracted(category="噪音")
    prompt, priority, speak = _build_voice_fields(ex, "Low", False)
    assert speak is False
    assert prompt is None
    assert priority is None


def test_voice_high_risk_general():
    ex = Extracted(category="待確認")
    _, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "medium"


def test_voice_medical_unconscious():
    ex = Extracted(category="醫療急症", conscious=False)
    prompt, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "high"
    assert "我在" in prompt
    assert "有沒有在呼吸" in prompt


def test_voice_fields_normalize_tts_sensitive_terms():
    ex = Extracted(category="醫療急症", people_injured=True)
    prompt, priority, speak = _build_voice_fields(
        ex,
        "High",
        True,
        "收到，AED 已經到現場。請保持手機可接通。",
        "請打開 AED 電源，依語音貼上電極片；AED 分析時不要碰患者。",
    )
    assert speak is True
    assert priority == "high"
    assert "AED" not in prompt
    assert "打開機器" in prompt


def test_voice_medical_breathing_difficulty():
    ex = Extracted(category="醫療急症", breathing_difficulty=True)
    prompt, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "high"


def test_voice_medical_stable_high():
    ex = Extracted(category="醫療急症", people_injured=True)
    _, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "high"


def test_voice_fire_active():
    ex = Extracted(category="火災", danger_active=True)
    prompt, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "high"
    assert "離開" in prompt


def test_voice_fire_trigger_by_immediate():
    ex = Extracted(category="火災", danger_active=True)
    _, _, speak = _build_voice_fields(ex, "Medium", False)
    assert speak is True


def test_voice_violence_with_weapon():
    ex = Extracted(category="暴力事件", weapon=True)
    prompt, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "high"
    assert "離開" in prompt


def test_voice_violence_no_weapon():
    ex = Extracted(category="暴力事件", weapon=False)
    _, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "medium"


def test_voice_traffic_high():
    ex = Extracted(category="交通事故", people_injured=True)
    _, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "medium"


def test_voice_medium_no_immediate_no_speak():
    ex = Extracted(category="噪音")
    _, _, speak = _build_voice_fields(ex, "Medium", False)
    assert speak is False


def test_dynamic_voice_prefers_action_guidance():
    prompt = _build_dynamic_voice_prompt(
        "你的家人目前沒有反應，系統已列為高風險通報。請保持手機可接通，現在確認胸口是否有起伏、是否有正常呼吸；如果沒有正常呼吸，請開擴音聽救援指示，並請旁邊的人找 AED。",
        None,
        urgent=True,
    )
    assert prompt.startswith("我在")
    assert "系統已列為" not in prompt
    assert "AED" not in prompt
    assert len(prompt) <= 76


def test_dynamic_voice_can_follow_question():
    prompt = _build_dynamic_voice_prompt(
        "聽起來情況很緊急。",
        "請告訴我，傷者現在有沒有正常呼吸？",
        urgent=True,
    )
    assert "有沒有正常呼吸" in prompt


def test_medical_step_voice_aed_arrived():
    ex = Extracted(category="醫療急症", people_injured=True)
    prompt = _build_medical_step_voice_prompt(
        ex,
        "收到，AED 已經到現場。請保持手機可接通，並照 AED 語音或救援人員指示操作。",
        "請打開 AED 電源，依語音貼上電極片；AED 分析或準備電擊時，確認所有人都離開傷者身體。",
    )
    assert "打開機器" in prompt
    assert "不要碰他" in prompt


def test_medical_step_voice_find_aed():
    ex = Extracted(category="醫療急症", conscious=False)
    prompt = _build_medical_step_voice_prompt(
        ex,
        "你的家人目前沒有反應。",
        "如果沒有正常呼吸，請開擴音聽救援指示，並請旁邊的人找 AED。",
    )
    assert "自動體外心臟電擊器" in prompt
    assert "有沒有在呼吸" in prompt


def test_medical_step_voice_breathing_check():
    ex = Extracted(category="醫療急症", conscious=False)
    prompt = _build_medical_step_voice_prompt(
        ex,
        "收到，目前這比較像是醫療急症。",
        "請確認胸口是否有起伏、有沒有正常呼吸。",
    )
    assert "深呼吸" in prompt
    assert "有沒有在呼吸" in prompt


# ======================
# _build_report_status_hint
# ======================

def test_hint_low_is_none():
    ex = Extracted()
    assert _build_report_status_hint(ex, "Low", False) == "none"


def test_hint_medium_is_monitoring():
    ex = Extracted(category="噪音")
    assert _build_report_status_hint(ex, "Medium", False) == "monitoring"


def test_hint_high_no_location_is_detected():
    ex = Extracted(category="醫療急症")
    assert _build_report_status_hint(ex, "High", True) == "high_risk_detected"


def test_hint_high_with_location_and_category_is_recommended():
    ex = Extracted(category="醫療急症", location="台北市中正區")
    assert _build_report_status_hint(ex, "High", True) == "report_recommended"


def test_hint_high_unconfirmed_category_is_detected():
    ex = Extracted(category="待確認", location="台北車站")
    assert _build_report_status_hint(ex, "High", True) == "high_risk_detected"


def test_hint_escalate_true_overrides_level():
    ex = Extracted(category="暴力事件", location="忠孝東路")
    assert _build_report_status_hint(ex, "Medium", True) == "report_recommended"


# ======================
# _refine_natural_reply_for_context — 先前遺漏的分類（天然災害/受困救援/自殺危機/失蹤走失/可疑人士/噪音）
# ======================

_OVERLONG_REPLY = "我在，先不要緊張，我們一步一步整理狀況。" * 6


@pytest.mark.parametrize(
    ("category", "extra_fields", "expected_builder"),
    [
        ("天然災害", {"danger_active": True, "people_injured": True}, _natural_disaster_next_reply),
        ("受困救援", {"danger_active": True, "people_injured": True}, _trapped_rescue_next_reply),
        ("自殺危機", {"danger_active": True, "people_injured": True}, _self_harm_next_reply),
        ("失蹤走失", {"danger_active": True, "people_injured": True}, _missing_person_next_reply),
        ("可疑人士", {"weapon": False, "danger_active": True}, _suspicious_next_reply),
        ("噪音", {"danger_active": True, "people_injured": True}, _noise_next_reply),
    ],
)
def test_refine_natural_reply_replaces_overlong_reply_for_all_categories(
    category, extra_fields, expected_builder
):
    ex = Extracted(category=category, **extra_fields)
    result = _refine_natural_reply_for_context(_OVERLONG_REPLY, ex, messages=[])
    assert result == expected_builder(ex)
    assert len(result) <= 220


def test_refine_natural_reply_replaces_self_harm_reply_reasking_known_danger():
    ex = Extracted(category="自殺危機", danger_active=True)
    reply = "我在，對方目前還在頂樓嗎？"
    result = _refine_natural_reply_for_context(reply, ex, messages=[])
    assert result == _self_harm_next_reply(ex)


def test_refine_natural_reply_keeps_short_non_repeating_reply():
    ex = Extracted(category="天然災害")
    reply = "我在，先確認你目前是否安全。"
    result = _refine_natural_reply_for_context(reply, ex, messages=[])
    assert result == reply


# ======================
# 山域水域救援 — 已知 GPS 位置時不重複詢問座標
# ======================

def test_remote_rescue_next_reply_confirms_known_location():
    ex = Extracted(category="山域水域救援", location="24.500000, 121.300000 (+/- 20m)")
    reply = _remote_rescue_next_reply(ex)
    assert "24.500000, 121.300000" in reply
    assert "已收到你的位置" in reply


def test_remote_rescue_next_reply_without_location_asks_for_gps():
    ex = Extracted(category="山域水域救援")
    reply = _remote_rescue_next_reply(ex)
    assert "GPS 座標" in reply
    assert "已收到你的位置" not in reply


def test_medical_next_reply_delegates_to_remote_rescue_when_extracted():
    ex = Extracted(
        category="醫療急症",
        symptom_summary="疑似山域水域救援",
        location="南投縣仁愛鄉步道",
    )
    assert _medical_next_reply(ex) == _remote_rescue_next_reply(ex)


# ======================
# 火災/天然災害/自殺危機 — 已知位置時不重複詢問位置
# ======================

def test_fire_next_reply_confirms_known_location():
    ex = Extracted(
        category="火災", danger_active=True, people_injured=False,
        location="台北市信義路100號",
    )
    reply = _fire_next_reply(ex)
    assert "已收到你的位置：台北市信義路100號" in reply
    assert "告知起火位置" not in reply


def test_fire_next_reply_without_location_still_asks():
    ex = Extracted(category="火災", danger_active=True, people_injured=False)
    reply = _fire_next_reply(ex)
    assert "告知起火位置" in reply


def test_natural_disaster_next_reply_confirms_known_location():
    ex = Extracted(
        category="天然災害", danger_active=True, people_injured=False,
        location="南投縣埔里鎮",
    )
    reply = _natural_disaster_next_reply(ex)
    assert "已收到你的位置：南投縣埔里鎮" in reply


def test_self_harm_next_reply_confirms_known_location():
    ex = Extracted(
        category="自殺危機",
        danger_active=True,
        people_injured=False,
        location="台中市西區某大樓頂樓",
    )
    reply = _self_harm_next_reply(ex)
    assert "已收到你的位置：台中市西區某大樓頂樓" in reply
