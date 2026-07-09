"""後處理模組的單元測試（純字串函式）。"""
import pytest

from backend.services.postprocess import (
    contextualize_reply_and_question,
    has_aed_arrived,
    has_called_119,
    has_no_normal_breathing,
    looks_like_report_style_reply,
    previous_question_intent,
    remove_duplicate_next_question,
)
from backend.models import ChatMessage, Extracted


# ======================
# has_no_normal_breathing
# ======================

def test_no_breathing_direct():
    assert has_no_normal_breathing("沒呼吸") is True
    assert has_no_normal_breathing("沒有呼吸") is True
    assert has_no_normal_breathing("不呼吸") is True


def test_no_breathing_abnormal():
    assert has_no_normal_breathing("胸口沒有起伏") is True
    assert has_no_normal_breathing("瀕死式呼吸") is True
    assert has_no_normal_breathing("像打鼾") is True


def test_no_breathing_normal():
    assert has_no_normal_breathing("呼吸正常") is False
    assert has_no_normal_breathing("還在呼吸") is False
    assert has_no_normal_breathing("") is False


# ======================
# has_called_119
# ======================

def test_called_119_phrases():
    assert has_called_119("已經撥119了") is True
    assert has_called_119("打119了") is True
    assert has_called_119("已撥119") is True


def test_called_119_with_spaces():
    assert has_called_119("已經撥 119 了") is True   # compact removes spaces


def test_called_119_not_yet():
    assert has_called_119("還沒打電話") is False
    assert has_called_119("要撥119嗎") is False
    assert has_called_119("") is False


# ======================
# has_aed_arrived
# ======================

def test_aed_arrived_phrases():
    assert has_aed_arrived("AED到了") is True
    assert has_aed_arrived("有AED") is True
    assert has_aed_arrived("拿到AED") is True
    assert has_aed_arrived("我找到 AED 了") is True
    assert has_aed_arrived("AED在旁邊") is True


def test_aed_not_arrived():
    assert has_aed_arrived("找不到AED") is False
    assert has_aed_arrived("需要AED") is False
    assert has_aed_arrived("") is False


# ======================
# looks_like_report_style_reply
# ======================

def test_report_style_two_markers():
    text = "案件類型：火災\n地點：台北市\n風險等級：High"
    assert looks_like_report_style_reply(text) is True


def test_report_style_single_marker():
    text = "案件類型：火災"
    assert looks_like_report_style_reply(text) is False


def test_report_style_pipe_separator():
    text = "類型 | 地點 | 風險等級"
    assert looks_like_report_style_reply(text) is True


def test_report_style_normal_reply():
    assert looks_like_report_style_reply("請問現場有人受傷嗎？") is False
    assert looks_like_report_style_reply("收到，你先保持冷靜。") is False
    assert looks_like_report_style_reply("") is False


# ======================
# previous_question_intent
# ======================

def test_intent_consciousness_medical():
    q = "請問傷者有意識嗎？叫得醒嗎？"
    assert previous_question_intent(q, "醫療急症") == "consciousness"


def test_intent_breathing_medical():
    q = "傷者的呼吸是否正常？有沒有喘？"
    assert previous_question_intent(q, "醫療急症") == "breathing"


def test_intent_weapon_violence():
    q = "現場對方有持刀或其他武器嗎？"
    assert previous_question_intent(q, "暴力事件") == "weapon"


def test_intent_danger_active():
    q = "目前危險還在持續嗎？對方還在現場嗎？"
    assert previous_question_intent(q, "暴力事件") == "danger_active"


def test_intent_fire_active():
    q = "火勢現在還在燃燒嗎？"
    assert previous_question_intent(q, "火災") == "fire_active"


def test_intent_injury():
    q = "現場有沒有人受傷？"
    assert previous_question_intent(q, "交通事故") == "injury"


def test_intent_none_for_empty():
    assert previous_question_intent("", None) is None


def test_intent_none_for_irrelevant():
    assert previous_question_intent("今天天氣不錯", None) is None


# ======================
# remove_duplicate_next_question
# ======================

def test_no_duplicate_returns_original():
    reply = "了解，現場有人受傷。"
    next_q = "現場是否有武器？"
    result = remove_duplicate_next_question(reply, next_q)
    assert result == next_q


def test_similar_weapon_question_removed():
    reply = "收到。現場對方是否有持刀或其他武器？"
    next_q = "對方手上有刀或槍嗎？"
    assert remove_duplicate_next_question(reply, next_q) == ""


def test_empty_next_q_stays_empty():
    assert remove_duplicate_next_question("任何回應", "") == ""


def test_non_question_reply_no_removal():
    reply = "了解，我會幫你整理通報內容。"
    next_q = "請問傷者意識是否清醒？"
    assert remove_duplicate_next_question(reply, next_q) == next_q


def test_aed_arrived_context_goes_to_aed_guidance():
    messages = [
        ChatMessage(
            role="assistant",
            content="請確認胸口是否有起伏、有沒有正常呼吸；如果沒有正常呼吸，請開擴音聽救援指示，並請旁邊的人找 AED。",
        ),
        ChatMessage(role="user", content="我找到 AED 了，現在要怎麼做？"),
    ]
    ex = Extracted(category="醫療急症", people_injured=True)
    reply, next_q = contextualize_reply_and_question(
        messages,
        ex,
        "收到，目前這比較像是醫療急症，我先幫你確認症狀變化。",
        "請確認他有沒有正常呼吸？",
        "High",
    )
    assert "AED 已經到現場" in reply
    assert "打開 AED" in next_q
    assert "電擊" in next_q


def test_fire_followup_updates_active_smoke_state():
    messages = [
        ChatMessage(role="assistant", content="火勢或濃煙現在還在持續嗎？"),
        ChatMessage(role="user", content="還有濃煙，有人吸到煙不舒服"),
    ]
    ex = Extracted(category="火災", location="台北車站")

    reply, next_q = contextualize_reply_and_question(
        messages,
        ex,
        "我會協助你整理資訊。",
        "請補充現場狀況。",
        "High",
    )

    assert ex.danger_active is True
    assert ex.people_injured is True
    assert "火災現場有人受困或不適" in reply
    assert ex.dispatch_advice
    assert next_q


def test_violence_followup_updates_gone_state():
    messages = [
        ChatMessage(role="assistant", content="對方現在還在現場，或還在持續威脅嗎？"),
        ChatMessage(role="user", content="對方已經離開了"),
    ]
    ex = Extracted(category="暴力事件", weapon=False, people_injured=False)

    reply, next_q = contextualize_reply_and_question(
        messages,
        ex,
        "我會協助你整理資訊。",
        "請補充現場狀況。",
        "Medium",
    )

    assert ex.danger_active is False
    assert "已經離開或停止" in reply
    assert next_q


def test_traffic_followup_updates_injury_state():
    messages = [
        ChatMessage(role="assistant", content="現場有沒有人受傷或被困在車內？"),
        ChatMessage(role="user", content="有人受傷流血，需要救護車"),
    ]
    ex = Extracted(category="交通事故", location="忠孝東路路口")

    reply, next_q = contextualize_reply_and_question(
        messages,
        ex,
        "我會協助你整理資訊。",
        "請補充現場狀況。",
        "High",
    )

    assert ex.people_injured is True
    assert "事故現場有人受傷或受困" in reply
    assert ex.dispatch_advice
    assert next_q
