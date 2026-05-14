"""風險評分模組的單元測試。"""
import pytest

from backend.services.risk import (
    compact_signal_text,
    contains_any_keyword,
    has_child_distress_signal,
    has_child_unresponsive_signal,
    has_disturbance_signal,
    has_high_risk_context_signal,
    has_ongoing_disturbance_signal,
    is_repeated_alert_noise,
    risk_level_from_score,
)


# ======================
# risk_level_from_score
# ======================

def test_risk_level_high():
    assert risk_level_from_score(0.9) == "High"
    assert risk_level_from_score(0.81) == "High"
    assert risk_level_from_score(1.0) == "High"


def test_risk_level_medium():
    assert risk_level_from_score(0.8) == "Medium"   # 0.8 不 > 0.8
    assert risk_level_from_score(0.6) == "Medium"
    assert risk_level_from_score(0.51) == "Medium"


def test_risk_level_low():
    assert risk_level_from_score(0.5) == "Low"      # 0.5 不 > 0.5
    assert risk_level_from_score(0.2) == "Low"
    assert risk_level_from_score(0.0) == "Low"


# ======================
# compact_signal_text
# ======================

def test_compact_strips_spaces():
    assert compact_signal_text("  救 救 救  ") == "救救救"


def test_compact_removes_punctuation():
    assert compact_signal_text("救、救、救") == "救救救"
    assert compact_signal_text("救，救，救") == "救救救"
    assert compact_signal_text("救。救。救") == "救救救"


def test_compact_empty():
    assert compact_signal_text("") == ""
    assert compact_signal_text("   ") == ""


# ======================
# is_repeated_alert_noise
# ======================

def test_repeated_noise_single_char():
    assert is_repeated_alert_noise("救救救") is True
    assert is_repeated_alert_noise("刀刀刀") is True
    assert is_repeated_alert_noise("火火火") is True
    assert is_repeated_alert_noise("血血血") is True


def test_repeated_noise_multi_char():
    assert is_repeated_alert_noise("救命救命救命") is True


def test_repeated_noise_too_short():
    assert is_repeated_alert_noise("救救") is False   # len=2 < 3
    assert is_repeated_alert_noise("救") is False


def test_repeated_noise_normal_text():
    assert is_repeated_alert_noise("樓下有人打架") is False
    assert is_repeated_alert_noise("") is False


def test_repeated_noise_with_punctuation():
    assert is_repeated_alert_noise("救、救、救") is True


# ======================
# has_disturbance_signal
# ======================

def test_disturbance_signal_keyword():
    assert has_disturbance_signal("樓上一直在吵架") is True
    assert has_disturbance_signal("鄰居在大叫") is True


def test_disturbance_signal_negative():
    assert has_disturbance_signal("今天天氣很好") is False


# ======================
# has_ongoing_disturbance_signal
# ======================

def test_ongoing_disturbance_both_terms():
    assert has_ongoing_disturbance_signal("吵架還在持續") is True
    assert has_ongoing_disturbance_signal("大吼大叫一直沒有停") is True


def test_ongoing_disturbance_missing_one():
    assert has_ongoing_disturbance_signal("吵架") is False
    assert has_ongoing_disturbance_signal("還在持續") is False


# ======================
# has_child_distress_signal
# ======================

def test_child_distress_child_crying():
    assert has_child_distress_signal("小孩一直哭") is True
    assert has_child_distress_signal("嬰兒在哀號") is True


def test_child_distress_neighbor_crying():
    assert has_child_distress_signal("隔壁傳來哭聲") is True
    assert has_child_distress_signal("樓下有人在哭叫") is True


def test_child_distress_no_signal():
    assert has_child_distress_signal("小孩在玩") is False
    assert has_child_distress_signal("哭聲") is False  # 沒有 child/neighbor 詞


# ======================
# has_child_unresponsive_signal
# ======================

def test_child_unresponsive():
    assert has_child_unresponsive_signal("小孩叫不醒") is True
    assert has_child_unresponsive_signal("嬰兒失去意識") is True


def test_child_unresponsive_pronoun():
    assert has_child_unresponsive_signal("他沒有反應") is True


def test_child_unresponsive_no_signal():
    assert has_child_unresponsive_signal("小孩在睡覺") is False


# ======================
# has_high_risk_context_signal
# ======================

def test_high_risk_weapon():
    assert has_high_risk_context_signal("對方拿刀追我") is True
    assert has_high_risk_context_signal("有人持槍威脅") is True


def test_high_risk_medical_unresponsive():
    assert has_high_risk_context_signal("叫不醒") is True
    assert has_high_risk_context_signal("沒有呼吸") is True


def test_high_risk_child_unresponsive():
    assert has_high_risk_context_signal("小孩沒有反應") is True


def test_high_risk_traffic():
    assert has_high_risk_context_signal("車禍有人受傷倒地") is True


def test_high_risk_negated_weapon():
    assert has_high_risk_context_signal("沒有刀") is False


def test_high_risk_normal_text():
    assert has_high_risk_context_signal("有點吵") is False
    assert has_high_risk_context_signal("門口有人") is False


# ======================
# contains_any_keyword
# ======================

def test_contains_any_keyword_match():
    assert contains_any_keyword("有人昏倒了", ["昏倒", "暈倒"]) is True


def test_contains_any_keyword_no_match():
    assert contains_any_keyword("今天下雨", ["昏倒", "暈倒"]) is False


def test_contains_any_keyword_empty():
    assert contains_any_keyword("", ["昏倒"]) is False
    assert contains_any_keyword("昏倒", []) is False
