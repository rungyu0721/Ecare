"""
E-CARE FastAPI 應用程式入口。

此檔案為精簡版主程式，負責：
1. 建立 FastAPI app 與 CORS
2. 掛載路由
3. 啟動時初始化所有服務
4. 重新導出所有符號以維持 backend.main 的向下相容性
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.audio import build_audio_analysis_result  # noqa: F401
from backend.api.routes.audio import router as audio_router
from backend.api.routes.chat import router as chat_router
from backend.api.routes.reports import router as reports_router
from backend.config import (  # noqa: F401
    CHAT_CONTEXT_TURNS,
    COMPACT_LOCAL_LLM_MAX_TOKENS,
    ENABLE_LLM_GRAPH_PLANNER,
    ENABLE_LLM_SEMANTIC_UNDERSTANDING,
    FOLLOWUP_CONTEXT_TURNS,
    LLM_MODEL_NAME,
    LLM_PROVIDER,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MAX_TOKENS,
    WARMUP_LLM_ON_STARTUP,
)
from backend.db.neo4j_db import (  # noqa: F401
    GRAPH_EMOTION_MAP,
    build_fallback_graph_query_plan,
    build_graph_user_identity,
    build_knowledge_graph_cypher,
    build_neo4j_hint,
    check_neo4j,
    graph_reasoning_from_context,
    normalize_graph_emotion,
    query_neo4j_by_keyword,
    query_neo4j_by_plan,
    query_neo4j_user_context,
    sync_chat_state_to_neo4j,
)
from backend.db.postgres import (  # noqa: F401
    build_user_item,
    ensure_db_available,
    find_existing_user_id,
    get_db,
    init_db,
    make_id,
    now_str,
)
from backend.models import (  # noqa: F401
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUserContext,
    DialogueState,
    Extracted,
    GraphQueryPlan,
    LLMTextResponse,
    ReportCreate,
    ReportItem,
    SemanticEntities,
    SemanticUnderstanding,
    UserCreate,
    UserItem,
    latest_user_text,
    model_to_dict,
)
from backend.services.chat import llm_chat, llm_chat_with_audio  # noqa: F401
from backend.services.dialogue import (  # noqa: F401
    build_dialogue_state,
    get_last_turn_context,
    is_brief_non_emergency_text,
    is_generic_intake_text,
    is_greeting_or_opening_text,
    log_chat_debug,
    next_question,
    should_skip_graph_lookup,
    should_use_compact_chat_path,
)
from backend.services.emotion import (  # noqa: F401
    build_audio_analysis_summary,
    emotion_risk_adjustment,
    init_emotion,
    predict_emotion_from_wav,
)
from backend.services.extraction import (  # noqa: F401
    apply_turn_context,
    asks_about_danger,
    asks_about_injury,
    asks_about_location,
    asks_about_weapon,
    build_incident_acknowledgement,
    build_medical_acknowledgement,
    enrich_extracted_details,
    extract_conversation_state,
    extract_location_from_text,
    generate_incident_summary,
    get_client_location_text,
    get_dispatch_advice,
    is_likely_incident_detail,
    is_likely_location_response,
    medical_follow_up_question,
    merge_extracted,
    normalize_category_name,
    normalize_location_candidate,
    simple_extract,
)
from backend.services.llm import (  # noqa: F401
    call_llm,
    init_llm,
    llm_is_ready,
    local_llm_provider_label,
    parse_llm_json_text,
    warmup_llm,
)
from backend.services.postprocess import (  # noqa: F401
    adapt_opening_turn_response,
    apply_semantic_tone,
    contextualize_reply_and_question,
    next_question_from_semantic,
    sanitize_reply_and_question,
)
from backend.services.risk import (  # noqa: F401
    apply_structured_risk_floor,
    has_high_risk_context_signal,
    simple_risk,
)
from backend.services.semantic import (  # noqa: F401
    get_audio_emotion,
    get_audio_emotion_score,
    has_high_urgency_audio_emotion,
    heuristic_semantic_understanding,
    semantic_understanding_from_payload,
    semantic_understanding_from_text,
    should_use_llm_semantic_understanding,
)
from backend.services.speech import (  # noqa: F401
    WHISPER_EMERGENCY_INITIAL_PROMPT,
    fix_transcript,
    init_speech,
)

# Backward-compat alias
COMPACT_GEMMA_MAX_TOKENS = COMPACT_LOCAL_LLM_MAX_TOKENS  # noqa: F401

# ======================
# App 建立
# ======================

app = FastAPI()

ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://10.0.2.2",
    "http://10.0.2.2:8000",
    "http://192.168.50.223",
    "http://192.168.50.223:5500",
    "capacitor://localhost",
    "ionic://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發期間允許全部，上線前改回 ALLOWED_ORIGINS
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(audio_router)
app.include_router(reports_router)


# ======================
# 啟動初始化
# ======================

@app.on_event("startup")
def load_models():
    init_llm()
    init_speech()
    init_emotion()
    check_neo4j()
    warmup_llm()

    print(
        "ℹ️ Chat latency config:"
        f" context_turns={CHAT_CONTEXT_TURNS},"
        f" followup_turns={FOLLOWUP_CONTEXT_TURNS},"
        f" graph_planner={'on' if ENABLE_LLM_GRAPH_PLANNER else 'off'},"
        f" semantic_llm={'on' if ENABLE_LLM_SEMANTIC_UNDERSTANDING else 'off'},"
        f" local_llm_max_tokens={LOCAL_LLM_MAX_TOKENS},"
        f" compact_local_llm_max_tokens={COMPACT_LOCAL_LLM_MAX_TOKENS},"
        f" warmup={'on' if WARMUP_LLM_ON_STARTUP else 'off'}"
    )


if os.getenv("ECARE_SKIP_INIT_DB", "0") != "1":
    init_db()
