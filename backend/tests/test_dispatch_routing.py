"""110/119 分流規則測試。"""

import pytest

from backend.models import ChatMessage, Extracted
from backend.services.chat import process_chat_request
from backend.services.dialogue import next_question
from backend.services.extraction.classify import get_dispatch_advice
from backend.services.extraction.entities import simple_extract


@pytest.mark.parametrize(
    ("category", "people_injured", "expected_terms"),
    [
        ("自殺危機", None, ["救護車", "警察"]),
        ("失蹤走失", None, ["警察", "119"]),
        ("受困救援", None, ["消防救援"]),
        ("天然災害", True, ["消防救災", "救護車"]),
        ("山域水域救援", None, ["消防救援"]),
    ],
)
def test_dispatch_advice_routes_emergency_categories(category, people_injured, expected_terms):
    advice = get_dispatch_advice(category, weapon=None, people_injured=people_injured)

    for term in expected_terms:
        assert term in advice


@pytest.mark.parametrize(
    ("text", "expected_category", "expected_terms"),
    [
        ("有人在頂樓說要跳樓", "自殺危機", ["119", "110"]),
        ("阿嬤在市場附近走失找不到人", "失蹤走失", ["110", "119"]),
        ("朋友在山區走失，手機快沒電也沒訊號", "山域水域救援", ["119"]),
        ("我們困在電梯裡門打不開", "受困救援", ["119"]),
        ("地震後大樓倒塌有人被壓住", "天然災害", ["119"]),
    ],
)
def test_simple_extract_routes_real_world_emergency_text(text, expected_category, expected_terms):
    extracted = simple_extract(text)

    assert extracted.category == expected_category
    assert extracted.dispatch_advice
    for term in expected_terms:
        assert term in extracted.dispatch_advice


@pytest.mark.parametrize(
    "text",
    [
        "我不知道怎麼辦",
        "好像有點不對勁",
        "我有點害怕",
        "可以幫我嗎",
        "有人怪怪的",
    ],
)
def test_ambiguous_intake_stays_pending_confirmation(text):
    extracted = simple_extract(text)

    assert extracted.category == "待確認"
    assert extracted.dispatch_advice == "建議派遣：待確認"


def test_pending_confirmation_asks_location_first():
    extracted = Extracted(category="待確認")

    assert next_question(extracted, "Low") == "請問事發地點在哪裡？"


def test_pending_confirmation_asks_incident_after_location():
    extracted = Extracted(category="待確認", location="台北車站")

    assert "請直接告訴我現在發生什麼事" in next_question(extracted, "Low")


@pytest.mark.parametrize(
    ("text", "expected_category", "expected_level", "expected_terms", "reply_terms"),
    [
        ("有人在頂樓說要跳樓", "自殺危機", "High", ["119", "110"], ["我在", "安全"]),
        ("朋友在山區走失，手機快沒電也沒訊號", "山域水域救援", "High", ["119"], ["救援"]),
        ("地震後大樓倒塌有人被壓住", "天然災害", "High", ["119"], ["受困", "安全"]),
    ],
)
def test_process_chat_request_fallback_routes_high_risk_cases(
    text,
    expected_category,
    expected_level,
    expected_terms,
    reply_terms,
):
    response = process_chat_request([ChatMessage(role="user", content=text)])

    assert response.extracted.category == expected_category
    assert response.risk_level == expected_level
    assert response.should_escalate is True
    for term in reply_terms:
        assert term in response.reply
    assert response.extracted.dispatch_advice
    for term in expected_terms:
        assert term in response.extracted.dispatch_advice


def test_process_chat_request_pending_confirmation_keeps_location_question():
    response = process_chat_request([ChatMessage(role="user", content="我不知道怎麼辦")])

    assert response.extracted.category == "待確認"
    assert response.risk_level == "Low"
    assert response.should_escalate is False
    assert response.extracted.location is None
    assert response.extracted.dispatch_advice == "建議派遣：待確認"
    assert "我在" in response.reply
    assert response.next_question == "請問事發地點在哪裡？"


def test_trapped_rescue_with_client_location_does_not_repeat_address_request():
    audio_context = {
        "client_location": {
            "latitude": 25.0,
            "longitude": 121.5,
            "accuracy": 20,
            "address": "台北市信義區市府路1號",
            "display_text": "台北市信義區市府路1號",
        }
    }
    messages = [
        ChatMessage(role="assistant", content="您好，我是 E-CARE 救援助理。"),
        ChatMessage(
            role="user",
            content="我們困在電梯裡，門打不開，有一位老人覺得喘不過氣。",
        ),
    ]

    first_response = process_chat_request(messages, audio_context=audio_context)

    assert first_response.extracted.category == "受困救援"
    assert first_response.extracted.location == "台北市信義區市府路1號"
    assert first_response.next_question
    assert "地址" not in first_response.next_question
    assert "樓層" in first_response.next_question
    assert "電梯編號" in first_response.next_question

    messages.extend(
        [
            ChatMessage(
                role="assistant",
                content=f"{first_response.reply}\n\n{first_response.next_question}",
            ),
            ChatMessage(role="user", content="仍受困"),
        ]
    )

    followup_response = process_chat_request(messages, audio_context=audio_context)

    assert followup_response.extracted.category == "受困救援"
    assert followup_response.extracted.location == "台北市信義區市府路1號"
    assert followup_response.next_question
    assert "地址" not in followup_response.next_question
    assert "樓層" in followup_response.next_question
    assert "電梯編號" in followup_response.next_question


def test_trapped_rescue_followup_acknowledges_still_trapped_and_discomfort():
    audio_context = {
        "client_location": {
            "latitude": 25.0,
            "longitude": 121.5,
            "accuracy": 20,
            "address": "台北市信義區市府路1號",
            "display_text": "台北市信義區市府路1號",
        }
    }
    messages = [
        ChatMessage(role="user", content="我們困在電梯裡，門打不開。"),
    ]

    first_response = process_chat_request(messages, audio_context=audio_context)
    messages.extend(
        [
            ChatMessage(
                role="assistant",
                content=f"{first_response.reply}\n\n{first_response.next_question}",
            ),
            ChatMessage(role="user", content="仍受困，有人不舒服"),
        ]
    )

    followup_response = process_chat_request(messages, audio_context=audio_context)

    assert followup_response.extracted.category == "受困救援"
    assert followup_response.extracted.danger_active is True
    assert followup_response.extracted.people_injured is True
    assert "仍受困" in followup_response.reply
    assert "有人不舒服" in followup_response.reply
    assert "樓層" in followup_response.next_question
    assert "電梯編號" in followup_response.next_question
