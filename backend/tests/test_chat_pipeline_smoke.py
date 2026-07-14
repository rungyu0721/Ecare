"""端對端煙霧測試：在沒有真實 Ollama/Neo4j 的情況下，用 mock LLM 回應驗證
process_chat_request() 完整跑過自然模型與 JSON 模型兩條路徑都不會出錯，
並確認 system prompt 有依模型類型正確傳遞（見 backend/services/llm.py 的
call_local_llm system 覆蓋修正）。

這裡不驗證「LLM 回覆品質」，只驗證管線串接與參數傳遞正確；
回覆品質仍需要接上真實模型實際測試。
"""
import json
from unittest.mock import patch

from backend.models import ChatMessage, LLMTextResponse
from backend.services.chat import process_chat_request


NATURAL_REPLY = "我在，先確認你們目前安全，你們是在合歡山步道迷路了嗎？請保留手機電力。"

JSON_REPLY = json.dumps(
    {
        "reply": "我在，先確認你們目前安全。",
        "risk_score": 0.85,
        "risk_level": "High",
        "should_escalate": True,
        "next_question": "你們同行幾個人？",
        "semantic": {
            "intent": "求助",
            "primary_need": "確認安全",
            "emotion": "worried",
            "reply_strategy": "先確認安全",
            "entities": {"location": None, "injured": None, "weapon": None, "danger_active": True},
        },
        "extracted": {
            "category": "山域水域救援",
            "location": None,
            "people_injured": None,
            "weapon": None,
            "danger_active": True,
            "reporter_role": None,
            "conscious": None,
            "breathing_difficulty": None,
            "fever": None,
            "symptom_summary": "疑似山域水域救援",
            "dispatch_advice": None,
            "description": None,
        },
    },
    ensure_ascii=False,
)


def test_natural_chat_model_path_runs_end_to_end_and_uses_explicit_system_prompt():
    messages = [ChatMessage(role="user", content="我們在合歡山步道迷路了，手機快沒電。")]

    with patch("backend.services.chat.llm_is_ready", return_value=True), \
         patch("backend.services.chat.LLM_MODEL_NAME", "ecare-v4:latest"), \
         patch("backend.services.chat.call_llm") as mock_call_llm:
        mock_call_llm.return_value = LLMTextResponse(text=NATURAL_REPLY)
        response = process_chat_request(messages)

    assert response.reply
    assert response.extracted.category == "山域水域救援"
    mock_call_llm.assert_called_once()
    _, kwargs = mock_call_llm.call_args
    assert kwargs.get("system"), "natural-chat call must send an explicit system message"
    assert "不要輸出 JSON" in kwargs["system"]


def test_json_chat_model_path_runs_end_to_end_without_natural_system_prompt():
    messages = [ChatMessage(role="user", content="我們在合歡山步道迷路了，手機快沒電。")]

    with patch("backend.services.chat.llm_is_ready", return_value=True), \
         patch("backend.services.chat.LLM_MODEL_NAME", "gemma-3-12b"), \
         patch("backend.services.chat.call_llm") as mock_call_llm, \
         patch("backend.services.chat.parse_llm_json_text", side_effect=json.loads):
        mock_call_llm.return_value = LLMTextResponse(text=JSON_REPLY)
        response = process_chat_request(messages)

    assert response.reply
    assert response.extracted.category == "山域水域救援"
    assert response.risk_level == "High"
    assert mock_call_llm.called
    _, kwargs = mock_call_llm.call_args
    assert kwargs.get("system") is None, "JSON-model call must not get the natural-chat system override"
