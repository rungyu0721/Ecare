"""Proxy local TTS service audio through the E-CARE backend."""

from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.error
import urllib.request
from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from backend.config import TTS_BASE_URL, TTS_TIMEOUT_SECONDS
from backend.models import TtsRequest

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory pre-synthesis cache
# key → {"task": asyncio.Task, "audio": bytes|None}
# Keyed by SHA-256 prefix of voice_prompt text so identical prompts reuse the
# same synthesis result across concurrent requests.
# ---------------------------------------------------------------------------
_prefetch_cache: dict[str, dict] = {}
_CACHE_MAX = 64


def make_tts_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


async def _synthesize_to_cache(text: str, key: str) -> None:
    req = TtsRequest(text=text, mode="zero-shot")
    try:
        audio, _ = await asyncio.to_thread(_call_local_tts, req)
        _prefetch_cache[key]["audio"] = audio
    except Exception:
        _prefetch_cache[key]["audio"] = None
    finally:
        _prefetch_cache[key]["event"].set()


def schedule_prefetch(text: str, key: str) -> None:
    """Start background TTS synthesis if not already scheduled."""
    if key in _prefetch_cache:
        return
    if len(_prefetch_cache) >= _CACHE_MAX:
        # Evict the oldest entry
        oldest = next(iter(_prefetch_cache))
        _prefetch_cache.pop(oldest, None)
    _prefetch_cache[key] = {"event": asyncio.Event(), "audio": None}
    asyncio.create_task(_synthesize_to_cache(text, key))


# ---------------------------------------------------------------------------
# Internal HTTP helper
# ---------------------------------------------------------------------------

def _call_local_tts(req: TtsRequest) -> tuple[bytes, dict[str, str]]:
    url = TTS_BASE_URL.rstrip("/") + "/tts"
    payload: dict[str, object] = {
        "text": req.text,
        "mode": req.mode,
    }
    if req.speed is not None:
        payload["speed"] = req.speed

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "audio/wav",
        },
    )

    with urllib.request.urlopen(request, timeout=TTS_TIMEOUT_SECONDS) as response:
        audio = response.read()
        headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower().startswith("x-ecare-tts-")
        }
        return audio, headers


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/tts")
async def synthesize_tts(req: TtsRequest) -> Response:
    import time as _time
    _t0 = _time.perf_counter()
    try:
        audio, headers = await asyncio.to_thread(_call_local_tts, req)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=502,
            detail=f"Local TTS service returned {exc.code}: {detail}",
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local TTS service is not available at {TTS_BASE_URL}: {exc}",
        ) from exc

    if not audio:
        raise HTTPException(status_code=502, detail="Local TTS service returned empty audio.")

    elapsed = _time.perf_counter() - _t0
    tts_sec = headers.get("x-ecare-tts-seconds", "?")
    text_preview = req.text[:30].replace("\n", " ")
    print(f"[TTS] {elapsed:.2f}s total | synthesis={tts_sec}s | {len(audio)//1024}KB | \"{text_preview}...\"")

    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'inline; filename="ecare_voice_prompt.wav"',
            **headers,
        },
    )


@router.get("/tts/ready/{key}")
async def get_prefetched_tts(key: str) -> Response:
    """Return pre-synthesized audio for *key* (from /chat tts_key field).

    Blocks until synthesis completes or times out.  Flutter calls this
    immediately after receiving the chat response so the wait overlaps with
    the time spent rendering the text reply.
    """
    entry = _prefetch_cache.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="TTS key not found or expired.")

    try:
        await asyncio.wait_for(asyncio.shield(entry["event"].wait()), timeout=45.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TTS synthesis timed out.")

    audio: Optional[bytes] = entry.get("audio")
    if not audio:
        raise HTTPException(status_code=502, detail="TTS synthesis failed for this key.")

    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="ecare_voice_prompt.wav"'},
    )
