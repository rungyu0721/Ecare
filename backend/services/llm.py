"""
LLM provider 抽象層：Gemini / Ollama / Gemma。
同時包含 LLM 輸出的 JSON 解析工具函式。
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from backend.config import (
    COMPACT_LOCAL_LLM_MAX_TOKENS,
    LOCAL_LLM_API_KEY,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_CHAT_PATH,
    LOCAL_LLM_MAX_TOKENS,
    LLM_MODEL_NAME,
    LLM_PROVIDER,
    WARMUP_LLM_ON_STARTUP,
)
from backend.models import LLMTextResponse

# Gemini client（啟動時初始化）
GEMINI_CLIENT = None


# ======================
# JSON 解析工具
# ======================

def strip_llm_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned


def extract_json_object_text(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start: end + 1]
    return text


def preview_text(text: str, limit: int = 140) -> str:
    normalized = (text or "").strip().replace("\n", " ")
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def parse_llm_json_text(text: str) -> Dict[str, Any]:
    cleaned = strip_llm_code_fence(text)
    candidates: List[str] = []

    for candidate in [cleaned, extract_json_object_text(cleaned)]:
        normalized = candidate.strip()
        if not normalized or normalized in candidates:
            continue
        candidates.append(normalized)

        without_trailing_commas = re.sub(r",\s*([}\]])", r"\1", normalized)
        if without_trailing_commas not in candidates:
            candidates.append(without_trailing_commas)

    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    if cleaned and not cleaned.rstrip().endswith("}"):
        raise RuntimeError(
            f"LLM JSON parse failed: response may be truncated ({last_error}); raw={preview_text(cleaned)}"
        ) from last_error
    raise RuntimeError(
        f"LLM JSON parse failed: {last_error}; raw={preview_text(cleaned)}"
    ) from last_error


# ======================
# Provider 判斷
# ======================

def llm_is_ready() -> bool:
    if LLM_PROVIDER == "gemini":
        return GEMINI_CLIENT is not None
    if LLM_PROVIDER in {"gemma", "ollama"}:
        return bool(LOCAL_LLM_BASE_URL and LLM_MODEL_NAME)
    return False


def local_llm_provider_label() -> str:
    if LLM_PROVIDER == "ollama":
        return "Ollama"
    return "Gemma"


def build_local_llm_endpoint(base_url: str) -> str:
    normalized_base_url = (base_url or "").rstrip("/")
    if LOCAL_LLM_CHAT_PATH:
        path = (
            LOCAL_LLM_CHAT_PATH
            if LOCAL_LLM_CHAT_PATH.startswith("/")
            else f"/{LOCAL_LLM_CHAT_PATH}"
        )
    elif normalized_base_url.endswith("/v1"):
        path = "/chat/completions"
    else:
        path = "/v1/chat/completions"
    return f"{normalized_base_url}{path}"


# ======================
# LLM 呼叫
# ======================

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
                contents=contents,
            )
        except Exception as exc:
            last_error = exc
            print(f"Gemini model failed: {model_name} -> {exc}")

    raise last_error if last_error else RuntimeError("Gemini generate_content failed")


def call_local_llm(contents: str, *, max_tokens: Optional[int] = None):
    provider_label = local_llm_provider_label()
    if not LOCAL_LLM_BASE_URL or not LLM_MODEL_NAME:
        raise RuntimeError(f"{provider_label} provider not configured")

    endpoint = build_local_llm_endpoint(LOCAL_LLM_BASE_URL)
    payload = {
        "model": LLM_MODEL_NAME,
        "messages": [{"role": "user", "content": contents}],
        "temperature": 0.1,
        "max_tokens": max_tokens or LOCAL_LLM_MAX_TOKENS,
        "stream": False,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **(
                {"Authorization": f"Bearer {LOCAL_LLM_API_KEY}"}
                if LOCAL_LLM_API_KEY
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
        raise RuntimeError(f"{provider_label} HTTP error: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{provider_label} connection failed: {exc}") from exc

    try:
        text = body["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(
                part.get("text", "")
                for part in text
                if isinstance(part, dict)
            )
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{provider_label} response format not recognized: {body}") from exc

    if not isinstance(text, str):
        raise RuntimeError(f"{provider_label} content format not recognized: {body}")

    return LLMTextResponse(text=text)


def call_gemma(contents: str, *, max_tokens: Optional[int] = None):
    return call_local_llm(contents, max_tokens=max_tokens)


def call_llm(contents: str, *, max_tokens: Optional[int] = None):
    if LLM_PROVIDER == "gemini":
        return call_gemini(contents)
    if LLM_PROVIDER in {"gemma", "ollama"}:
        return call_local_llm(contents, max_tokens=max_tokens)
    raise RuntimeError(f"Unsupported LLM provider: {LLM_PROVIDER}")


# ======================
# 預熱
# ======================

def warmup_llm() -> None:
    if not llm_is_ready() or not WARMUP_LLM_ON_STARTUP:
        return

    prompt = """
請只輸出一行合法 JSON，不要加其他文字：
{"ok":true}
"""
    started_at = time.perf_counter()
    try:
        response = call_llm(prompt)
        payload = parse_llm_json_text(response.text or "")
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        print(f"✅ LLM 預熱完成：{payload} ({elapsed_ms} ms)")
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        print(f"⚠️ LLM 預熱失敗（{elapsed_ms} ms）：{exc}")


# ======================
# 初始化
# ======================

def init_llm() -> None:
    global GEMINI_CLIENT
    if LLM_PROVIDER == "gemini":
        try:
            from google import genai
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("google_api_key")
            if api_key:
                GEMINI_CLIENT = genai.Client(api_key=api_key)
                print(f"✅ LLM 已初始化：Gemini ({LLM_MODEL_NAME})")
            else:
                print("⚠️ 找不到 GOOGLE_API_KEY，/chat 將使用 fallback")
        except Exception as exc:
            print(f"⚠️ Gemini 初始化失敗：{exc}")
    elif LLM_PROVIDER in {"gemma", "ollama"}:
        provider_label = local_llm_provider_label()
        if LOCAL_LLM_BASE_URL and LLM_MODEL_NAME:
            print(f"✅ LLM 已設定：{provider_label} ({LLM_MODEL_NAME}) @ {LOCAL_LLM_BASE_URL}")
        else:
            print(f"⚠️ {provider_label} provider 未完整設定，/chat 將使用 fallback")
    else:
        print(f"⚠️ 不支援的 LLM_PROVIDER={LLM_PROVIDER}，/chat 將使用 fallback")
