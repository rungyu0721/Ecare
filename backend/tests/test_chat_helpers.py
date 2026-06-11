"""_build_voice_fields 與 _build_report_status_hint 的單元測試。"""
import pytest

from backend.models import Extracted
from backend.services.chat import (
    _build_dynamic_voice_prompt,
    _build_medical_step_voice_prompt,
    _build_report_status_hint,
    _build_voice_fields,
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
