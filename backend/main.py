from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import List, Literal, Optional, Dict, Any
import re
import whisper
import tempfile
import subprocess
import os
import time
import random
import json
import urllib.error
import urllib.request
import psycopg2
from neo4j import GraphDatabase
from psycopg2.extras import RealDictCursor
import numpy as np
import librosa
import joblib

# LLM providers
from google import genai

app = FastAPI()

ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://10.0.2.2",
    "http://10.0.2.2:8000",
    "http://192.168.50.254",
    "http://192.168.50.254:5500",
    "capacitor://localhost",
    "ionic://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Role = Literal["user", "assistant"]

# ======================
# 資料模型
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
# 通報紀錄
# ======================

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "ecare_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
DB_AVAILABLE = False

GRAPH_EMOTION_MAP = {
    "panic": "慌張",
    "fearful": "害怕",
    "sad": "難過",
    "angry": "生氣",
    "neutral": "平穩",
    "unknown": None,
}

def get_neo4j():
    if not NEO4J_URI or not NEO4J_PASSWORD:
        raise RuntimeError("NEO4J_URI 或 NEO4J_PASSWORD 尚未設定")
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def check_neo4j():
    driver = None
    try:
        driver = get_neo4j()
        driver.verify_connectivity()
        with driver.session() as session:
            session.run("RETURN 1 AS ok").single()
        print(f"✅ Neo4j 已連線：{NEO4J_URI}")
    except Exception as e:
        print(f"⚠️ Neo4j 連線失敗：{e}")
    finally:
        if driver is not None:
            driver.close()


def query_neo4j_by_keyword(text: str) -> dict:
    """用關鍵字查詢 Neo4j，取得事件類型、風險等級、派遣建議"""
    if not text.strip():
        return {}

    driver = None
    try:
        driver = get_neo4j()
        with driver.session() as session:
            result = session.run("""
                MATCH (k:Keyword)<-[:HAS_KEYWORD]-(e:Event)-[:EVENT_HAS_RISK]->(r:RiskLevel)
                WHERE $text CONTAINS k.word
                WITH DISTINCT e, r
                ORDER BY coalesce(r.score_min, 0) DESC
                LIMIT 1
                OPTIONAL MATCH (e)-[:NEEDS_ACTION]->(a:Action)
                RETURN e.code AS code, e.name AS name,
                       r.level AS risk_level,
                       collect(DISTINCT a.detail) AS actions
            """, text=text)
            record = result.single()
            if record:
                return {
                    "event_code": record["code"],
                    "event_name": record["name"],
                    "risk_level": record["risk_level"],
                    "actions":    record["actions"],
                }
    except Exception as e:
        print(f"⚠️ Neo4j 查詢失敗：{e}")
    finally:
        if driver is not None:
            driver.close()
    return {}


def normalize_graph_emotion(emotion: Optional[str]) -> Optional[str]:
    if not emotion:
        return None

    normalized = GRAPH_EMOTION_MAP.get(emotion.strip().lower())
    if normalized:
        return normalized

    cleaned = emotion.strip()
    return cleaned or None


def build_graph_user_identity(
    session_id: Optional[str],
    user_context: Optional[ChatUserContext],
) -> Optional[Dict[str, Optional[str]]]:
    if user_context and user_context.user_id is not None:
        node_id = f"user:{user_context.user_id}"
    elif user_context and user_context.phone:
        digits = re.sub(r"\D+", "", user_context.phone)
        node_id = f"phone:{digits}" if digits else None
    elif session_id:
        node_id = f"session:{session_id.strip()}"
    else:
        node_id = None

    if not node_id:
        return None

    name = user_context.name.strip() if user_context and user_context.name else None
    phone = user_context.phone.strip() if user_context and user_context.phone else None

    return {
        "id": node_id,
        "name": name or None,
        "phone": phone or None,
    }


def latest_user_text(messages: List[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def build_fallback_graph_query_plan(
    messages: List[ChatMessage],
    conversation_state: Extracted,
    audio_context: Optional[Dict[str, Any]] = None,
) -> GraphQueryPlan:
    latest_text = latest_user_text(messages)
    location_keyword = (
        conversation_state.location
        or get_client_location_text(audio_context)
    )
    emotion_keyword = normalize_graph_emotion((audio_context or {}).get("emotion"))

    injury_keyword = "未知"
    if conversation_state.people_injured is True:
        injury_keyword = "有傷亡"
    elif conversation_state.people_injured is False:
        injury_keyword = "無明確傷亡"

    return GraphQueryPlan(
        event_keyword=normalize_category_name(conversation_state.category),
        injury_keyword=injury_keyword,
        location_keyword=location_keyword,
        emotion_keyword=emotion_keyword,
        query_goal="event_knowledge",
        search_text=latest_text,
    )


def graph_reasoning_from_context(
    messages: List[ChatMessage],
    conversation_state: Extracted,
    audio_context: Optional[Dict[str, Any]] = None,
) -> GraphQueryPlan:
    fallback = build_fallback_graph_query_plan(messages, conversation_state, audio_context)

    if not llm_is_ready():
        return fallback

    latest_text = latest_user_text(messages)
    if not latest_text:
        return fallback

    safe_audio_context = {
        "emotion": (audio_context or {}).get("emotion"),
        "emotion_score": (audio_context or {}).get("emotion_score"),
        "risk_level": (audio_context or {}).get("risk_level"),
        "risk_score": (audio_context or {}).get("risk_score"),
        "client_location": get_client_location_text(audio_context),
    }

    known_context = {
        "category": conversation_state.category,
        "location": conversation_state.location,
        "people_injured": conversation_state.people_injured,
        "weapon": conversation_state.weapon,
        "danger_active": conversation_state.danger_active,
    }

    prompt = f"""
你是 Neo4j 圖譜查詢規劃器。你的工作是先理解使用者最新一句話與已知上下文，再輸出供系統生成 Cypher 的 JSON。

規則：
- 只能輸出 JSON，不要加註解或 markdown
- event_keyword 只能是：火災、可疑人士、噪音、醫療急症、暴力事件、交通事故、待確認、null
- injury_keyword 只能是：有傷亡、無明確傷亡、未知
- location_keyword 只有在使用者明確提到地址、路名、地標時才填，否則填 null
- emotion_keyword 請用簡短中文，例如：害怕、緊張、慌張、難過、生氣、平穩；不確定可填 null
- query_goal 只能是：event_knowledge、location_context、user_context
- search_text 要保留最能查圖的核心描述，盡量短
- 如果使用者是在補充症狀或事件，不要把那句話當成地點

輸出格式：
{{
  "event_keyword": "string|null",
  "injury_keyword": "string",
  "location_keyword": "string|null",
  "emotion_keyword": "string|null",
  "query_goal": "string",
  "search_text": "string"
}}

最新使用者描述：
{latest_text}

已知案件資訊：
{json.dumps(known_context, ensure_ascii=False)}

語音 / 裝置脈絡：
{json.dumps(safe_audio_context, ensure_ascii=False)}
"""

    try:
        resp = call_llm(prompt)
        result_text = (resp.text or "").strip()
        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "").replace("```", "").strip()

        data = json.loads(result_text)
        event_keyword = normalize_category_name(data.get("event_keyword"))
        location_keyword = normalize_location_candidate(data.get("location_keyword") or "")
        emotion_keyword = normalize_graph_emotion(data.get("emotion_keyword"))
        injury_keyword = data.get("injury_keyword") or fallback.injury_keyword
        query_goal = data.get("query_goal") or "event_knowledge"
        search_text = (data.get("search_text") or latest_text).strip()

        if event_keyword == "待確認" and fallback.event_keyword and fallback.event_keyword != "待確認":
            event_keyword = fallback.event_keyword
        if not location_keyword and fallback.location_keyword:
            location_keyword = fallback.location_keyword
        if not emotion_keyword and fallback.emotion_keyword:
            emotion_keyword = fallback.emotion_keyword
        if injury_keyword not in ["有傷亡", "無明確傷亡", "未知"]:
            injury_keyword = fallback.injury_keyword
        if query_goal not in ["event_knowledge", "location_context", "user_context"]:
            query_goal = "event_knowledge"

        return GraphQueryPlan(
            event_keyword=event_keyword,
            injury_keyword=injury_keyword,
            location_keyword=location_keyword,
            emotion_keyword=emotion_keyword,
            query_goal=query_goal,
            search_text=search_text,
        )
    except Exception:
        return fallback


def build_knowledge_graph_cypher(plan: GraphQueryPlan) -> tuple[str, Dict[str, Any]]:
    cypher = """
    MATCH (e:Event)
    OPTIONAL MATCH (e)-[:HAS_KEYWORD]->(k:Keyword)
    OPTIONAL MATCH (e)-[:EVENT_HAS_RISK]->(r:RiskLevel)
    OPTIONAL MATCH (e)-[:NEEDS_ACTION]->(a:Action)
    WITH e,
         collect(DISTINCT k.word) AS keywords,
         r,
         collect(DISTINCT a.detail) AS actions
    WHERE
      ($event_keyword IS NULL OR e.name = $event_keyword OR e.code = $event_keyword)
      AND (
        $search_text = ''
        OR size([kw IN keywords WHERE kw IS NOT NULL AND $search_text CONTAINS kw]) > 0
        OR $event_keyword IS NOT NULL
      )
    WITH e, keywords, r, actions,
         CASE
           WHEN $event_keyword IS NOT NULL AND (e.name = $event_keyword OR e.code = $event_keyword) THEN 3
           ELSE 0
         END
         +
         CASE
           WHEN $search_text <> '' AND size([kw IN keywords WHERE kw IS NOT NULL AND $search_text CONTAINS kw]) > 0 THEN 1
           ELSE 0
         END AS match_score
    ORDER BY match_score DESC, coalesce(r.score_min, 0) DESC
    LIMIT 1
    RETURN e.code AS code,
           e.name AS name,
           keywords,
           r.level AS risk_level,
           actions,
           match_score
    """

    params = {
        "event_keyword": plan.event_keyword,
        "search_text": (plan.search_text or "").strip(),
    }
    return cypher, params


def query_neo4j_by_plan(plan: GraphQueryPlan) -> Dict[str, Any]:
    if not ((plan.event_keyword and plan.event_keyword != "待確認") or (plan.search_text or "").strip()):
        return {}

    driver = None
    try:
        driver = get_neo4j()
        cypher, params = build_knowledge_graph_cypher(plan)
        with driver.session() as session:
            record = session.run(cypher, **params).single()
        if not record:
            return {}

        return {
            "cypher": cypher.strip(),
            "params": params,
            "event_code": record.get("code"),
            "event_name": record.get("name"),
            "risk_level": record.get("risk_level"),
            "actions": record.get("actions") or [],
            "keywords": record.get("keywords") or [],
            "match_score": record.get("match_score") or 0,
        }
    except Exception as e:
        print(f"⚠️ Neo4j 圖譜查詢失敗：{e}")
        return {}
    finally:
        if driver is not None:
            driver.close()


def query_neo4j_user_context(user_identity: Optional[Dict[str, Optional[str]]]) -> Dict[str, Any]:
    if not user_identity:
        return {}

    driver = None
    try:
        driver = get_neo4j()
        with driver.session() as session:
            record = session.run(
                """
                OPTIONAL MATCH (u:User {id: $user_id})
                OPTIONAL MATCH (u)-[:DESCRIBED]->(i:IncidentEvent)-[:REFERS_TO]->(e:Event)
                OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location)
                OPTIONAL MATCH (u)-[:HAS_EMOTION]->(m:Emotion)
                RETURN
                  [name IN collect(DISTINCT e.name) WHERE name IS NOT NULL][0..5] AS recent_events,
                  [loc IN collect(DISTINCT l.name) WHERE loc IS NOT NULL][0..5] AS recent_locations,
                  [emo IN collect(DISTINCT m.name) WHERE emo IS NOT NULL][0..5] AS recent_emotions
                """,
                user_id=user_identity["id"],
            ).single()
        if not record:
            return {}

        return {
            "recent_events": record.get("recent_events") or [],
            "recent_locations": record.get("recent_locations") or [],
            "recent_emotions": record.get("recent_emotions") or [],
        }
    except Exception as e:
        print(f"⚠️ Neo4j 使用者脈絡查詢失敗：{e}")
        return {}
    finally:
        if driver is not None:
            driver.close()


def build_neo4j_hint(
    plan: GraphQueryPlan,
    graph_knowledge: Dict[str, Any],
    user_graph_context: Dict[str, Any],
) -> str:
    lines: List[str] = []

    if graph_knowledge:
        lines.append("知識圖譜查詢結果：")
        lines.append(f"- Cypher：{graph_knowledge.get('cypher', '')}")
        lines.append(f"- 事件類型：{graph_knowledge.get('event_name', '未知')}")
        lines.append(f"- 風險等級：{graph_knowledge.get('risk_level', '未知')}")
        actions = graph_knowledge.get("actions") or []
        if actions:
            lines.append(f"- 建議派遣 / 處置：{', '.join(actions)}")
        keywords = graph_knowledge.get("keywords") or []
        if keywords:
            lines.append(f"- 命中關鍵字：{', '.join(keywords)}")

    if user_graph_context:
        events = user_graph_context.get("recent_events") or []
        locations = user_graph_context.get("recent_locations") or []
        emotions = user_graph_context.get("recent_emotions") or []
        if events or locations or emotions:
            lines.append("使用者圖譜脈絡：")
            if events:
                lines.append(f"- 近期描述事件：{', '.join(events)}")
            if locations:
                lines.append(f"- 近期提過地點：{', '.join(locations)}")
            if emotions:
                lines.append(f"- 近期情緒狀態：{', '.join(emotions)}")

    if not lines:
        return ""

    if plan.location_keyword:
        lines.append(f"- 本輪判定地點關鍵字：{plan.location_keyword}")
    if plan.emotion_keyword:
        lines.append(f"- 本輪判定情緒關鍵字：{plan.emotion_keyword}")
    if plan.injury_keyword:
        lines.append(f"- 本輪判定傷亡關鍵字：{plan.injury_keyword}")

    return "\n".join(lines)


def sync_chat_state_to_neo4j(
    session_id: Optional[str],
    user_context: Optional[ChatUserContext],
    ex: Extracted,
    semantic: SemanticUnderstanding,
    latest_text: str,
):
    user_identity = build_graph_user_identity(session_id, user_context)
    if not user_identity:
        return

    event_name = normalize_category_name(ex.category)
    location_name = normalize_location_candidate(ex.location or "")
    emotion_name = normalize_graph_emotion(semantic.emotion)

    driver = None
    try:
        driver = get_neo4j()
        incident_id = f"{user_identity['id']}:{int(time.time() * 1000)}"
        now_iso = datetime.now().isoformat(timespec="seconds")
        with driver.session() as session:
            session.run(
                """
                MERGE (u:User {id: $user_id})
                SET u.name = coalesce($user_name, u.name),
                    u.phone = coalesce($user_phone, u.phone),
                    u.updated_at = $updated_at

                MERGE (i:IncidentEvent {id: $incident_id})
                SET i.latest_text = $latest_text,
                    i.updated_at = $updated_at,
                    i.people_injured = $people_injured,
                    i.weapon = $weapon,
                    i.danger_active = $danger_active,
                    i.reporter_role = $reporter_role,
                    i.conscious = $conscious,
                    i.breathing_difficulty = $breathing_difficulty,
                    i.fever = $fever,
                    i.symptom_summary = $symptom_summary

                MERGE (u)-[:DESCRIBED]->(i)

                FOREACH (_ IN CASE WHEN $event_name IS NULL OR $event_name = '待確認' THEN [] ELSE [1] END |
                    MERGE (e:Event {name: $event_name})
                    MERGE (i)-[:REFERS_TO]->(e)
                )

                FOREACH (_ IN CASE WHEN $location_name IS NULL THEN [] ELSE [1] END |
                    MERGE (l:Location {name: $location_name})
                    MERGE (i)-[:OCCURRED_AT]->(l)
                )

                FOREACH (_ IN CASE WHEN $emotion_name IS NULL THEN [] ELSE [1] END |
                    MERGE (m:Emotion {name: $emotion_name})
                    MERGE (u)-[:HAS_EMOTION]->(m)
                )
                """,
                user_id=user_identity["id"],
                user_name=user_identity["name"],
                user_phone=user_identity["phone"],
                incident_id=incident_id,
                latest_text=latest_text.strip(),
                updated_at=now_iso,
                event_name=event_name,
                location_name=location_name,
                emotion_name=emotion_name,
                people_injured=ex.people_injured,
                weapon=ex.weapon,
                danger_active=ex.danger_active,
                reporter_role=ex.reporter_role,
                conscious=ex.conscious,
                breathing_difficulty=ex.breathing_difficulty,
                fever=ex.fever,
                symptom_summary=ex.symptom_summary,
            )
    except Exception as e:
        print(f"⚠️ Neo4j 對話脈絡同步失敗：{e}")
    finally:
        if driver is not None:
            driver.close()

def get_db():
    return psycopg2.connect(**DB_CONFIG)


def describe_db_connection(conn) -> str:
    server_addr = None
    server_port = None
    database_name = DB_CONFIG["database"]
    current_user = DB_CONFIG["user"]

    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                inet_server_addr()::text AS server_addr,
                inet_server_port() AS server_port,
                current_database() AS database_name,
                current_user AS current_user
        """)
        row = cur.fetchone() or {}
        server_addr = row.get("server_addr") or server_addr
        server_port = row.get("server_port") or server_port
        database_name = row.get("database_name") or database_name
        current_user = row.get("current_user") or current_user
    except Exception:
        pass
    finally:
        if cur is not None:
            cur.close()

    return (
        f"host={DB_CONFIG['host']} "
        f"port={server_port or DB_CONFIG['port']} "
        f"db={database_name} "
        f"user={current_user} "
        f"server_addr={server_addr or DB_CONFIG['host']}"
    )


def init_db():
    global DB_AVAILABLE
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_records (
                id          VARCHAR(20) PRIMARY KEY,
                title       VARCHAR(200),
                category    VARCHAR(100),
                location    TEXT,
                status      VARCHAR(50) DEFAULT '處理中',
                created_at  VARCHAR(50),
                risk_level  VARCHAR(20),
                risk_score  FLOAT,
                description TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ecare_user (
                id              SERIAL PRIMARY KEY,
                name            VARCHAR(100) NOT NULL,
                phone           VARCHAR(30),
                gender          VARCHAR(20),
                age             INTEGER,
                emergency_name  VARCHAR(100),
                emergency_phone VARCHAR(30),
                relationship    VARCHAR(50),
                address         TEXT,
                notes           TEXT,
                created_at      VARCHAR(50) DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY/MM/DD HH24:MI')
            );
        """)
        conn.commit()
        DB_AVAILABLE = True
        print(f"PostgreSQL 已連線：{describe_db_connection(conn)}")
    except Exception as e:
        DB_AVAILABLE = False
        print(f"⚠️ PostgreSQL 連線失敗，/reports 將暫時不可用：{e}")
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def ensure_db_available():
    if not DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="資料庫目前不可用，請稍後再試")


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

class UserCreate(BaseModel):
    name:            str
    phone:           Optional[str] = None
    gender:          Optional[str] = None
    age:             Optional[int] = None
    emergency_name:  Optional[str] = None
    emergency_phone: Optional[str] = None
    relationship:    Optional[str] = None
    address:         Optional[str] = None
    notes:           Optional[str] = None

class UserItem(BaseModel):
    id:              int
    name:            str
    phone:           Optional[str] = None
    gender:          Optional[str] = None
    age:             Optional[int] = None
    emergency_name:  Optional[str] = None
    emergency_phone: Optional[str] = None
    relationship:    Optional[str] = None
    address:         Optional[str] = None
    notes:           Optional[str] = None
    created_at:      Optional[str] = None


def build_user_item(row: Dict[str, Any]) -> UserItem:
    data = dict(row)
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        data["created_at"] = created_at.isoformat(sep=" ", timespec="seconds")
    elif created_at is not None:
        data["created_at"] = str(created_at)
    return UserItem(**data)


def find_existing_user_id(cur, payload: "UserCreate") -> Optional[int]:
    name = payload.name.strip()
    phone = (payload.phone or "").strip()
    if not name or not phone:
        return None

    cur.execute(
        """
        SELECT id
        FROM ecare_user
        WHERE name = %s AND phone = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (name, phone),
    )
    row = cur.fetchone()
    if not row:
        return None
    return row["id"]

def now_str():
    return time.strftime("%Y/%m/%d %H:%M", time.localtime())


def make_id(prefix="A"):
    return f"{prefix}{random.randint(100, 999)}"


# ======================
# 模型初始化
# ======================

WHISPER_MODEL = None
GEMINI_CLIENT = None
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
LLM_MODEL_NAME = os.getenv(
    "LLM_MODEL",
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
)
GEMMA_BASE_URL = os.getenv("GEMMA_BASE_URL", "").strip()
GEMMA_API_KEY = os.getenv("GEMMA_API_KEY", "").strip()
GEMMA_CHAT_PATH = os.getenv("GEMMA_CHAT_PATH", "").strip()
EMOTION_MODEL = None


class LLMTextResponse:
    def __init__(self, text: str):
        self.text = text


def llm_is_ready() -> bool:
    if LLM_PROVIDER == "gemini":
        return GEMINI_CLIENT is not None
    if LLM_PROVIDER == "gemma":
        return bool(GEMMA_BASE_URL and LLM_MODEL_NAME)
    return False

@app.on_event("startup")
def load_models():
    global WHISPER_MODEL, GEMINI_CLIENT, EMOTION_MODEL

    if WHISPER_MODEL is None:
        WHISPER_MODEL = whisper.load_model("base")

    if LLM_PROVIDER == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("google_api_key")
        if api_key:
            GEMINI_CLIENT = genai.Client(api_key=api_key)
            print(f"✅ LLM 已初始化：Gemini ({LLM_MODEL_NAME})")
        else:
            print("⚠️ 找不到 GOOGLE_API_KEY，/chat 將使用 fallback")
    elif LLM_PROVIDER == "gemma":
        if GEMMA_BASE_URL and LLM_MODEL_NAME:
            print(f"✅ LLM 已設定：Gemma ({LLM_MODEL_NAME}) @ {GEMMA_BASE_URL}")
        else:
            print("⚠️ Gemma provider 未完整設定，/chat 將使用 fallback")
    else:
        print(f"⚠️ 不支援的 LLM_PROVIDER={LLM_PROVIDER}，/chat 將使用 fallback")

    try:
        EMOTION_MODEL = joblib.load("backend/emotion_model.pkl")
        print("✅ Emotion model 已載入")
    except Exception as e:
        EMOTION_MODEL = None
        print(f"⚠️ Emotion model 載入失敗：{e}")
    check_neo4j()


if os.getenv("ECARE_SKIP_INIT_DB", "0") != "1":
    init_db()

def call_gemini(contents: str):
    if GEMINI_CLIENT is None:
        raise RuntimeError("Gemini client not ready")

    fallback_models = []
    for model_name in [
        LLM_MODEL_NAME,
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    ]:
        if model_name and model_name not in fallback_models:
            fallback_models.append(model_name)

    last_error = None
    for model_name in fallback_models:
        try:
            return GEMINI_CLIENT.models.generate_content(
                model=model_name,
                contents=contents
            )
        except Exception as exc:
            last_error = exc
            print(f"Gemini model failed: {model_name} -> {exc}")

    raise last_error if last_error else RuntimeError("Gemini generate_content failed")


def call_gemma(contents: str):
    if not GEMMA_BASE_URL or not LLM_MODEL_NAME:
        raise RuntimeError("Gemma provider not configured")

    base_url = GEMMA_BASE_URL.rstrip("/")
    if GEMMA_CHAT_PATH:
        path = GEMMA_CHAT_PATH if GEMMA_CHAT_PATH.startswith("/") else f"/{GEMMA_CHAT_PATH}"
    elif base_url.endswith("/v1"):
        path = "/chat/completions"
    else:
        path = "/v1/chat/completions"

    endpoint = f"{base_url}{path}"
    payload = {
        "model": LLM_MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": contents,
            }
        ],
        "temperature": 0.3,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **(
                {"Authorization": f"Bearer {GEMMA_API_KEY}"}
                if GEMMA_API_KEY
                else {}
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemma HTTP error: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemma connection failed: {exc}") from exc

    try:
        text = body["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(
                part.get("text", "")
                for part in text
                if isinstance(part, dict)
            )
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Gemma response format not recognized: {body}") from exc

    if not isinstance(text, str):
        raise RuntimeError(f"Gemma content format not recognized: {body}")

    return LLMTextResponse(text=text)


def call_llm(contents: str):
    if LLM_PROVIDER == "gemini":
        return call_gemini(contents)
    if LLM_PROVIDER == "gemma":
        return call_gemma(contents)
    raise RuntimeError(f"Unsupported LLM provider: {LLM_PROVIDER}")

def extract_emotion_features(wav_path: str) -> np.ndarray:
    y, sr = librosa.load(wav_path, sr=16000, mono=True)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_delta = librosa.feature.delta(mfcc)
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=40)
    zcr = librosa.feature.zero_crossing_rate(y)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)

    feats = np.concatenate([
        np.mean(mfcc, axis=1),
        np.std(mfcc, axis=1),
        np.mean(mfcc_delta, axis=1),
        np.std(mfcc_delta, axis=1),
        np.mean(mel, axis=1),
        np.std(mel, axis=1),
        [np.mean(zcr), np.std(zcr)],
        [np.mean(centroid), np.std(centroid)],
        [np.mean(rms), np.std(rms)],
    ])

    return feats.reshape(1, -1).astype(np.float32)


def predict_emotion_from_wav(wav_path: str):
    global EMOTION_MODEL

    if EMOTION_MODEL is None:
        return {
            "emotion": "unknown",
            "emotion_score": 0.0
        }

    feats = extract_emotion_features(wav_path)

    pred = EMOTION_MODEL.predict(feats)[0]

    try:
        proba = EMOTION_MODEL.predict_proba(feats)[0]
        score = float(np.max(proba))
    except Exception:
        score = 0.60

    # fearful 分數高時，升級成 panic 比較符合你的專題情境
    if pred == "fearful" and score >= 0.75:
        final_emotion = "panic"
    else:
        final_emotion = pred

    return {
        "emotion": final_emotion,
        "emotion_score": round(score, 2)
    }


def build_audio_analysis_result(transcript: str, emotion: str, emotion_score: float):
    score, level = simple_risk(transcript)
    ex = simple_extract(transcript)

    if emotion in ["panic", "fearful"]:
        score = min(1.0, score + 0.12)
    elif emotion == "sad":
        score = min(1.0, score + 0.05)
    elif emotion == "angry":
        score = min(1.0, score + 0.08)

    if score > 0.8:
        level = "High"
    elif score > 0.5:
        level = "Medium"
    else:
        level = "Low"

    return {
        "situation": ex.category or "待確認",
        "risk_score": round(score, 2),
        "risk_level": level,
        "extracted": ex.dict()
    }
# ======================
# Whisper 修正詞典
# ======================

COMMON_FIXES = {
    "婚倒": "昏倒",
    "師火": "失火",
    "著伙": "著火",
    "打加": "打架",
    "火在燒起來了": "火災發生了",
    "可已人士": "可疑人士",
    "流學": "流血",
}


def fix_transcript(text: str) -> str:
    text = text.strip()
    for wrong, correct in COMMON_FIXES.items():
        text = text.replace(wrong, correct)
    return text


# ======================
# 事件分類 / 派遣建議
# ======================

def get_dispatch_advice(category: Optional[str], weapon: Optional[bool], people_injured: Optional[bool]) -> str:
    if category == "火災":
        if people_injured:
            return "建議派遣：消防車 + 救護車"
        return "建議派遣：消防車"

    if category == "醫療急症":
        return "建議派遣：救護車"

    if category == "暴力事件":
        if weapon:
            return "建議派遣：警察，必要時通知救護車待命"
        return "建議派遣：警察"

    if category == "交通事故":
        if people_injured:
            return "建議派遣：警察 + 救護車"
        return "建議派遣：警察"

    if category == "可疑人士":
        return "建議派遣：警察"

    if category == "噪音":
        return "建議派遣：警察或相關單位查看"

    return "建議派遣：待確認"


# ======================
# 簡易事件抽取
# ======================

VAGUE_LOCATION_PHRASES = {
    "我旁邊",
    "旁邊",
    "這裡",
    "那裡",
    "附近",
    "現場",
    "我這裡",
    "我這邊",
    "這邊",
    "那邊",
    "身邊",
}

LOCATION_HINT_TOKENS = {
    "縣",
    "市",
    "鄉",
    "鎮",
    "區",
    "村",
    "里",
    "路",
    "街",
    "段",
    "巷",
    "弄",
    "號",
    "樓",
}

LANDMARK_HINT_TOKENS = {
    "門口",
    "樓下",
    "樓上",
    "家裡",
    "家中",
    "住家",
    "公司",
    "學校",
    "校門口",
    "教室",
    "宿舍",
    "公園",
    "車站",
    "捷運站",
    "超商",
    "便利商店",
    "醫院",
    "診所",
    "市場",
    "巷口",
    "路口",
}

LOCATION_QUESTION_KEYWORDS = ["地點", "地址", "哪裡", "位置", "在哪裡", "人在哪"]
INJURY_QUESTION_KEYWORDS = ["受傷", "失去意識", "送醫", "醫療協助", "呼吸困難", "昏倒", "意識清楚"]
CATEGORY_QUESTION_KEYWORDS = ["火災", "可疑人士", "噪音", "醫療急症", "暴力事件", "交通事故", "發生了什麼事"]
WEAPON_QUESTION_KEYWORDS = ["武器", "持刀", "棍棒", "槍"]
DANGER_QUESTION_KEYWORDS = ["還在持續", "還在現場", "是否安全", "危險還在", "還在擴大"]

INCIDENT_DESCRIPTION_KEYWORDS = {
    "發燒",
    "昏倒",
    "流血",
    "受傷",
    "不舒服",
    "胸痛",
    "呼吸困難",
    "喘不過氣",
    "抽搐",
    "嘔吐",
    "火災",
    "失火",
    "著火",
    "起火",
    "冒煙",
    "打架",
    "被打",
    "威脅",
    "可疑",
    "跟蹤",
    "怪人",
    "闖入",
    "車禍",
    "撞車",
    "翻車",
    "刀",
    "槍",
}

ACUTE_MEDICAL_HIGH_KEYWORDS = {
    "呼吸困難",
    "喘不過氣",
    "沒呼吸",
    "胸痛",
    "抽搐",
    "昏倒",
    "失去意識",
    "嘴唇發紫",
}

MEDICAL_URGENCY_KEYWORDS = ACUTE_MEDICAL_HIGH_KEYWORDS | {
    "發燒",
    "頭暈",
    "嘔吐",
    "不舒服",
    "咳不停",
}

CATEGORY_NORMALIZATION_MAP = {
    "火災": "火災",
    "可疑人士": "可疑人士",
    "噪音": "噪音",
    "醫療急症": "醫療急症",
    "暴力事件": "暴力事件",
    "交通事故": "交通事故",
    "待確認": "待確認",
    "暴力傷害": "暴力事件",
    "持械威脅": "暴力事件",
    "車禍傷病": "交通事故",
    "自殺風險": "醫療急症",
    "其他危急事件": "待確認",
    "未知": "待確認",
}


def contains_any_keyword(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def normalize_category_name(category: Optional[str]) -> Optional[str]:
    if category is None:
        return None
    return CATEGORY_NORMALIZATION_MAP.get(category, category)


def normalize_location_candidate(text: str) -> Optional[str]:
    candidate = text.strip(" ：:，,。.？?！!；;、\n\t")
    if not candidate:
        return None

    for prefix in ["我在", "目前在", "現在在", "人在", "在", "於"]:
        if candidate.startswith(prefix) and len(candidate) > len(prefix):
            candidate = candidate[len(prefix):].strip(" ：:，,。.？?！!；;、\n\t")
            break

    if not candidate:
        return None

    if candidate in VAGUE_LOCATION_PHRASES:
        return None

    if any(
        candidate.startswith(prefix)
        for prefix in ["我旁邊", "旁邊", "附近", "這裡", "那裡", "現場"]
    ):
        return None

    return candidate


def location_quality_score(text: Optional[str]) -> int:
    if not text:
        return -1

    candidate = text.strip()
    if not candidate:
        return -1

    score = min(len(candidate), 12)

    if any(token in candidate for token in ["縣", "市", "鄉", "鎮", "區", "村", "里", "路", "街", "段", "巷", "弄", "號", "樓"]):
        score += 8

    if "+/-" in candidate and "," in candidate:
        score += 10

    if candidate.isdigit():
        score -= 12
    elif len(candidate) <= 3 and any(char.isdigit() for char in candidate):
        score -= 8

    return score


def has_strong_location_signal(text: str) -> bool:
    candidate = normalize_location_candidate(text)
    if not candidate:
        return False

    if any(token in candidate for token in INCIDENT_DESCRIPTION_KEYWORDS):
        return False

    if any(token in candidate for token in LOCATION_HINT_TOKENS):
        return True

    if any(token in candidate for token in LANDMARK_HINT_TOKENS):
        return True

    return bool(re.search(r"\d", candidate) and any(token in candidate for token in ["巷", "弄", "號", "樓"]))


def is_likely_location_response(text: str) -> bool:
    candidate = normalize_location_candidate(text)
    if not candidate:
        return False

    if any(token in candidate for token in INCIDENT_DESCRIPTION_KEYWORDS):
        return False

    return has_strong_location_signal(candidate) or location_quality_score(candidate) >= 14


def is_likely_incident_detail(text: str, ex: Optional[Extracted] = None) -> bool:
    normalized = text.strip()
    if not normalized:
        return False

    if ex and ex.category and ex.category != "待確認":
        return True

    return any(token in normalized for token in INCIDENT_DESCRIPTION_KEYWORDS)


def build_incident_acknowledgement(ex: Extracted) -> str:
    if ex.category == "醫療急症":
        return "收到，現場有人身體不舒服，我先幫你整理。"
    if ex.category == "火災":
        return "收到，現場疑似有火災，我先幫你確認重點。"
    if ex.category == "暴力事件":
        return "收到，現場可能有衝突或人身危險，我先幫你整理。"
    if ex.category == "交通事故":
        return "收到，現場看起來有交通事故，我先幫你整理。"
    if ex.category == "可疑人士":
        return "收到，現場有可疑狀況，我先幫你整理。"
    if ex.category == "噪音":
        return "收到，我先幫你整理目前的情況。"
    return "收到，我先幫你整理目前的狀況。"


def asks_about_location(text: str) -> bool:
    return contains_any_keyword(text, LOCATION_QUESTION_KEYWORDS)


def asks_about_injury(text: str) -> bool:
    return contains_any_keyword(text, INJURY_QUESTION_KEYWORDS)


def asks_about_category(text: str) -> bool:
    return contains_any_keyword(text, CATEGORY_QUESTION_KEYWORDS)


def asks_about_weapon(text: str) -> bool:
    return contains_any_keyword(text, WEAPON_QUESTION_KEYWORDS)


def asks_about_danger(text: str) -> bool:
    return contains_any_keyword(text, DANGER_QUESTION_KEYWORDS)


def has_acute_medical_signal(text: str) -> bool:
    return any(keyword in text for keyword in ACUTE_MEDICAL_HIGH_KEYWORDS)


def has_medical_urgency_signal(text: str) -> bool:
    return any(keyword in text for keyword in MEDICAL_URGENCY_KEYWORDS)


def should_ask_scene_danger(ex: Extracted, risk_level: str) -> bool:
    if ex.danger_active is not None or risk_level not in ["Medium", "High"]:
        return False

    return ex.category in ["火災", "暴力事件", "交通事故", "可疑人士"]


def build_medical_acknowledgement(ex: Extracted, text: str) -> str:
    ref = subject_reference(ex)

    if ex.conscious is True and ex.breathing_difficulty is True:
        return f"收到，{ref}目前意識清楚，但有呼吸困難等急性症狀，需要優先留意。"
    if ex.conscious is False:
        return f"收到，{ref}目前意識不清，這屬於需要立即處理的醫療急症。"
    if has_acute_medical_signal(text) or ex.breathing_difficulty is True:
        if ex.breathing_difficulty is True:
            return f"收到，{ref}有呼吸困難等急性症狀，這屬於需要優先處理的醫療急症。"
        return f"收到，{ref}有明顯急性症狀，這屬於需要優先處理的醫療急症。"
    return f"收到，我先幫你確認{subject_possessive_reference(ex)}醫療狀況。"


def medical_follow_up_question(ex: Extracted, risk_level: str) -> str:
    ref = subject_reference(ex)

    if ex.breathing_difficulty is True or ex.conscious is False or risk_level == "High":
        return f"{ref}現在能正常說完整句子嗎？症狀有在加重，或需要立刻送醫嗎？如果越來越喘，請立刻撥 119。"
    return f"除了目前提到的症狀外，{ref}還有發燒、胸痛、嘔吐，或其他不舒服正在加重嗎？"


def risk_level_from_score(score: float) -> str:
    if score > 0.8:
        return "High"
    if score > 0.5:
        return "Medium"
    return "Low"


def apply_structured_risk_floor(
    text: str,
    ex: Extracted,
    risk_score: float,
    risk_level: str,
) -> tuple[float, str]:
    score = max(0.0, min(1.0, float(risk_score)))
    level = risk_level if risk_level in ["Low", "Medium", "High"] else risk_level_from_score(score)

    if ex.category == "醫療急症":
        if ex.breathing_difficulty is True or ex.conscious is False or has_acute_medical_signal(text):
            score = max(score, 0.85)
        elif ex.fever is True or has_medical_urgency_signal(text) or ex.people_injured is True:
            score = max(score, 0.62)

    level = risk_level_from_score(score)
    return score, level


def infer_reporter_role(text: str) -> Optional[str]:
    normalized = text.strip()
    if not normalized:
        return None

    self_markers = ["我發燒", "我不舒服", "我胸痛", "我喘不過氣", "我呼吸困難", "我昏倒", "我受傷"]
    other_markers = [
        "他",
        "她",
        "對方",
        "有人",
        "我朋友",
        "我同學",
        "我家人",
        "我爸",
        "我媽",
        "我先生",
        "我太太",
        "我兒子",
        "我女兒",
    ]

    if any(marker in normalized for marker in self_markers):
        return "本人"
    if any(marker in normalized for marker in other_markers):
        return "代他人通報"
    return None


def subject_reference(ex: Extracted) -> str:
    if ex.reporter_role == "本人":
        return "你"
    return "對方"


def subject_possessive_reference(ex: Extracted) -> str:
    if ex.reporter_role == "本人":
        return "你的"
    return "對方的"


def collect_symptoms(text: str) -> List[str]:
    symptom_pairs = [
        ("發燒", "發燒"),
        ("高燒", "高燒"),
        ("呼吸困難", "呼吸困難"),
        ("喘不過氣", "喘不過氣"),
        ("胸痛", "胸痛"),
        ("抽搐", "抽搐"),
        ("昏倒", "昏倒"),
        ("失去意識", "失去意識"),
        ("意識不清", "意識不清"),
        ("頭暈", "頭暈"),
        ("嘔吐", "嘔吐"),
        ("流血", "流血"),
        ("受傷", "受傷"),
        ("咳", "咳嗽"),
    ]
    symptoms: List[str] = []
    for keyword, label in symptom_pairs:
        if keyword in text and label not in symptoms:
            symptoms.append(label)
    return symptoms


def merge_symptom_summary(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
    tokens: List[str] = []
    for summary in [existing, incoming]:
        if not summary:
            continue
        for token in [part.strip() for part in summary.split("、")]:
            if token and token not in tokens:
                tokens.append(token)
    return "、".join(tokens) if tokens else (incoming or existing)


def enrich_extracted_details(ex: Extracted, text: str) -> Extracted:
    role = infer_reporter_role(text)
    if role:
        ex.reporter_role = role

    if "意識清楚" in text or "叫得醒" in text:
        ex.conscious = True
    elif any(keyword in text for keyword in ["意識不清", "昏迷", "失去意識", "叫不醒"]):
        ex.conscious = False

    if any(keyword in text for keyword in ["呼吸困難", "喘不過氣", "沒辦法呼吸", "呼吸很喘"]):
        ex.breathing_difficulty = True
    elif any(keyword in text for keyword in ["呼吸正常", "沒有呼吸困難", "沒有喘"]):
        ex.breathing_difficulty = False

    if any(keyword in text for keyword in ["發燒", "高燒"]):
        ex.fever = True
    elif "沒有發燒" in text:
        ex.fever = False

    symptoms = collect_symptoms(text)
    if symptoms:
        ex.symptom_summary = merge_symptom_summary(ex.symptom_summary, "、".join(symptoms))

    if ex.category == "醫療急症":
        if ex.breathing_difficulty is True or ex.conscious is False:
            ex.people_injured = True
        elif ex.people_injured is None and (ex.fever is True or bool(symptoms)):
            ex.people_injured = True

    return ex


def apply_category_scripts(ex: Extracted, risk_level: str) -> str:
    ref = subject_reference(ex)

    if ex.category == "醫療急症":
        if ex.conscious is None and ex.breathing_difficulty is None:
            return f"{ref}現在意識清楚嗎？有沒有呼吸困難、喘不過氣、昏倒，或需要立刻送醫？"
        if ex.conscious is None:
            return f"{ref}現在意識清楚嗎？有沒有昏倒、叫不太醒，或反應變慢？"
        if ex.breathing_difficulty is None:
            return f"{ref}有沒有呼吸困難、喘不過氣，或沒辦法正常說完整句子？"
        if ex.breathing_difficulty is True or ex.conscious is False:
            return medical_follow_up_question(ex, risk_level)
        if ex.fever is None:
            return f"{ref}有沒有發燒、胸痛、嘔吐，或其他症狀正在加重？"
        return medical_follow_up_question(ex, risk_level)

    if ex.category == "火災":
        if ex.danger_active is None:
            return "火勢或濃煙現在還在持續嗎？有沒有越燒越大？"
        if ex.people_injured is None:
            return "現場有人受困、嗆傷，或需要救護車嗎？"
        return "起火點大概是在住家、室內空間、店面，還是車輛附近？"

    if ex.category == "暴力事件":
        if ex.weapon is None:
            return "現場對方有持刀、棍棒或其他武器嗎？"
        if ex.danger_active is None:
            return "對方現在還在現場，或還在持續威脅嗎？"
        if ex.people_injured is None:
            return "現場有人受傷、流血，或需要立刻送醫嗎？"
        return "目前你們有沒有先移動到比較安全的位置？"

    if ex.category == "交通事故":
        if ex.people_injured is None:
            return "有人受傷、受困，或需要立刻叫救護車嗎？"
        if ex.danger_active is None:
            return "事故車輛現在還卡在車道上，或現場還有持續危險嗎？"
        return "事故大概是在路口、巷口，還是主要幹道？"

    if ex.category == "可疑人士":
        if ex.danger_active is None:
            return "那個人現在還在附近，或還在跟著你們嗎？"
        return "你可以描述一下對方的外觀、穿著，或目前在做什麼嗎？"

    if ex.category == "噪音":
        if ex.danger_active is None:
            return "現在吵鬧還在持續嗎？有沒有變成衝突或威脅？"
        return "聲音大概是來自住戶、施工，還是路邊聚眾？"

    return "可以再補充目前現場的狀況嗎？"


def get_client_location_text(audio_context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not audio_context:
        return None

    client_location = audio_context.get("client_location")
    if not isinstance(client_location, dict):
        return None

    for key in ["address", "display_text"]:
        value = client_location.get(key)
        if isinstance(value, str):
            normalized = normalize_location_candidate(value)
            if normalized:
                return normalized

    latitude = client_location.get("latitude")
    longitude = client_location.get("longitude")
    accuracy = client_location.get("accuracy")
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        if isinstance(accuracy, (int, float)):
            return f"{latitude:.6f}, {longitude:.6f} (+/- {round(accuracy)}m)"
        return f"{latitude:.6f}, {longitude:.6f}"

    return None

def simple_extract(text: str) -> Extracted:
    ex = Extracted(description=text)

    if any(k in text for k in ["火災", "失火", "著火", "起火", "冒煙", "燒起來"]):
        ex.category = "火災"
    elif any(k in text for k in ["可疑", "跟蹤", "怪人", "鬼鬼祟祟", "闖入"]):
        ex.category = "可疑人士"
    elif any(k in text for k in ["噪音", "很吵", "吵鬧", "施工", "喧嘩"]):
        ex.category = "噪音"
    elif any(k in text for k in ["昏倒", "流血", "受傷", "沒呼吸", "抽搐", "心臟痛", "頭暈", "胸痛", "呼吸困難", "喘不過氣", "不舒服", "發燒", "嘔吐"]):
        ex.category = "醫療急症"
    elif any(k in text for k in ["打架", "刀", "砍", "威脅", "家暴", "被打"]):
        ex.category = "暴力事件"
    elif any(k in text for k in ["車禍", "撞車", "翻車", "追撞"]):
        ex.category = "交通事故"
    else:
        ex.category = "待確認"

    if any(k in text for k in ["流血", "受傷", "昏倒", "沒呼吸", "抽搐", "骨折", "頭暈", "胸痛", "呼吸困難", "喘不過氣", "嘔吐"]):
        ex.people_injured = True
    else:
        ex.people_injured = None

    if any(k in text for k in ["刀", "槍", "武器", "棍棒"]):
        ex.weapon = True
    else:
        ex.weapon = None

    if any(k in text for k in ["還在", "持續", "正在", "還沒結束", "還在現場"]):
        ex.danger_active = True
    else:
        ex.danger_active = None

    for key in ["在", "位於", "地址", "地點是"]:
        if key in text:
            idx = text.find(key) + len(key)
            candidate = normalize_location_candidate(text[idx: idx + 25])
            if candidate and is_likely_location_response(candidate):
                ex.location = candidate
                break

    ex = enrich_extracted_details(ex, text)
    ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
    return ex


def merge_extracted(base: Extracted, incoming: Extracted) -> Extracted:
    base.category = normalize_category_name(base.category)
    incoming.category = normalize_category_name(incoming.category)

    if incoming.category and incoming.category != "待確認":
        base.category = incoming.category
    elif not base.category:
        base.category = incoming.category

    if incoming.location and location_quality_score(incoming.location) >= location_quality_score(base.location):
        base.location = incoming.location
    if incoming.people_injured is not None:
        base.people_injured = incoming.people_injured
    if incoming.weapon is not None:
        base.weapon = incoming.weapon
    if incoming.danger_active is not None:
        base.danger_active = incoming.danger_active
    if incoming.reporter_role:
        base.reporter_role = incoming.reporter_role
    if incoming.conscious is not None:
        base.conscious = incoming.conscious
    if incoming.breathing_difficulty is not None:
        base.breathing_difficulty = incoming.breathing_difficulty
    if incoming.fever is not None:
        base.fever = incoming.fever
    if incoming.symptom_summary:
        base.symptom_summary = merge_symptom_summary(base.symptom_summary, incoming.symptom_summary)
    if incoming.description:
        base.description = incoming.description

    base.dispatch_advice = get_dispatch_advice(base.category, base.weapon, base.people_injured)
    return base


def apply_turn_context(messages: List[ChatMessage], ex: Extracted) -> Extracted:
    last_user_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last_user_index = index
            break

    if last_user_index is None:
        return ex

    latest_user_text = messages[last_user_index].content.strip()
    previous_assistant_text = ""

    for index in range(last_user_index - 1, -1, -1):
        if messages[index].role == "assistant":
            previous_assistant_text = messages[index].content.strip()
            break

    normalized_location = normalize_location_candidate(latest_user_text)
    asked_for_location = asks_about_location(previous_assistant_text)

    if (
        not ex.location
        and latest_user_text
        and asked_for_location
        and is_likely_location_response(latest_user_text)
        and normalized_location
    ):
        ex.location = normalized_location

    ex = enrich_extracted_details(ex, latest_user_text)

    if ex.category == "待確認" and latest_user_text:
        category_map = {
            "火災": "火災",
            "失火": "火災",
            "可疑人士": "可疑人士",
            "可疑": "可疑人士",
            "噪音": "噪音",
            "醫療": "醫療急症",
            "急症": "醫療急症",
            "暴力": "暴力事件",
            "打架": "暴力事件",
            "車禍": "交通事故",
            "交通事故": "交通事故",
        }
        mapped = category_map.get(latest_user_text)
        if mapped:
            ex.category = mapped

    if not ex.dispatch_advice:
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)

    return ex


def extract_conversation_state(messages: List[ChatMessage]) -> Extracted:
    merged = Extracted(
        category="待確認",
        location=None,
        people_injured=None,
        weapon=None,
        danger_active=None,
        reporter_role=None,
        conscious=None,
        breathing_difficulty=None,
        fever=None,
        symptom_summary=None,
        dispatch_advice="建議派遣：待確認",
        description=None,
    )

    for index, message in enumerate(messages):
        if message.role != "user":
            continue
        turn_extracted = simple_extract(message.content)
        turn_extracted = apply_turn_context(messages[: index + 1], turn_extracted)
        merged = merge_extracted(merged, turn_extracted)

    return merged


def get_last_turn_context(messages: List[ChatMessage]) -> tuple[str, str]:
    last_user_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last_user_index = index
            break

    if last_user_index is None:
        return "", ""

    latest_user_text = messages[last_user_index].content.strip()
    previous_assistant_text = ""

    for index in range(last_user_index - 1, -1, -1):
        if messages[index].role == "assistant":
            previous_assistant_text = messages[index].content.strip()
            break

    return latest_user_text, previous_assistant_text


def contextualize_reply_and_question(
    messages: List[ChatMessage],
    ex: Extracted,
    reply: str,
    next_q: str,
    risk_level: str,
) -> tuple[str, str]:
    latest_user_text, previous_assistant_text = get_last_turn_context(messages)
    latest_user_text = latest_user_text.strip()
    previous_assistant_text = previous_assistant_text.strip()
    ex = enrich_extracted_details(ex, latest_user_text)

    def contains_any(text: str, keywords: List[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def is_yes(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["有", "是", "對", "會", "需要", "有的", "有喔", "有啊", "對啊", "對喔", "嗯", "恩", "要"]

    def is_no(text: str) -> bool:
        normalized = text.replace("！", "").replace("!", "").strip().lower()
        return normalized in ["沒有", "沒", "不是", "不會", "不用", "沒有喔", "沒有啊", "沒有呢"]

    def normalize_location_text(text: str) -> str:
        return normalize_location_candidate(text) or text.strip()

    normalized_user_location = normalize_location_text(latest_user_text)
    answered_location = is_likely_location_response(latest_user_text)
    answered_incident_detail = is_likely_incident_detail(latest_user_text, ex)

    if (
        ex.location
        and latest_user_text
        and answered_location
        and normalized_user_location == ex.location
        and asks_about_location(previous_assistant_text)
    ):
        reply = f"收到，地點是在{ex.location}。"
        if ex.category == "待確認":
            next_q = "那現場現在是發生了什麼事？像是火災、衝突、車禍，還是有人身體不舒服？"
        else:
            next_q = next_question(ex, risk_level)

    elif asks_about_location(previous_assistant_text) and answered_incident_detail:
        reply = build_incident_acknowledgement(ex)
        next_q = next_question(ex, risk_level)

    elif (
        ex.category
        and ex.category != "待確認"
        and latest_user_text
        and contains_any(previous_assistant_text, ["火災", "可疑人士", "噪音", "醫療急症", "暴力事件", "交通事故"])
    ):
        reply = f"了解，這看起來是{ex.category}。"
        next_q = next_question(ex, risk_level)

    elif asks_about_injury(previous_assistant_text):
        if ex.category == "醫療急症" and (
            has_medical_urgency_signal(latest_user_text)
            or "意識清楚" in latest_user_text
            or "意識不清" in latest_user_text
        ):
            ex.people_injured = True
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            reply = build_medical_acknowledgement(ex, latest_user_text)
            next_q = medical_follow_up_question(ex, risk_level)
        elif is_yes(latest_user_text):
            ex.people_injured = True
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            reply = "收到，現場有人受傷，我會優先以需要醫療協助的情況來處理。"
            if should_ask_scene_danger(ex, risk_level):
                next_q = "目前危險還在持續嗎？例如火勢、衝突，或肇事者還在現場嗎？"
            else:
                next_q = "請再告訴我現場目前最危急的狀況，我幫你整理成通報內容。"
        elif is_no(latest_user_text):
            ex.people_injured = False
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            reply = "了解，目前沒有明確提到有人受傷。"
            if ex.category == "暴力事件" and ex.weapon is None:
                next_q = "現場對方有持刀、棍棒或其他武器嗎？"
            elif should_ask_scene_danger(ex, risk_level):
                next_q = "目前危險還在持續嗎？對方或事件還在現場嗎？"

    elif asks_about_weapon(previous_assistant_text):
        if is_yes(latest_user_text):
            ex.weapon = True
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            reply = "收到，現場可能有武器，風險會比較高。"
            next_q = "現在對方或危險因素還在現場嗎？請先確認你自己是否安全。"
        elif is_no(latest_user_text):
            ex.weapon = False
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
            reply = "了解，目前沒有提到武器。"
            if should_ask_scene_danger(ex, risk_level):
                next_q = "目前危險還在持續嗎？對方或事件還在現場嗎？"

    elif asks_about_danger(previous_assistant_text):
        if is_yes(latest_user_text):
            ex.danger_active = True
            reply = "收到，危險目前還在持續。你先以自身安全為優先，盡量移動到安全的位置。"
            next_q = "如果方便，請再補充現場有幾個人、目前最危急的是什麼，我會幫你整理成通報重點。"
        elif is_no(latest_user_text):
            ex.danger_active = False
            reply = "了解，目前危險看起來沒有持續擴大。"
            next_q = "請再補充一下現場的狀況，我會幫你整理後續通報內容。"

    return reply, next_q


def sanitize_reply_and_question(
    reply: str,
    next_q: str,
    ex: Extracted,
    risk_level: str,
) -> tuple[str, str]:
    reply = (reply or "").strip()
    next_q = (next_q or "").strip()

    ex.category = normalize_category_name(ex.category)

    if ex.location:
        normalized_location = normalize_location_candidate(ex.location)
        if normalized_location:
            ex.location = normalized_location

    for _ in range(4):
        changed = False

        if ex.category == "醫療急症" and reply and asks_about_danger(reply):
            reply = "收到，目前這比較像是醫療急症，我先幫你確認症狀變化。"
            changed = True
        elif ex.location and reply and asks_about_location(reply):
            reply = build_incident_acknowledgement(ex)
            changed = True

        replacement = None
        if ex.category == "醫療急症" and asks_about_danger(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.location and asks_about_location(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.category and ex.category != "待確認" and asks_about_category(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.people_injured is not None and asks_about_injury(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.weapon is not None and asks_about_weapon(next_q):
            replacement = next_question(ex, risk_level)
        elif ex.danger_active is not None and asks_about_danger(next_q):
            replacement = next_question(ex, risk_level)

        if replacement and replacement != next_q:
            next_q = replacement
            changed = True

        if not changed:
            break

    return reply, next_q


# ======================
# 風險判斷
# ======================

def simple_risk(text: str):
    score = 0.2

    high_keywords = ["流血", "昏倒", "沒呼吸", "火災", "失火", "刀", "砍", "打架", "威脅", "闖入"]
    medium_keywords = ["可疑", "跟蹤", "害怕", "噪音", "吵鬧", "怪人"]

    if any(k in text for k in high_keywords):
        score = 0.9
    elif any(k in text for k in medium_keywords):
        score = 0.6

    score += random.uniform(-0.03, 0.03)
    score = max(0.0, min(1.0, score))

    if score > 0.8:
        level = "High"
    elif score > 0.5:
        level = "Medium"
    else:
        level = "Low"

    return score, level


# ======================
# 自動追問
# ======================

def next_question(ex: Extracted, risk_level: str) -> str:
    if risk_level == "High" and not ex.location:
        return "請問事發地點在哪裡？"

    if ex.category == "待確認":
        if not ex.location:
            return "請問事發地點在哪裡？"
        return "請問是火災、可疑人士、噪音、醫療急症、暴力事件，還是交通事故？"

    return apply_category_scripts(ex, risk_level)


# ======================
# 案件摘要生成
# ======================

def generate_incident_summary(ex: Extracted, risk_level: str) -> str:
    summary = []

    summary.append(f"案件類型：{ex.category or '待確認'}")
    summary.append(f"地點：{ex.location or '未提供'}")
    if ex.reporter_role:
        summary.append(f"通報角色：{ex.reporter_role}")

    if ex.people_injured:
        summary.append("傷勢：現場有人受傷或需要醫療協助")

    if ex.conscious is True:
        summary.append("意識：目前清楚")
    elif ex.conscious is False:
        summary.append("意識：不清或無反應")

    if ex.breathing_difficulty is True:
        summary.append("呼吸：有呼吸困難")

    if ex.fever is True:
        summary.append("症狀：有發燒")

    if ex.symptom_summary:
        summary.append(f"症狀摘要：{ex.symptom_summary}")

    if ex.weapon:
        summary.append("注意：現場可能有武器")

    if ex.danger_active:
        summary.append("危險狀況：事件仍在持續")

    summary.append(f"風險等級：{risk_level}")
    summary.append(ex.dispatch_advice or "建議派遣：待確認")

    return " | ".join(summary)


# ======================
# LLM 分析
# ======================

def llm_chat(messages: List[ChatMessage]) -> Dict[str, Any]:
    if not llm_is_ready():
        raise RuntimeError("LLM 未初始化")

    recent = messages[-10:]
    context = "\n".join(
        f"{'使用者' if m.role == 'user' else '助手'}：{m.content}"
        for m in recent
    )


    prompt = f"""
你是 E-CARE 緊急事件關懷助理。你的風格要冷靜、穩定、有同理心，像受過訓練的真人接線助理。

請根據以下對話輸出嚴格 JSON，不要加入其他文字。
請使用繁體中文。
如果資訊不確定請填 null，不要自行猜測。

回覆原則：
- 先用 1 句自然口語接住對方情緒，再進入重點
- 不要機械重述使用者原句，不要出現像「你在你旁邊」這種不自然說法
- 一次只問 1 個最重要的問題
- 如果 reply 已經包含完整提問，next_question 請輸出空字串
- 不要把「我旁邊、這裡、附近、現場」當成明確位置
- reply 要短，像真人說話，不要像表單

category 只能從以下擇一：
- 火災
- 可疑人士
- 噪音
- 醫療急症
- 暴力事件
- 交通事故
- 待確認

risk_level 只能是：
- Low
- Medium
- High

JSON 格式如下：
{{
  "reply": "string",
  "risk_score": 0.0,
  "risk_level": "Low",
  "should_escalate": false,
  "next_question": "string",
  "extracted": {{
    "category": "string|null",
    "location": "string|null",
    "people_injured": true,
    "weapon": false,
    "danger_active": true,
    "reporter_role": "string|null",
    "conscious": true,
    "breathing_difficulty": true,
    "fever": true,
    "symptom_summary": "string|null",
    "dispatch_advice": "string|null",
    "description": "string|null"
  }}
}}

風險規則：
- 涉及火災、流血、昏倒、沒呼吸、持刀、打架、威脅、闖入 → High
- 涉及可疑人士、跟蹤、害怕、嚴重噪音衝突 → Medium
- 低急迫性一般諮詢 → Low

對話如下：
{context}
"""

    resp = call_llm(prompt)

    text = (resp.text or "").strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    data = json.loads(text)
    return data


def llm_chat_with_audio(
    messages: List[ChatMessage],
    audio_context: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    user_context: Optional[ChatUserContext] = None,
) -> Dict[str, Any]:
    if not llm_is_ready():
        raise RuntimeError("LLM client not ready")

    recent = messages[-10:]
    conversation_state = extract_conversation_state(messages)
    user_identity = build_graph_user_identity(session_id, user_context)
    client_location_text = get_client_location_text(audio_context)
    if client_location_text and not conversation_state.location:
        conversation_state.location = client_location_text
        conversation_state.dispatch_advice = get_dispatch_advice(
            conversation_state.category,
            conversation_state.weapon,
            conversation_state.people_injured,
        )
    context = "\n".join(
        f"{'使用者' if m.role == 'user' else '助理'}：{m.content}"
        for m in recent
    )

    audio_context_text = "無"
    if audio_context:
        safe_audio_context = {
            "transcript": audio_context.get("transcript"),
            "emotion": audio_context.get("emotion"),
            "emotion_score": audio_context.get("emotion_score"),
            "situation": audio_context.get("situation"),
            "risk_level": audio_context.get("risk_level"),
            "risk_score": audio_context.get("risk_score"),
            "extracted": audio_context.get("extracted"),
            "client_location": audio_context.get("client_location"),
        }
        audio_context_text = json.dumps(safe_audio_context, ensure_ascii=False)
    graph_plan = graph_reasoning_from_context(messages, conversation_state, audio_context)
    neo4j_info = query_neo4j_by_plan(graph_plan)
    if not neo4j_info:
        neo4j_info = query_neo4j_by_keyword(context)
    user_graph_context = query_neo4j_user_context(user_identity)
    neo4j_hint = build_neo4j_hint(graph_plan, neo4j_info, user_graph_context)

    known_context = json.dumps(
        {
            "category": conversation_state.category,
            "location": conversation_state.location,
            "people_injured": conversation_state.people_injured,
            "weapon": conversation_state.weapon,
            "danger_active": conversation_state.danger_active,
            "dispatch_advice": conversation_state.dispatch_advice,
        },
        ensure_ascii=False
    )
        
    prompt = f"""
你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。

回覆原則：
- 先用 1 句短短安撫或接住情緒的話，再進入協助
- 若資訊不足，一次只追問 1 個最重要的問題
- 如果風險高，優先確認安全、位置、是否有人受傷
- 請延續前面的對話，不要重複已經問過且已經得到答案的問題
- 如果使用者剛剛只回答短句，例如地點、症狀、是否受傷，請把它視為對上一題的回答
- 如果目前已整理出的案件資訊中 location 已有值，表示位置已知，不要再追問地點
- 如果使用者這句是在描述症狀或事件，不要把那句話誤當成地址
- reply 一律使用繁體中文，自然口語，不要寫得像表單或系統訊息
- 不要機械重述使用者的句子，避免不自然的語句
- 不要把「我旁邊、這裡、附近、現場」當成明確位置
- 如果 reply 已經是一句完整的提問，next_question 請輸出空字串
- 只能輸出 JSON，不要加註解或 markdown

category 只能是：
- 火災
- 可疑人士
- 噪音
- 醫療急症
- 暴力事件
- 交通事故
- 待確認

risk_level 只能是：
- Low
- Medium
- High

輸出格式：
{{
 "reply": "string",
  "risk_score": 0.0,
  "risk_level": "Low",
  "should_escalate": false,
  "next_question": "string",
  "extracted": {{
    "category": "string|null",
    "location": "string|null",
    "people_injured": true,
    "weapon": false,
    "danger_active": true,
    "reporter_role": "string|null",
    "conscious": true,
    "breathing_difficulty": true,
    "fever": true,
    "symptom_summary": "string|null",
    "dispatch_advice": "string|null",
    "description": "string|null"
 }}
}}

風格要求：
- reply 長度盡量控制在 1 到 2 句
- 優先用「我知道你現在很慌／我先陪你整理」這類自然說法
- 不要同時在 reply 和 next_question 問同一件事
- 如果對方描述的是他人出事，不要誤問成「你是否清醒」
- 如果位置不明確，就說「你現在人在哪裡」或「事發地點在哪裡」，不要自行腦補

風險判斷原則：
- 明確人身危險、武器、火勢、持續暴力、重傷，傾向 High
- 有受傷、威脅、自傷風險、狀況未明但令人擔心，傾向 Medium
- 單純諮詢、情緒低落但無立即危險，傾向 Low

圖譜使用原則：
- 先參考 Neo4j 查到的事件知識，再結合目前對話回應
- 如果圖譜中已有建議派遣或處置，請自然整合進回覆，不要像貼資料表
- 如果圖譜中已有使用者近期提過的事件、地點或情緒，可用來避免重複追問
- 不要硬套圖譜內容；若和當前對話衝突，以最新使用者描述為主

接線腳本原則：
- 若是醫療急症，優先釐清「本人還是替他人通報」、「意識是否清楚」、「是否呼吸困難」、「症狀是否惡化」
- 若是火災，優先釐清火勢 / 濃煙是否持續、是否有人受困、起火點大概在哪
- 若是暴力事件，優先釐清是否有武器、危險人物是否仍在現場、是否有人受傷
- 若是交通事故，優先釐清是否有人受傷、車輛是否仍在危險位置
- 已經確認過的欄位不要重複問

最新語音分析：
{audio_context_text}

目前已整理出的案件資訊：
{known_context}

{neo4j_hint}
對話內容：
{context}
"""

    resp = call_llm(prompt)

    text = (resp.text or "").strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def semantic_understanding_from_text(
    text: str,
    audio_context: Optional[Dict[str, Any]] = None,
    extracted: Optional[Extracted] = None
) -> SemanticUnderstanding:
    client_location_text = get_client_location_text(audio_context)
    fallback_entities = SemanticEntities(
        location=(extracted.location if extracted and extracted.location else client_location_text),
        injured=(extracted.people_injured if extracted else None),
        weapon=(extracted.weapon if extracted else None),
        danger_active=(extracted.danger_active if extracted else None),
    )

    if not text.strip():
        return SemanticUnderstanding(entities=fallback_entities)

    if not llm_is_ready():
        intent = "求救" if any(k in text for k in ["救", "幫", "快點", "危險"]) else "資訊補充"
        primary_need = "立即安全協助" if any(k in text for k in ["救", "危險", "受傷"]) else "釐清狀況"
        reply_strategy = "先安撫，再確認位置與安全" if any(k in text for k in ["怕", "救", "危險"]) else "先確認事件重點"
        emotion = "panic" if audio_context and audio_context.get("emotion") in ["panic", "fearful"] else "neutral"
        return SemanticUnderstanding(
            intent=intent,
            primary_need=primary_need,
            emotion=emotion,
            reply_strategy=reply_strategy,
            entities=fallback_entities
        )

    safe_audio_context = {
        "transcript": (audio_context or {}).get("transcript"),
        "emotion": (audio_context or {}).get("emotion"),
        "emotion_score": (audio_context or {}).get("emotion_score"),
        "risk_level": (audio_context or {}).get("risk_level"),
        "risk_score": (audio_context or {}).get("risk_score"),
        "client_location": client_location_text,
    }
    safe_extracted = extracted.dict() if extracted else {}

    prompt = f"""
你是語意理解模組。請根據使用者文字、語音情緒與事件抽取結果，輸出語意理解 JSON。

規則：
- 只能輸出 JSON
- intent 只能是：求救、通報、詢問、情緒支持、資訊補充、未知
- primary_need 要簡短描述此刻最需要的協助
- emotion 可綜合文字語氣與語音情緒
- reply_strategy 要描述助理最適合的回應策略
- 如果文字是在描述他人出事，primary_need 與 reply_strategy 也要反映「協助通報/確認現場」而不是只安撫本人
- 不要把「我旁邊、這裡、附近、現場」當成明確位置

輸出格式：
{{
  "intent": "string",
  "primary_need": "string",
  "emotion": "string",
  "reply_strategy": "string",
  "entities": {{
    "location": "string|null",
    "injured": true,
    "weapon": false,
    "danger_active": true
  }}
}}

文字：
{text}

語音脈絡：
{json.dumps(safe_audio_context, ensure_ascii=False)}

事件抽取：
{json.dumps(safe_extracted, ensure_ascii=False)}
"""
    try:
        resp = call_llm(prompt)
        result_text = (resp.text or "").strip()
        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "").replace("```", "").strip()

        data = json.loads(result_text)
        entities = data.get("entities", {}) or {}
        return SemanticUnderstanding(
            intent=data.get("intent") or "未知",
            primary_need=data.get("primary_need") or "釐清狀況",
            emotion=data.get("emotion") or ((audio_context or {}).get("emotion") or "neutral"),
            reply_strategy=data.get("reply_strategy") or "先確認事件重點",
            entities=SemanticEntities(
                location=entities.get("location", fallback_entities.location),
                injured=entities.get("injured", fallback_entities.injured),
                weapon=entities.get("weapon", fallback_entities.weapon),
                danger_active=entities.get("danger_active", fallback_entities.danger_active),
            )
        )
    except Exception:
        return SemanticUnderstanding(
            intent="未知",
            primary_need="釐清狀況",
            emotion=(audio_context or {}).get("emotion") or "neutral",
            reply_strategy="先確認事件重點",
            entities=fallback_entities
        )


def apply_semantic_tone(reply: str, semantic: SemanticUnderstanding, risk_level: str) -> str:
    prefix = ""

    if semantic.emotion in ["panic", "fearful"]:
        prefix = "我知道你現在很慌，我會先陪你把重點整理清楚。"
    elif semantic.emotion == "sad":
        prefix = "我有注意到你現在很難受，我會陪你一步一步整理。"
    elif semantic.emotion == "angry":
        prefix = "我知道你現在很激動，我先幫你抓重點。"
    elif semantic.intent == "情緒支持":
        prefix = "我在，你可以慢慢說，我會陪你一起整理。"

    if risk_level == "High" and "安全" not in reply:
        if semantic.primary_need and "通報" in semantic.primary_need:
            suffix = " 先留意現場安全，如果方便，請立刻告訴我目前位置。"
        else:
            suffix = " 先確認你現在是否安全，如果方便，請立刻告訴我目前位置。"
    elif semantic.reply_strategy and "安撫" in semantic.reply_strategy and semantic.primary_need:
        suffix = f" 我會先以{semantic.primary_need}為主。"
    else:
        suffix = ""

    return f"{prefix}{reply}{suffix}".strip()


def next_question_from_semantic(
    default_question: str,
    semantic: SemanticUnderstanding,
    ex: Extracted,
    risk_level: str
) -> str:
    if risk_level == "High" and not (semantic.entities.location or ex.location):
        return "你現在人在哪裡？請告訴我地址、明顯地標，或附近路名。"

    if ex.category == "醫療急症":
        return next_question(ex, risk_level)

    if risk_level in ["Medium", "High"] and semantic.entities.injured is None and ex.people_injured is None:
        return "現場有人受傷、失去意識，或需要立刻送醫嗎？"

    if semantic.intent == "情緒支持":
        return "你現在身邊有沒有可以陪你的人，或你目前是不是一個人？"

    if semantic.intent == "詢問":
        return "你最想先知道哪一部分？我可以先直接回答你最急的問題。"

    return default_question


# ======================
# Chat API
# ======================

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    context = " ".join(
        m.content for m in req.messages if m.role == "user"
    ).strip()
    latest_text = latest_user_text(req.messages)
    conversation_state = extract_conversation_state(req.messages)

    if not context:
        return ChatResponse(
            reply="請先描述一下目前發生的情況，我會協助你整理資訊。",
            risk_score=0.1,
            risk_level="Low",
            should_escalate=False,
            next_question="請問目前發生了什麼事？",
            extracted=Extracted(
                category="待確認",
                location=None,
                people_injured=None,
                weapon=None,
                danger_active=None,
                dispatch_advice="建議派遣：待確認",
                description="案件類型：待確認 | 地點：未提供 | 風險等級：Low | 建議派遣：待確認"
            ),
            semantic=SemanticUnderstanding()
        )

    try:
        data = llm_chat_with_audio(
            req.messages,
            req.audio_context,
            req.session_id,
            req.user_context,
        )
        extracted = data.get("extracted", {}) or {}
        client_location_text = get_client_location_text(req.audio_context)

        ex = Extracted(
            category=extracted.get("category"),
            location=extracted.get("location"),
            people_injured=extracted.get("people_injured"),
            weapon=extracted.get("weapon"),
            danger_active=extracted.get("danger_active"),
            reporter_role=extracted.get("reporter_role"),
            conscious=extracted.get("conscious"),
            breathing_difficulty=extracted.get("breathing_difficulty"),
            fever=extracted.get("fever"),
            symptom_summary=extracted.get("symptom_summary"),
            dispatch_advice=extracted.get("dispatch_advice"),
            description=extracted.get("description"),
        )
        ex.category = normalize_category_name(ex.category)
        ex = apply_turn_context(req.messages, ex)
        if not ex.location and client_location_text:
            ex.location = client_location_text
        ex = merge_extracted(conversation_state, ex)

        risk_score = float(data.get("risk_score", 0.2))
        risk_score = max(0.0, min(1.0, risk_score))

        risk_level = data.get("risk_level", "Low")
        if risk_level not in ["Low", "Medium", "High"]:
            risk_level = "Low"
        risk_score, risk_level = apply_structured_risk_floor(context, ex, risk_score, risk_level)

        should_escalate = bool(data.get("should_escalate", False)) or risk_level == "High"

        if not ex.dispatch_advice:
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)

        summary = generate_incident_summary(ex, risk_level)
        ex.description = summary
        semantic = semantic_understanding_from_text(context, req.audio_context, ex)

        reply = data.get("reply") or "我會一步一步協助你整理資訊。"
        nq = data.get("next_question") or next_question(ex, risk_level)
        reply, nq = contextualize_reply_and_question(req.messages, ex, reply, nq, risk_level)
        reply = apply_semantic_tone(reply, semantic, risk_level)
        nq = next_question_from_semantic(nq, semantic, ex, risk_level)
        reply, nq = sanitize_reply_and_question(reply, nq, ex, risk_level)
        sync_chat_state_to_neo4j(req.session_id, req.user_context, ex, semantic, latest_text)

        return ChatResponse(
            reply=reply,
            risk_score=risk_score,
            risk_level=risk_level,
            should_escalate=should_escalate,
            next_question=nq,
            extracted=ex,
            semantic=semantic
        )

    except Exception as e:
        print("LLM fallback:", str(e))

        score, level = simple_risk(context)
        ex = simple_extract(context)
        ex = apply_turn_context(req.messages, ex)
        client_location_text = get_client_location_text(req.audio_context)
        if not ex.location and client_location_text:
            ex.location = client_location_text
        ex = merge_extracted(conversation_state, ex)
        score, level = apply_structured_risk_floor(context, ex, score, level)
        summary = generate_incident_summary(ex, level)
        ex.description = summary
        semantic = semantic_understanding_from_text(context, req.audio_context, ex)
        if level == "High":
            reply = "我了解你現在很緊張，我會快速協助你整理資訊並引導你進行通報。"
        elif level == "Medium":
            reply = "我了解你的狀況，我會一步步協助你整理必要資訊。"
        else:
            reply = "我在這裡，我會協助你把事情講清楚。"

        follow_up = next_question_from_semantic(next_question(ex, level), semantic, ex, level)
        reply, follow_up = contextualize_reply_and_question(req.messages, ex, reply, follow_up, level)
        reply = apply_semantic_tone(reply, semantic, level)
        reply, follow_up = sanitize_reply_and_question(reply, follow_up, ex, level)
        sync_chat_state_to_neo4j(req.session_id, req.user_context, ex, semantic, latest_text)

        return ChatResponse(
            reply=reply,
            risk_score=score,
            risk_level=level,
            should_escalate=(level == "High"),
            next_question=follow_up,
            extracted=ex,
            semantic=semantic
        )


# ======================
# Whisper
# ======================

@app.post("/audio")
async def audio_to_text(audio: UploadFile = File(...)):
    global WHISPER_MODEL, EMOTION_MODEL

    if WHISPER_MODEL is None:
        raise HTTPException(status_code=503, detail="Whisper model 尚未載入完成")

    if EMOTION_MODEL is None:
        raise HTTPException(status_code=503, detail="Emotion model 尚未載入")

    tmp_in = None
    tmp_wav = None

    try:
        ext = os.path.splitext(audio.filename or "")[1].lower()
        if ext not in [".webm", ".wav", ".mp3", ".m4a", ".ogg", ".aac"]:
            ext = ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            content = await audio.read()
            if not content:
                raise HTTPException(status_code=400, detail="收到的音訊是空的")
            f.write(content)
            tmp_in = f.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f2:
            tmp_wav = f2.name

        cmd = [
            "ffmpeg",
            "-y",
            "-i", tmp_in,
            "-ac", "1",
            "-ar", "16000",
            tmp_wav
        ]

        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            raise HTTPException(status_code=500, detail=f"ffmpeg 轉檔失敗：{p.stderr[-500:]}")

        # 1. Whisper 轉文字
        result = WHISPER_MODEL.transcribe(tmp_wav, language="zh", fp16=False)
        text = (result.get("text") or "").strip()
        text = fix_transcript(text)

        if not text:
            text = "（無法辨識語音）"

        # 2. 情緒辨識
        emotion_result = predict_emotion_from_wav(tmp_wav)

        # 3. 整合
        final_result = build_audio_analysis_result(
            transcript=text,
            emotion=emotion_result["emotion"],
            emotion_score=emotion_result["emotion_score"]
        )

        return {
            "transcript": text,
            "emotion": emotion_result["emotion"],
            "emotion_score": emotion_result["emotion_score"],
            "situation": final_result["situation"],
            "risk_level": final_result["risk_level"],
            "risk_score": final_result["risk_score"],
            "extracted": final_result["extracted"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"audio_to_text 失敗：{str(e)}")
    finally:
        for path in [tmp_in, tmp_wav]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
                
# ======================
# reports
# ======================

@app.get("/reports", response_model=List[ReportItem])
def list_reports():
    ensure_db_available()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM case_records ORDER BY created_at DESC LIMIT 200;"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [ReportItem(**dict(row)) for row in rows]
    except Exception as e:
        print(f"❌ list_reports 失敗：{e}")
        raise HTTPException(status_code=500, detail=f"資料庫查詢失敗：{str(e)}")


@app.post("/reports", response_model=ReportItem)
def create_report(payload: ReportCreate):
    ensure_db_available()
    rid = make_id("A")
    item = ReportItem(
        id=rid,
        title=payload.title,
        category=payload.category,
        location=payload.location,
        status="處理中",
        created_at=now_str(),
        risk_level=payload.risk_level,
        risk_score=payload.risk_score,
        description=payload.description,
    )
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO case_records
                (id, title, category, location, status, created_at, risk_level, risk_score, description)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item.id, item.title, item.category, item.location,
                item.status, item.created_at, item.risk_level,
                item.risk_score, item.description,
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ 案件寫入 PostgreSQL：{item.id}")
        return item
    except Exception as e:
        print(f"❌ create_report 失敗：{e}")
        raise HTTPException(status_code=500, detail=f"資料庫寫入失敗：{str(e)}")
    

@app.get("/users", response_model=List[UserItem])
def list_users():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM ecare_user ORDER BY created_at DESC;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [build_user_item(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查詢失敗：{str(e)}")


@app.post("/users", response_model=UserItem)
def create_user(payload: UserCreate):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        existing_user_id = find_existing_user_id(cur, payload)
        if existing_user_id is not None:
            cur.execute("""
                UPDATE ecare_user
                SET
                    name = %s,
                    phone = %s,
                    gender = %s,
                    age = %s,
                    emergency_name = %s,
                    emergency_phone = %s,
                    relationship = %s,
                    address = %s,
                    notes = %s
                WHERE id = %s
                RETURNING *;
            """, (
                payload.name, payload.phone, payload.gender, payload.age,
                payload.emergency_name, payload.emergency_phone,
                payload.relationship, payload.address, payload.notes,
                existing_user_id,
            ))
        else:
            cur.execute("""
                INSERT INTO ecare_user
                    (name, phone, gender, age, emergency_name, emergency_phone, relationship, address, notes)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (
                payload.name, payload.phone, payload.gender, payload.age,
                payload.emergency_name, payload.emergency_phone,
                payload.relationship, payload.address, payload.notes
            ))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return build_user_item(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"新增失敗：{str(e)}")


@app.put("/users/{user_id}", response_model=UserItem)
def update_user(user_id: int, payload: UserCreate):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            UPDATE ecare_user
            SET
                name = %s,
                phone = %s,
                gender = %s,
                age = %s,
                emergency_name = %s,
                emergency_phone = %s,
                relationship = %s,
                address = %s,
                notes = %s
            WHERE id = %s
            RETURNING *;
        """, (
            payload.name, payload.phone, payload.gender, payload.age,
            payload.emergency_name, payload.emergency_phone,
            payload.relationship, payload.address, payload.notes,
            user_id,
        ))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="找不到此使用者")
        return build_user_item(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.get("/users/{user_id}", response_model=UserItem)
def get_user(user_id: int):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM ecare_user WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="找不到此使用者")
        return build_user_item(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查詢失敗：{str(e)}")
