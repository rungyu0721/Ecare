"""
情緒辨識服務：音頻特徵抽取 + RandomForest 情緒預測。
"""

from typing import Optional

import numpy as np

# 情緒模型（啟動時初始化）
EMOTION_MODEL = None


# ======================
# 音頻特徵抽取
# ======================

def extract_emotion_features(wav_path: str) -> np.ndarray:
    import librosa
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


# ======================
# 情緒預測
# ======================

def predict_emotion_from_wav(wav_path: str) -> dict:
    global EMOTION_MODEL

    if EMOTION_MODEL is None:
        return {"emotion": "unknown", "emotion_score": 0.0}

    feats = extract_emotion_features(wav_path)
    pred = EMOTION_MODEL.predict(feats)[0]

    try:
        proba = EMOTION_MODEL.predict_proba(feats)[0]
        score = float(np.max(proba))
    except Exception:
        score = 0.60

    # fearful 分數高時升級為 panic
    if pred == "fearful" and score >= 0.75:
        final_emotion = "panic"
    else:
        final_emotion = pred

    return {
        "emotion": final_emotion,
        "emotion_score": round(score, 2),
    }


# ======================
# 情緒輔助函式
# ======================

def localize_audio_emotion(emotion: str) -> str:
    mapping = {
        "panic": "非常慌張",
        "fearful": "害怕",
        "sad": "低落難受",
        "angry": "激動",
        "neutral": "相對平穩",
        "unknown": "情緒待確認",
    }
    return mapping.get((emotion or "").strip().lower(), emotion or "情緒待確認")


def normalize_emotion_score(emotion_score: float) -> float:
    try:
        score = float(emotion_score)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def emotion_risk_adjustment(emotion: str, emotion_score: float) -> float:
    normalized_emotion = (emotion or "").strip().lower()
    score = normalize_emotion_score(emotion_score)

    if normalized_emotion in ["panic", "fearful"]:
        return 0.16 if score >= 0.8 else 0.12
    if normalized_emotion == "angry":
        return 0.1 if score >= 0.7 else 0.06
    if normalized_emotion == "sad":
        return 0.07 if score >= 0.7 else 0.04
    return 0.0


def has_high_urgency_emotion_value(emotion: str, emotion_score: float) -> bool:
    normalized_emotion = (emotion or "").strip().lower()
    score = normalize_emotion_score(emotion_score)

    if normalized_emotion == "panic":
        return True
    if normalized_emotion == "fearful" and score >= 0.72:
        return True
    return False


def summarize_transcript_for_audio_reply(transcript: str, max_length: int = 20) -> str:
    import re as _re
    cleaned = _re.sub(r"\s+", " ", (transcript or "")).strip()
    if not cleaned:
        return "剛剛的語音"
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[:max_length].rstrip()}..."


def build_audio_analysis_summary(
    transcript: str,
    emotion: str,
    risk_level: str,
    situation: Optional[str],
) -> str:
    snippet = summarize_transcript_for_audio_reply(transcript)
    emotion_text = localize_audio_emotion(emotion)
    situation_text = situation or "目前狀況"

    if risk_level == "High":
        return (
            f"我有聽到你提到「{snippet}」，從語音情緒與內容判斷目前可能是緊急狀況，"
            "我會優先協助確認安全、位置，以及是否需要立即通報。"
        )

    if risk_level == "Medium":
        return (
            f"我有收到這段語音，聽起來你現在可能有些{emotion_text}，"
            f"我先幫你整理成{situation_text}的重點，再一起確認下一步。"
        )

    return (
        f"我有收到你的語音內容，先幫你整理成{situation_text}的重點；"
        "如果情況有變化，也可以再直接補充。"
    )


# ======================
# 初始化
# ======================

def init_emotion() -> None:
    global EMOTION_MODEL
    try:
        import joblib
        EMOTION_MODEL = joblib.load("backend/emotion_model.pkl")
        print("✅ Emotion model 已載入")
    except Exception as exc:
        EMOTION_MODEL = None
        print(f"⚠️ Emotion model 載入失敗：{exc}")
