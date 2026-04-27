"""
/chat 路由：接收請求 → 呼叫服務管線 → 回傳回應。
"""

from fastapi import APIRouter, BackgroundTasks

from backend.db.neo4j_db import sync_chat_state_to_neo4j
from backend.models import ChatRequest, ChatResponse, latest_user_text
from backend.services.chat import process_chat_request

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    response = process_chat_request(
        req.messages, req.audio_context, req.session_id, req.user_context
    )
    background_tasks.add_task(
        sync_chat_state_to_neo4j,
        req.session_id,
        req.user_context,
        response.extracted,
        response.semantic,
        latest_user_text(req.messages),
    )
    return response
