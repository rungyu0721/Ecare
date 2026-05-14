"""Pydantic 資料模型的單元測試。"""
import pytest
from pydantic import ValidationError

from backend.models import (
    ChatMessage,
    ChatRequest,
    Extracted,
    SemanticUnderstanding,
    ChatResponse,
    ReportCreate,
    UserCreate,
    UserItem,
    model_to_dict,
    latest_user_text,
)


# ======================
# ChatMessage
# ======================

def test_chat_message_user():
    msg = ChatMessage(role="user", content="有人在打架")
    assert msg.role == "user"
    assert msg.content == "有人在打架"


def test_chat_message_assistant():
    msg = ChatMessage(role="assistant", content="請告訴我地點")
    assert msg.role == "assistant"


def test_chat_message_invalid_role():
    with pytest.raises(ValidationError):
        ChatMessage(role="system", content="hello")


def test_chat_message_empty_content_is_allowed():
    msg = ChatMessage(role="user", content="")
    assert msg.content == ""


# ======================
# Extracted
# ======================

def test_extracted_defaults():
    ex = Extracted()
    assert ex.category is None
    assert ex.location is None
    assert ex.people_injured is None
    assert ex.weapon is None
    assert ex.danger_active is None
    assert ex.conscious is None
    assert ex.breathing_difficulty is None
    assert ex.fever is None


def test_extracted_medical():
    ex = Extracted(category="醫療急症", people_injured=True, conscious=False)
    assert ex.category == "醫療急症"
    assert ex.people_injured is True
    assert ex.conscious is False


def test_extracted_fire():
    ex = Extracted(category="火災", danger_active=True, people_injured=False)
    assert ex.category == "火災"
    assert ex.danger_active is True
    assert ex.people_injured is False


def test_extracted_weapon_none_vs_false():
    ex_none = Extracted()
    ex_false = Extracted(weapon=False)
    assert ex_none.weapon is None
    assert ex_false.weapon is False


# ======================
# SemanticUnderstanding
# ======================

def test_semantic_understanding_defaults():
    su = SemanticUnderstanding()
    assert su.intent == "未知"
    assert su.primary_need == "釐清狀況"
    assert su.emotion == "neutral"


def test_semantic_understanding_custom():
    su = SemanticUnderstanding(intent="緊急通報", emotion="fearful")
    assert su.intent == "緊急通報"
    assert su.emotion == "fearful"


# ======================
# ChatRequest
# ======================

def test_chat_request_minimal():
    req = ChatRequest(messages=[ChatMessage(role="user", content="你好")])
    assert len(req.messages) == 1
    assert req.session_id is None
    assert req.audio_context is None


def test_chat_request_with_session():
    req = ChatRequest(
        messages=[ChatMessage(role="user", content="火災")],
        session_id="abc-123",
    )
    assert req.session_id == "abc-123"


# ======================
# ChatResponse — 新欄位預設值
# ======================

def test_chat_response_new_fields_default():
    resp = ChatResponse(
        reply="收到",
        risk_score=0.3,
        risk_level="Low",
        should_escalate=False,
        next_question=None,
        extracted=Extracted(),
        semantic=SemanticUnderstanding(),
    )
    assert resp.should_speak is False
    assert resp.voice_prompt is None
    assert resp.voice_priority is None
    assert resp.report_status_hint is None


def test_chat_response_high_risk_fields():
    resp = ChatResponse(
        reply="高風險",
        risk_score=0.95,
        risk_level="High",
        should_escalate=True,
        next_question="請確認呼吸",
        extracted=Extracted(category="醫療急症", conscious=False),
        semantic=SemanticUnderstanding(),
        voice_prompt="系統已列為高風險通報。請確認患者呼吸。",
        voice_priority="high",
        should_speak=True,
        report_status_hint="high_risk_detected",
    )
    assert resp.should_speak is True
    assert resp.voice_priority == "high"
    assert resp.report_status_hint == "high_risk_detected"


# ======================
# ReportCreate
# ======================

def test_report_create_valid():
    r = ReportCreate(
        title="路口火災",
        category="火災",
        location="台北市中正區",
        risk_level="High",
        risk_score=0.9,
        description="路口有火",
    )
    assert r.risk_level == "High"
    assert r.latitude is None


def test_report_create_with_coordinates():
    r = ReportCreate(
        title="車禍",
        category="交通事故",
        location="忠孝東路",
        latitude=25.04,
        longitude=121.54,
        risk_level="Medium",
        risk_score=0.65,
        description="機車追撞",
    )
    assert r.latitude == pytest.approx(25.04)
    assert r.longitude == pytest.approx(121.54)


# ======================
# UserCreate / UserItem
# ======================

def test_user_create_minimal():
    u = UserCreate(name="王小明")
    assert u.name == "王小明"
    assert u.phone is None
    assert u.age is None


def test_user_create_full():
    u = UserCreate(
        name="李美玲",
        phone="0912345678",
        gender="女",
        age=30,
        emergency_name="李爸爸",
        emergency_phone="0987654321",
        relationship="父女",
    )
    assert u.age == 30
    assert u.relationship == "父女"


def test_user_item_requires_id():
    with pytest.raises((ValidationError, TypeError)):
        UserItem(name="沒有ID")


# ======================
# 工具函式
# ======================

def test_latest_user_text_empty():
    assert latest_user_text([]) == ""


def test_latest_user_text_single():
    msgs = [ChatMessage(role="user", content="火！")]
    assert latest_user_text(msgs) == "火！"


def test_latest_user_text_finds_last():
    msgs = [
        ChatMessage(role="user", content="第一句"),
        ChatMessage(role="assistant", content="回應"),
        ChatMessage(role="user", content="第二句"),
        ChatMessage(role="assistant", content="再回應"),
    ]
    assert latest_user_text(msgs) == "第二句"


def test_latest_user_text_only_assistant():
    msgs = [ChatMessage(role="assistant", content="你好")]
    assert latest_user_text(msgs) == ""


def test_model_to_dict_extracted():
    ex = Extracted(category="火災", danger_active=True)
    d = model_to_dict(ex)
    assert isinstance(d, dict)
    assert d["category"] == "火災"
    assert d["danger_active"] is True
    assert "people_injured" in d


def test_model_to_dict_preserves_none():
    ex = Extracted()
    d = model_to_dict(ex)
    assert d["weapon"] is None
