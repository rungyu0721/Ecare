"""
語音轉文字服務：Whisper 模型載入與轉錄。
同時包含轉錄後處理（錯別字修正）。
"""

import re
from typing import Optional

# Whisper 模型（啟動時初始化）
WHISPER_MODEL = None

# ======================
# 轉錄修正詞典
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

WHISPER_EMERGENCY_INITIAL_PROMPT = (
    "這是一段緊急求助與報案語音。"
    "常見詞包含：有人拿刀、持刀、刀子、槍、武器、打架、威脅、家暴、闖入、"
    "可疑人士、跟蹤、救命、流血、昏倒、沒呼吸、呼吸困難、火災、失火、車禍。"
)

WEAPON_TRANSCRIPT_PATTERNS = [
    (
        re.compile(
            r"(有人|對方|他|她|有個人|那個人|一個人)(拿到|那到|拿道|那道)"
            r"(?=(?:.{0,8}(怎麼辦|要怎麼辦|在追|追我|衝過來|靠近|威脅|要砍|砍人|攻擊|救命|很危險|在門口|在外面)))"
        ),
        r"\1拿刀",
    ),
    (
        re.compile(
            r"(有人|對方|他|她|有個人|那個人|一個人)(持到|持道)"
            r"(?=(?:.{0,8}(怎麼辦|要怎麼辦|在追|追我|衝過來|靠近|威脅|要砍|砍人|攻擊|救命|很危險|在門口|在外面)))"
        ),
        r"\1持刀",
    ),
    (
        re.compile(r"(拿到|那到|拿道|那道)(刀子|美工刀|水果刀)"),
        r"拿刀\2",
    ),
]


def normalize_emergency_transcript(text: str) -> str:
    normalized = text
    for pattern, replacement in WEAPON_TRANSCRIPT_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def fix_transcript(text: str) -> str:
    text = text.strip()
    for wrong, correct in COMMON_FIXES.items():
        text = text.replace(wrong, correct)
    return normalize_emergency_transcript(text)


# ======================
# 初始化
# ======================

def init_speech() -> None:
    global WHISPER_MODEL
    if WHISPER_MODEL is None:
        try:
            import whisper
            WHISPER_MODEL = whisper.load_model("base")
            print("✅ Whisper model 已載入")
        except Exception as exc:
            WHISPER_MODEL = None
            print(f"⚠️ Whisper model 載入失敗：{exc}")
