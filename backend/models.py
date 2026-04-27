"""
所有 Pydantic 資料模型與共用型別定義。
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["user", "assistant"]


# ======================
# 對話模型
# ======================

class ChatMessage(BaseModel):
    role: Role
    content: str


class ChatUserContext(BaseModel):
    user_id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    audio_context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    user_context: Optional[ChatUserContext] = None


class Extracted(BaseModel):
    category: Optional[str] = None
    location: Optional[str] = None
    people_injured: Optional[bool] = None
    weapon: Optional[bool] = None
    danger_active: Optional[bool] = None
    reporter_role: Optional[str] = None
    conscious: Optional[bool] = None
    breathing_difficulty: Optional[bool] = None
    fever: Optional[bool] = None
    symptom_summary: Optional[str] = None
    dispatch_advice: Optional[str] = None
    description: Optional[str] = None


class SemanticEntities(BaseModel):
    location: Optional[str] = None
    injured: Optional[bool] = None
    weapon: Optional[bool] = None
    danger_active: Optional[bool] = None


class SemanticUnderstanding(BaseModel):
    intent: str = "未知"
    primary_need: str = "釐清狀況"
    emotion: str = "neutral"
    reply_strategy: str = "先確認事件重點"
    entities: SemanticEntities = SemanticEntities()


class DialogueState(BaseModel):
    incident_type: str = "待確認"
    risk_level: str = "Low"
    location_known: bool = False
    location_source: Optional[str] = None
    location_text: Optional[str] = None
    latest_user_intent: str = "未知"
    user_goal: str = "開始描述狀況"
    reporter_role: Optional[str] = None
    stage: str = "初步釐清"
    last_assistant_question: Optional[str] = None
    missing_slots: List[str] = Field(default_factory=list)
    summary: str = ""


class GraphQueryPlan(BaseModel):
    event_keyword: Optional[str] = None
    injury_keyword: str = "未知"
    location_keyword: Optional[str] = None
    emotion_keyword: Optional[str] = None
    query_goal: str = "event_knowledge"
    search_text: str = ""


class ChatResponse(BaseModel):
    reply: str
    risk_score: float
    risk_level: str
    should_escalate: bool
    next_question: Optional[str]
    extracted: Extracted
    semantic: SemanticUnderstanding


# ======================
# 通報紀錄模型
# ======================

class ReportCreate(BaseModel):
    title: str
    category: str
    location: str
    risk_level: str
    risk_score: float
    description: str


class ReportItem(BaseModel):
    id: str
    title: str
    category: str
    location: str
    status: str
    created_at: str
    risk_level: str
    risk_score: float
    description: str


# ======================
# 使用者模型
# ======================

class UserCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    emergency_name: Optional[str] = None
    emergency_phone: Optional[str] = None
    relationship: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class UserItem(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    emergency_name: Optional[str] = None
    emergency_phone: Optional[str] = None
    relationship: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


# ======================
# LLM 回應包裝
# ======================

class LLMTextResponse:
    def __init__(self, text: str):
        self.text = text


# ======================
# 工具函式
# ======================

def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def latest_user_text(messages: List[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content.strip()
    return ""
