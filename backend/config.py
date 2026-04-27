"""
集中管理所有環境變數與設定值。
其他模組請從此處 import，不要直接呼叫 os.getenv。
"""

import os
from typing import List, Optional


# ======================
# 環境變數輔助函式
# ======================

def env_int(
    name: str,
    default: int,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_text(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        normalized = raw.strip()
        if normalized:
            return normalized
    return default


def env_int_alias(
    names: List[str],
    default: int,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    for name in names:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            continue
        return env_int(name, default, minimum=minimum, maximum=maximum)
    value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


# ======================
# PostgreSQL 設定
# ======================

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "ecare_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ======================
# Neo4j 設定
# ======================

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# ======================
# LLM 設定
# ======================

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
LLM_MODEL_NAME = os.getenv(
    "LLM_MODEL",
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
)
LOCAL_LLM_BASE_URL = env_text("OLLAMA_BASE_URL", "GEMMA_BASE_URL")
LOCAL_LLM_API_KEY = env_text("OLLAMA_API_KEY", "GEMMA_API_KEY")
LOCAL_LLM_CHAT_PATH = env_text("OLLAMA_CHAT_PATH", "GEMMA_CHAT_PATH")
LOCAL_LLM_MAX_TOKENS = env_int_alias(
    ["OLLAMA_MAX_TOKENS", "GEMMA_MAX_TOKENS"],
    256,
    minimum=64,
    maximum=1024,
)
COMPACT_LOCAL_LLM_MAX_TOKENS = env_int_alias(
    ["COMPACT_OLLAMA_MAX_TOKENS", "COMPACT_GEMMA_MAX_TOKENS"],
    320,
    minimum=96,
    maximum=512,
)

# 向下相容舊名稱
GEMMA_BASE_URL = LOCAL_LLM_BASE_URL
GEMMA_API_KEY = LOCAL_LLM_API_KEY
GEMMA_CHAT_PATH = LOCAL_LLM_CHAT_PATH
GEMMA_MAX_TOKENS = LOCAL_LLM_MAX_TOKENS
COMPACT_GEMMA_MAX_TOKENS = COMPACT_LOCAL_LLM_MAX_TOKENS

# ======================
# 對話設定
# ======================

CHAT_CONTEXT_TURNS = env_int("CHAT_CONTEXT_TURNS", 6, minimum=2, maximum=10)
FOLLOWUP_CONTEXT_TURNS = env_int("FOLLOWUP_CONTEXT_TURNS", 4, minimum=2, maximum=6)

ENABLE_LLM_GRAPH_PLANNER = env_flag("ENABLE_LLM_GRAPH_PLANNER", default=False)
ENABLE_LLM_SEMANTIC_UNDERSTANDING = env_flag("ENABLE_LLM_SEMANTIC_UNDERSTANDING", default=False)
WARMUP_LLM_ON_STARTUP = env_flag("WARMUP_LLM_ON_STARTUP", default=True)
