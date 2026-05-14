"""_build_voice_fields 與 _build_report_status_hint 的單元測試。"""
import pytest

from backend.models import Extracted
from backend.services.chat import _build_voice_fields, _build_report_status_hint


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
    assert "CPR" in prompt


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
    assert "疏散" in prompt


def test_voice_fire_trigger_by_immediate():
    ex = Extracted(category="火災", danger_active=True)
    _, _, speak = _build_voice_fields(ex, "Medium", False)
    assert speak is True


def test_voice_violence_with_weapon():
    ex = Extracted(category="暴力事件", weapon=True)
    prompt, priority, speak = _build_voice_fields(ex, "High", True)
    assert speak is True
    assert priority == "high"
    assert "撤離" in prompt


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
