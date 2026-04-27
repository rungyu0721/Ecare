"""
Neo4j 圖資料庫操作：連線、查詢、使用者脈絡同步。
"""

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from backend.config import (
    ENABLE_LLM_GRAPH_PLANNER,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)
from backend.models import (
    ChatMessage,
    ChatUserContext,
    Extracted,
    GraphQueryPlan,
    SemanticUnderstanding,
)
from backend.services.extraction import (
    get_client_location_text,
    normalize_category_name,
    normalize_location_candidate,
)
from backend.services.llm import call_llm, llm_is_ready, parse_llm_json_text


# ======================
# 情緒對應表
# ======================

GRAPH_EMOTION_MAP = {
    "panic": "慌張",
    "fearful": "害怕",
    "sad": "難過",
    "angry": "生氣",
    "neutral": "平穩",
    "unknown": None,
}


# ======================
# 連線工具
# ======================

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


# ======================
# 關鍵字查詢
# ======================

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


# ======================
# 情緒正規化
# ======================

def normalize_graph_emotion(emotion: Optional[str]) -> Optional[str]:
    if not emotion:
        return None

    normalized = GRAPH_EMOTION_MAP.get(emotion.strip().lower())
    if normalized:
        return normalized

    cleaned = emotion.strip()
    return cleaned or None


# ======================
# 使用者身份建構
# ======================

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


# ======================
# 圖譜查詢規劃
# ======================

def build_fallback_graph_query_plan(
    messages: List[ChatMessage],
    conversation_state: Extracted,
    audio_context: Optional[Dict[str, Any]] = None,
) -> GraphQueryPlan:
    from backend.models import latest_user_text
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

    if not ENABLE_LLM_GRAPH_PLANNER or not llm_is_ready():
        return fallback

    from backend.models import latest_user_text
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

        data = parse_llm_json_text(result_text)
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


# ======================
# Cypher 生成與查詢
# ======================

def build_knowledge_graph_cypher(plan: GraphQueryPlan) -> tuple:
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


# ======================
# 提示詞建構
# ======================

def build_neo4j_hint(
    plan: GraphQueryPlan,
    graph_knowledge: Dict[str, Any],
    user_graph_context: Dict[str, Any],
) -> str:
    lines: List[str] = []

    if graph_knowledge:
        lines.append("知識圖譜查詢結果：")
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


# ======================
# 對話狀態同步
# ======================

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
