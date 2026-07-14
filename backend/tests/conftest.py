"""
在 ML 服務被 import 之前注入輕量 mock，
讓單元測試不依賴 GPU、模型檔案或外部服務。
conftest.py 由 pytest 在所有 test module 之前載入，確保 mock 先生效。
"""
import sys
from types import ModuleType
from unittest.mock import MagicMock


def _inject(name: str, **attrs) -> None:
    if name in sys.modules:
        return
    m = MagicMock(spec=ModuleType(name))
    m.__name__ = name
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m


# emotion service — 需要 torch + scikit-learn + emotion_model.pkl
_inject(
    "backend.services.emotion",
    init_emotion=MagicMock(),
    predict_emotion_from_wav=MagicMock(return_value=("neutral", 0.5)),
    build_audio_analysis_summary=MagicMock(return_value={}),
    emotion_risk_adjustment=MagicMock(return_value=0.0),
    has_high_urgency_emotion_value=lambda e, s=None: False,
    has_high_urgency_emotion_value_from_score=lambda s: False,
    normalize_emotion_score=lambda s: 0.5,
)

# speech service — 需要 openai-whisper + ffmpeg
_inject(
    "backend.services.speech",
    init_speech=MagicMock(),
    fix_transcript=lambda t, **kw: t,
    WHISPER_EMERGENCY_INITIAL_PROMPT="",
)

def _extract_json_object_text(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start: end + 1]
    return text


# llm service — 需要網路 / Ollama
_inject(
    "backend.services.llm",
    init_llm=MagicMock(),
    call_llm=MagicMock(return_value=None),
    llm_is_ready=MagicMock(return_value=False),
    warmup_llm=MagicMock(),
    parse_llm_json_text=MagicMock(return_value={}),
    local_llm_provider_label=MagicMock(return_value="mock"),
    extract_json_object_text=_extract_json_object_text,
)
