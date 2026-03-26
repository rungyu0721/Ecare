from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal, Optional, Dict, Any
import whisper
import tempfile
import subprocess
import os
import time
import random
import json
import numpy as np
import librosa
import joblib

# Gemini
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


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    audio_context: Optional[Dict[str, Any]] = None


class Extracted(BaseModel):
    category: Optional[str] = None
    location: Optional[str] = None
    people_injured: Optional[bool] = None
    weapon: Optional[bool] = None
    danger_active: Optional[bool] = None
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

REPORTS = []


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


def now_str():
    return time.strftime("%Y/%m/%d %H:%M", time.localtime())


def make_id(prefix="A"):
    return f"{prefix}{random.randint(100, 999)}"


# ======================
# 模型初始化
# ======================

WHISPER_MODEL = None
GEMINI_CLIENT = None
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMOTION_MODEL = None

@app.on_event("startup")
def load_models():
    global WHISPER_MODEL, GEMINI_CLIENT, EMOTION_MODEL

    if WHISPER_MODEL is None:
        WHISPER_MODEL = whisper.load_model("base")

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("google_api_key")
    if api_key:
        GEMINI_CLIENT = genai.Client(api_key=api_key)
        print("✅ Gemini 已初始化")
    else:
        print("⚠️ 找不到 GOOGLE_API_KEY，/chat 將使用 fallback")

    try:
        EMOTION_MODEL = joblib.load("backend/emotion_model.pkl")
        print("✅ Emotion model 已載入")
    except Exception as e:
        EMOTION_MODEL = None
        print(f"⚠️ Emotion model 載入失敗：{e}")


def call_gemini(contents: str):
    if GEMINI_CLIENT is None:
        raise RuntimeError("Gemini client not ready")

    fallback_models = []
    for model_name in [
        GEMINI_MODEL_NAME,
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

def simple_extract(text: str) -> Extracted:
    ex = Extracted(description=text)

    if any(k in text for k in ["火災", "失火", "著火", "起火", "冒煙", "燒起來"]):
        ex.category = "火災"
    elif any(k in text for k in ["可疑", "跟蹤", "怪人", "鬼鬼祟祟", "闖入"]):
        ex.category = "可疑人士"
    elif any(k in text for k in ["噪音", "很吵", "吵鬧", "施工", "喧嘩"]):
        ex.category = "噪音"
    elif any(k in text for k in ["昏倒", "流血", "受傷", "沒呼吸", "抽搐", "心臟痛"]):
        ex.category = "醫療急症"
    elif any(k in text for k in ["打架", "刀", "砍", "威脅", "家暴", "被打"]):
        ex.category = "暴力事件"
    elif any(k in text for k in ["車禍", "撞車", "翻車", "追撞"]):
        ex.category = "交通事故"
    else:
        ex.category = "待確認"

    if any(k in text for k in ["流血", "受傷", "昏倒", "沒呼吸", "抽搐", "骨折"]):
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
            ex.location = text[idx: idx + 25].strip(" ：:，,。. ")
            break

    ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
    return ex


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
    if not ex.location:
        return "請問事發地點在哪裡？"

    if ex.category == "待確認":
        return "請問是火災、可疑人士、噪音、醫療急症、暴力事件，還是交通事故？"

    if ex.people_injured is None and ex.category in ["醫療急症", "暴力事件", "交通事故", "火災"]:
        return "現場有人受傷、失去意識，或需要醫療協助嗎？"

    if ex.weapon is None and ex.category == "暴力事件":
        return "現場對方有持刀、棍棒或其他武器嗎？"

    if ex.danger_active is None and risk_level in ["Medium", "High"]:
        return "目前危險還在持續嗎？對方或事件還在現場嗎？"

    return "可以再補充目前現場的狀況嗎？"


# ======================
# 案件摘要生成
# ======================

def generate_incident_summary(ex: Extracted, risk_level: str) -> str:
    summary = []

    summary.append(f"案件類型：{ex.category or '待確認'}")
    summary.append(f"地點：{ex.location or '未提供'}")

    if ex.people_injured:
        summary.append("傷勢：現場有人受傷或需要醫療協助")

    if ex.weapon:
        summary.append("注意：現場可能有武器")

    if ex.danger_active:
        summary.append("危險狀況：事件仍在持續")

    summary.append(f"風險等級：{risk_level}")
    summary.append(ex.dispatch_advice or "建議派遣：待確認")

    return " | ".join(summary)


# ======================
# Gemini 分析
# ======================

def gemini_chat(messages: List[ChatMessage]) -> Dict[str, Any]:
    if GEMINI_CLIENT is None:
        raise RuntimeError("Gemini 未初始化")

    recent = messages[-10:]
    context = "\n".join(
        f"{'使用者' if m.role == 'user' else '助手'}：{m.content}"
        for m in recent
    )

    prompt = f"""
你是 E-CARE 緊急事件報案助手。

請根據以下對話，輸出嚴格 JSON，不要加入其他文字。
請使用繁體中文。
如果資訊不確定請填 null，不要自行猜測。

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

    resp = call_gemini(prompt)

    text = (resp.text or "").strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    data = json.loads(text)
    return data


def gemini_chat_with_audio(messages: List[ChatMessage], audio_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if GEMINI_CLIENT is None:
        raise RuntimeError("Gemini client not ready")

    recent = messages[-10:]
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
        }
        audio_context_text = json.dumps(safe_audio_context, ensure_ascii=False)

    prompt = f"""
你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。

回覆原則：
- 先簡短接住使用者情緒，再提供實際協助
- 若資訊不足，一次只追問一個最重要的問題
- 如果風險高，優先確認安全、位置、是否有人受傷
- reply 一律使用繁體中文，自然口語，不要寫得像表單或系統訊息
- 只能輸出 JSON，不要加註解或 markdown

category 只能是：
- 火災
- 暴力傷害
- 自殺風險
- 車禍傷病
- 持械威脅
- 其他危急事件
- 未知

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
    "dispatch_advice": "string|null",
    "description": "string|null"
  }}
}}

風險判斷原則：
- 明確人身危險、武器、火勢、持續暴力、重傷，傾向 High
- 有受傷、威脅、自傷風險、狀況未明但令人擔心，傾向 Medium
- 單純諮詢、情緒低落但無立即危險，傾向 Low

最新語音分析：
{audio_context_text}

對話內容：
{context}
"""

    resp = call_gemini(prompt)

    text = (resp.text or "").strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def semantic_understanding_from_text(
    text: str,
    audio_context: Optional[Dict[str, Any]] = None,
    extracted: Optional[Extracted] = None
) -> SemanticUnderstanding:
    fallback_entities = SemanticEntities(
        location=(extracted.location if extracted else None),
        injured=(extracted.people_injured if extracted else None),
        weapon=(extracted.weapon if extracted else None),
        danger_active=(extracted.danger_active if extracted else None),
    )

    if not text.strip():
        return SemanticUnderstanding(entities=fallback_entities)

    if GEMINI_CLIENT is None:
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

    resp = call_gemini(prompt)

    result_text = (resp.text or "").strip()
    if result_text.startswith("```"):
        result_text = result_text.replace("```json", "").replace("```", "").strip()

    try:
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
            ),
            semantic=SemanticUnderstanding()
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
        data = gemini_chat_with_audio(req.messages, req.audio_context)
        extracted = data.get("extracted", {}) or {}

        ex = Extracted(
            category=extracted.get("category"),
            location=extracted.get("location"),
            people_injured=extracted.get("people_injured"),
            weapon=extracted.get("weapon"),
            danger_active=extracted.get("danger_active"),
            dispatch_advice=extracted.get("dispatch_advice"),
            description=extracted.get("description"),
        )

        risk_score = float(data.get("risk_score", 0.2))
        risk_score = max(0.0, min(1.0, risk_score))

        risk_level = data.get("risk_level", "Low")
        if risk_level not in ["Low", "Medium", "High"]:
            risk_level = "Low"

        should_escalate = bool(data.get("should_escalate", risk_level == "High"))

        if not ex.dispatch_advice:
            ex.dispatch_advice = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)

        summary = generate_incident_summary(ex, risk_level)
        ex.description = summary
        semantic = semantic_understanding_from_text(context, req.audio_context, ex)

        reply = data.get("reply") or "我會一步一步協助你整理資訊。"
        nq = data.get("next_question") or next_question(ex, risk_level)
        reply = apply_semantic_tone(reply, semantic, risk_level)
        nq = next_question_from_semantic(nq, semantic, ex, risk_level)

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
        print("Gemini fallback:", str(e))

        score, level = simple_risk(context)
        ex = simple_extract(context)
        summary = generate_incident_summary(ex, level)
        ex.description = summary
        semantic = semantic_understanding_from_text(context, req.audio_context, ex)
        if level == "High":
            reply = "我了解你現在很緊張，我會快速協助你整理資訊並引導你進行通報。"
        elif level == "Medium":
            reply = "我了解你的狀況，我會一步步協助你整理必要資訊。"
        else:
            reply = "我在這裡，我會協助你把事情講清楚。"

        reply = apply_semantic_tone(reply, semantic, level)
        follow_up = next_question_from_semantic(next_question(ex, level), semantic, ex, level)

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
    return REPORTS[::-1]


@app.post("/reports", response_model=ReportItem)
def create_report(payload: ReportCreate):
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
    REPORTS.append(item)
    return item






