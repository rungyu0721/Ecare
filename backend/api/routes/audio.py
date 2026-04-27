"""
/audio 路由：語音轉文字 + 情緒辨識。
"""

import os
import subprocess
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.services.emotion import (
    build_audio_analysis_summary,
    emotion_risk_adjustment,
    predict_emotion_from_wav,
)
from backend.services.extraction import (
    generate_incident_summary,
    get_dispatch_advice,
    simple_extract,
)
from backend.services.risk import apply_structured_risk_floor, simple_risk
from backend.services.speech import fix_transcript

router = APIRouter()


def build_audio_analysis_result(transcript: str, emotion: str, emotion_score: float):
    score, level = simple_risk(transcript)
    ex = simple_extract(transcript)

    score = min(1.0, score + emotion_risk_adjustment(emotion, emotion_score))

    score, level = apply_structured_risk_floor(transcript, ex, score, level)
    if not ex.dispatch_advice:
        ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
    ex.description = generate_incident_summary(ex, level)
    analysis_summary = build_audio_analysis_summary(transcript, emotion, level, ex.category)

    return {
        "situation": ex.category or "待確認",
        "risk_score": round(score, 2),
        "risk_level": level,
        "should_escalate": level == "High",
        "analysis_summary": analysis_summary,
        "extracted": ex.model_dump()
    }


@router.post("/audio")
async def audio_to_text(audio: UploadFile = File(...)):
    import backend.services.speech as _speech_mod
    import backend.services.emotion as _emotion_mod

    if _speech_mod.WHISPER_MODEL is None:
        raise HTTPException(status_code=503, detail="Whisper model 尚未載入完成")

    if _emotion_mod.EMOTION_MODEL is None:
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
        result = _speech_mod.WHISPER_MODEL.transcribe(
            tmp_wav,
            language="zh",
            fp16=False,
            temperature=0.0,
            initial_prompt=_speech_mod.WHISPER_EMERGENCY_INITIAL_PROMPT,
        )
        raw_text = (result.get("text") or "").strip()
        text = fix_transcript(raw_text)
        if raw_text:
            print(f"🎙️ Whisper 原始轉錄：{raw_text}")
        if text and text != raw_text:
            print(f"🛠️ 轉錄修正後：{text}")

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
            "should_escalate": final_result["should_escalate"],
            "analysis_summary": final_result["analysis_summary"],
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
                except Exception:
                    pass
