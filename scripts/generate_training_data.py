#!/usr/bin/env python3
"""
用 OpenAI API 或本機 Ollama 自動生成 E-CARE 訓練資料。

用法（OpenAI）：
    $env:OPENAI_API_KEY = "sk-..."
    python scripts/generate_training_data.py --count 50 --output scripts/data/generated.jsonl

用法（本機 Ollama，不需要 API Key）：
    python scripts/generate_training_data.py --backend ollama --model llama3.1:8b --count 50
"""

import argparse
import json
import os
import random
import time
import urllib.request
from pathlib import Path


# ======================
# 場景範本
# ======================

SCENARIOS = [
    # ── 醫療急症 ──────────────────────────────────────────────
    {"category": "醫療急症", "risk": "High",   "seed": "家人突然失去意識倒在地上，叫不醒"},
    {"category": "醫療急症", "risk": "High",   "seed": "朋友說呼吸很困難，嘴唇開始發紫"},
    {"category": "醫療急症", "risk": "High",   "seed": "有人抽搐倒地，已經停止抽搐但沒有反應"},
    {"category": "醫療急症", "risk": "High",   "seed": "老人突然胸口劇痛，臉色發白，感覺很不對"},
    {"category": "醫療急症", "risk": "High",   "seed": "小孩誤吞藥物，不知道吃了多少，現在嗜睡"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "自己發燒到39度，頭很暈，擔心越來越嚴重"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "老人家摔倒，腿可能骨折，意識清楚但很痛"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "孕婦說肚子痛得很厲害，還有3週才到預產期"},
    {"category": "醫療急症", "risk": "Low",    "seed": "小孩擦破皮，輕微流血，不確定需不需要送醫"},
    # 山域水域救援（app_category = 醫療急症）
    {"category": "醫療急症", "risk": "High",   "seed": "朋友登山迷路，天快黑了，手機電量剩不到10%"},
    {"category": "醫療急症", "risk": "High",   "seed": "有人溺水，被拉上岸但意識不清、呼吸微弱"},
    # 醫療事故（app_category = 醫療急症 or 待確認）
    {"category": "醫療急症", "risk": "Medium",  "seed": "醫院好像給我媽媽開錯藥，吃完後一直嘔吐"},
    {"category": "待確認",   "risk": "Medium",  "seed": "住院病人從床上摔下來，頭有撞到，護士還沒來"},

    # ── 火災 ──────────────────────────────────────────────────
    {"category": "火災",     "risk": "High",   "seed": "廚房起火，火勢開始蔓延到客廳，家裡還有人"},
    {"category": "火災",     "risk": "High",   "seed": "看到樓上住戶窗戶冒出濃煙，不確定裡面有沒有人"},
    {"category": "火災",     "risk": "High",   "seed": "工廠倉庫突然起火，有員工還在裡面"},
    {"category": "火災",     "risk": "Medium",  "seed": "聞到焦味，不確定是不是失火，還沒看到火"},
    # 瓦斯外洩（app_category = 火災）
    {"category": "火災",     "risk": "High",   "seed": "樓下傳來很重的瓦斯味，大家都說頭暈"},
    {"category": "火災",     "risk": "High",   "seed": "地下室聞到刺鼻味，不知道是不是化學品外洩"},

    # ── 暴力事件 ───────────────────────────────────────────────
    {"category": "暴力事件", "risk": "High",   "seed": "有人拿刀在外面追人，現在跑進大樓裡"},
    {"category": "暴力事件", "risk": "High",   "seed": "有人闖進家裡，躲在房間裡，很害怕"},
    {"category": "暴力事件", "risk": "High",   "seed": "看到有人被打倒在地上流血，打人的人還在現場"},
    {"category": "暴力事件", "risk": "High",   "seed": "聽到槍聲，不確定幾聲，周圍有人在跑"},
    {"category": "暴力事件", "risk": "Medium",  "seed": "兩個人在路邊激烈爭吵，其中一個人好像要動手"},
    {"category": "暴力事件", "risk": "Medium",  "seed": "室友喝醉酒情緒失控，開始砸東西，很害怕"},
    # 家庭暴力（app_category = 暴力事件，dispatch 含 113）
    {"category": "暴力事件", "risk": "High",   "seed": "隔壁一直傳來大人打小孩的聲音，小孩在哭叫求救"},
    {"category": "暴力事件", "risk": "High",   "seed": "先生喝醉酒在打我，孩子也在場，我很害怕"},
    {"category": "暴力事件", "risk": "Medium",  "seed": "鄰居夫妻大吵，聽到摔東西和哭叫聲，有點擔心"},
    # 性侵害（app_category = 暴力事件，dispatch 含 113）
    {"category": "暴力事件", "risk": "High",   "seed": "朋友傳訊說遭到性侵，現在躲在廁所，不知道怎麼辦"},

    # ── 可疑人士 ───────────────────────────────────────────────
    {"category": "可疑人士", "risk": "Medium",  "seed": "有陌生人在社區裡一直徘徊，已經一個多小時了"},
    {"category": "可疑人士", "risk": "Medium",  "seed": "走路回家時發現有人一直跟著自己"},
    {"category": "可疑人士", "risk": "Medium",  "seed": "深夜有人一直按門鈴但不說話，很害怕"},
    {"category": "可疑人士", "risk": "Low",    "seed": "鄰居最近很可疑，一直有陌生人進出，不確定要不要報警"},
    # 竊盜（app_category = 可疑人士）
    {"category": "可疑人士", "risk": "Medium",  "seed": "在便利商店看到一個人把東西塞進包包"},
    {"category": "可疑人士", "risk": "High",   "seed": "剛回到家，發現門鎖被破壞，有人可能已經進去過"},
    # 毒品（app_category = 可疑人士）
    {"category": "可疑人士", "risk": "Medium",  "seed": "租屋處樓上常有人出入，聞到奇怪的氣味，懷疑在吸毒"},

    # ── 噪音 ───────────────────────────────────────────────────
    {"category": "噪音",     "risk": "Low",    "seed": "隔壁深夜還在施工，已經吵了三個小時"},
    {"category": "噪音",     "risk": "Low",    "seed": "鄰居開派對音樂超大聲，已經凌晨一點了"},
    {"category": "噪音",     "risk": "Medium",  "seed": "樓上有人一直大吼大叫，聽起來像在激烈爭吵"},
    {"category": "噪音",     "risk": "Medium",  "seed": "半夜聽到玻璃破裂聲和重物倒地聲，不知道發生什麼事"},

    # ── 交通事故 ──────────────────────────────────────────────
    {"category": "交通事故", "risk": "High",   "seed": "目擊嚴重車禍，有人被困在車內，看起來有受傷"},
    {"category": "交通事故", "risk": "High",   "seed": "車子撞上路邊行人，行人倒地不起，駕駛逃跑了"},
    {"category": "交通事故", "risk": "High",   "seed": "高速公路上看到翻車，後面還有車輛持續追撞"},
    {"category": "交通事故", "risk": "High",   "seed": "我騎機車被追撞，腿很痛站不起來，對方停在旁邊"},
    {"category": "交通事故", "risk": "Medium",  "seed": "機車和汽車擦撞，機車騎士摔倒，走路好像有點跛"},
    {"category": "交通事故", "risk": "Medium",  "seed": "停車場出口有兩台車互撞，雙方都在吵架"},
    {"category": "交通事故", "risk": "Medium",  "seed": "老人騎自行車摔倒，說膝蓋很痛，腳踝也腫起來"},

    # ── 待確認 ─────────────────────────────────────────────────
    {"category": "待確認",   "risk": "Medium",  "seed": "外面有很大的聲響，不知道發生了什麼事，有點害怕"},
    {"category": "待確認",   "risk": "Low",    "seed": "不確定這樣算不算要報警，但感覺有點不對勁"},
    {"category": "待確認",   "risk": "Medium",  "seed": "聽到有人在喊救命，不知道從哪裡來的"},
    # 詐騙（app_category = 待確認，dispatch 含 165）
    {"category": "待確認",   "risk": "Medium",  "seed": "接到電話說我帳戶被凍結，要求立刻去ATM轉帳"},
    {"category": "待確認",   "risk": "Medium",  "seed": "有人自稱是警察說我涉嫌洗錢，要我配合匯款"},
    {"category": "待確認",   "risk": "Medium",  "seed": "老媽接到投資群組，說可以穩賺不賠，已經匯了10萬"},
    # 民事/家事（app_category = 待確認）
    {"category": "待確認",   "risk": "Low",    "seed": "房東說要趕我走，但租約還沒到期，不知道怎麼辦"},
    {"category": "待確認",   "risk": "Low",    "seed": "跟人借錢但對方不還，也不回訊息，金額有好幾萬"},
    # 天然災害（app_category = 待確認）
    {"category": "待確認",   "risk": "High",   "seed": "剛剛地震，家裡有裂縫，不確定還安不安全"},
    {"category": "待確認",   "risk": "High",   "seed": "颱風過後附近道路積水很深，有車輛被沖走"},
]


GENERATOR_SYSTEM_PROMPT = """你是緊急報案訓練資料生成器。請根據場景生成繁體中文對話，輸出 JSON 物件。

輸出結構（固定格式，不要更改欄位名稱）：
{
  "user1": "第一輪使用者說的話（自然口語、有情緒）",
  "assistant1": {
    "reply": "有同理心的1到2句回應",
    "risk_score": 0.7,
    "risk_level": "High",
    "should_escalate": true,
    "next_question": "最重要的下一個問題",
    "category": "火災|可疑人士|噪音|醫療急症|暴力事件|交通事故|待確認",
    "people_injured": null,
    "weapon": null,
    "danger_active": null,
    "dispatch_advice": "建議派遣：警察"
  },
  "user2": "第二輪使用者回答（回應上一個問題）",
  "assistant2": {
    "reply": "有同理心的1到2句回應",
    "risk_score": 0.7,
    "risk_level": "High",
    "should_escalate": true,
    "next_question": "下一個問題或空字串",
    "category": "火災|可疑人士|噪音|醫療急症|暴力事件|交通事故|待確認",
    "people_injured": null,
    "weapon": null,
    "danger_active": null,
    "dispatch_advice": "建議派遣：警察"
  }
}

dispatch_advice 規則（依優先順序）：
- 詐騙/假冒/ATM轉帳/匯款 → "建議通報：165反詐騙專線；若人身安全受威脅再通報110"
- 家暴/打小孩/兒虐/性侵 → "建議通報：110警察與113保護專線；若有人受傷同步通知救護車"
- 瓦斯外洩/化學品/刺鼻味 → "建議通報：119；先遠離現場、避免點火或開關電器"
- 登山迷路/山難/溺水 → "建議通報：119；提供座標、步道名稱、同行人數與最後聯絡時間"
- 火災/濃煙 → "建議派遣：消防隊"
- 醫療急症 → "建議派遣：救護車"
- 暴力/可疑人士 → "建議派遣：警察"
- 交通事故（有人傷） → "建議派遣：警察與救護車"
- 民事/租屋/借款 → "非立即緊急事件；建議保存證據並洽調解、法律諮詢或相關行政機關"

同理心原則：
- reply 要先接住情緒，不要像系統訊息
- 用「我知道你現在很害怕」「我先陪你整理」這類自然說法
- risk_level High 時 reply 要簡短有力
- 請全程使用繁體中文，不要夾雜簡體字"""

MULTI_TURN_SCENARIOS = [
    # 症狀逐漸加重
    {"category": "醫療急症", "risk": "High",   "seed": "爸爸說胸口有點悶，後來越來越喘，第三輪說已經臉色發白", "escalate": True},
    {"category": "醫療急症", "risk": "High",   "seed": "媽媽頭痛，第二輪說突然嘔吐，第三輪說說話開始不清楚", "escalate": True},
    {"category": "醫療急症", "risk": "Medium",  "seed": "自己發燒不舒服，第二輪問到症狀，第三輪確認不需要立即送醫", "escalate": False},
    # 地點在後面輪次才說出
    {"category": "火災",     "risk": "High",   "seed": "看到煙但說不清楚在哪，第二輪提供大樓名稱，第三輪確認出口", "escalate": False},
    {"category": "交通事故", "risk": "High",   "seed": "目擊車禍很慌張，第二輪才說出地點，第三輪確認傷者狀況", "escalate": False},
    # 風險從 Medium 升為 High
    {"category": "可疑人士", "risk": "High",   "seed": "有人在樓下徘徊，第二輪說對方開始上樓，第三輪說有在敲門", "escalate": True},
    {"category": "暴力事件", "risk": "High",   "seed": "聽到爭吵聲，第二輪說有東西被砸，第三輪說聽到有人喊救命", "escalate": True},
    # 助理引導行動步驟（多輪引導）
    {"category": "火災",     "risk": "High",   "seed": "家裡起火，助理逐步引導：確認人員→叫人撤離→等待消防", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "有人昏倒，助理逐步引導：確認意識→確認呼吸→指導 CPR", "escalate": False},
    # 資訊跨輪累積
    {"category": "醫療急症", "risk": "Medium",  "seed": "老人跌倒，第一輪問症狀，第二輪問地點，第三輪整合後給建議", "escalate": False},
    {"category": "暴力事件", "risk": "High",   "seed": "通報者邊跑邊打電話，每輪提供不同方向的線索", "escalate": False},
    # 詐騙多輪確認
    {"category": "待確認",   "risk": "Medium",  "seed": "接到可疑電話，助理幫助分辨是否詐騙，逐輪確認細節", "escalate": False},
    # 噪音升級為暴力
    {"category": "暴力事件", "risk": "High",   "seed": "樓上很吵，第二輪說聽到女生哭聲，第三輪說聽到打人聲", "escalate": True},
    # 家暴逐步揭露
    {"category": "暴力事件", "risk": "High",   "seed": "說跟先生吵架，第二輪說有被推，第三輪說孩子也在場很害怕", "escalate": True},
    # 瓦斯外洩多輪處置
    {"category": "火災",     "risk": "High",   "seed": "聞到瓦斯味，助理逐輪引導：不開電→撤離→打 119", "escalate": False},
]

MULTI_TURN_GENERATOR_PROMPT = """你是緊急報案訓練資料生成器。請根據場景生成繁體中文對話，輸出 JSON 物件。

輸出結構（固定格式，3 輪，不要更改欄位名稱）：
{
  "user1": "第一輪使用者說的話（自然口語、有情緒）",
  "assistant1": {
    "reply": "有同理心的回應，先接住情緒",
    "risk_score": 0.62,
    "risk_level": "Medium",
    "should_escalate": false,
    "next_question": "最重要的下一個問題",
    "reply_strategy": "先穩定情緒，再確認安全",
    "category": "醫療急症",
    "people_injured": null,
    "weapon": null,
    "danger_active": null,
    "dispatch_advice": "建議派遣：救護車"
  },
  "user2": "第二輪補充資訊（讓局面更清楚或更危急）",
  "assistant2": {
    "reply": "根據新資訊調整回應，要提及前一輪獲得的資訊",
    "risk_score": 0.82,
    "risk_level": "High",
    "should_escalate": true,
    "next_question": "下一步需要確認的問題",
    "reply_strategy": "確認危險程度，給出立即行動步驟",
    "category": "醫療急症",
    "people_injured": true,
    "weapon": null,
    "danger_active": true,
    "dispatch_advice": "建議派遣：救護車"
  },
  "user3": "第三輪回應（給出更多細節或執行助理的建議）",
  "assistant3": {
    "reply": "整合前三輪資訊給出明確結論或後續行動",
    "risk_score": 0.92,
    "risk_level": "High",
    "should_escalate": true,
    "next_question": "",
    "reply_strategy": "整合資訊，確認後續通報或行動",
    "category": "醫療急症",
    "people_injured": true,
    "weapon": null,
    "danger_active": true,
    "dispatch_advice": "建議派遣：救護車"
  }
}

重要規則：
- assistant2 的 reply 必須提及 user1 說過的資訊（展示上下文記憶）
- assistant3 的 reply 必須整合前面所有輪次的關鍵資訊
- 如果場景是風險升級，risk_level 應從 Medium 逐漸升到 High
- reply_strategy 三輪要不同，例如：「先穩定情緒」→「確認危險」→「整合行動」
- 請全程使用繁體中文，不要夾雜簡體字

dispatch_advice 規則（依優先順序）：
- 詐騙/假冒/ATM轉帳/匯款 → "建議通報：165反詐騙專線；若人身安全受威脅再通報110"
- 家暴/打小孩/兒虐/性侵 → "建議通報：110警察與113保護專線；若有人受傷同步通知救護車"
- 瓦斯外洩/化學品/刺鼻味 → "建議通報：119；先遠離現場、避免點火或開關電器"
- 登山迷路/山難/溺水 → "建議通報：119；提供座標、步道名稱、同行人數與最後聯絡時間"
- 火災/濃煙 → "建議派遣：消防隊"
- 醫療急症 → "建議派遣：救護車"
- 暴力/可疑人士 → "建議派遣：警察"
- 交通事故（有人傷） → "建議派遣：警察與救護車" """


TRAINING_SYSTEM_PROMPT = (
    "你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。\n"
    "只輸出 JSON，不要加入其他文字。\n"
    "category 只能是：火災、可疑人士、噪音、醫療急症、暴力事件、交通事故、待確認\n"
    "risk_level 只能是：Low、Medium、High"
)


def build_user_prompt(scenario: dict, multi_turn: bool = False) -> str:
    if multi_turn:
        escalate_hint = "，對話過程中風險應逐漸升高" if scenario.get("escalate") else ""
        return (
            f"請生成一段關於「{scenario['seed']}」的緊急報案對話{escalate_hint}。\n"
            f"場景：{scenario['category']}，預期最終風險：{scenario['risk']}\n"
            f"要求 3 輪對話，每輪使用者提供新資訊，助理的回應要展示對前面輪次的記憶與整合。"
        )
    return (
        f"請生成一段關於「{scenario['seed']}」的緊急報案對話。\n"
        f"場景：{scenario['category']}，預期風險：{scenario['risk']}\n"
        f"要求 2 到 3 輪對話，展示助理如何逐步釐清狀況並保持同理心。"
    )


# ======================
# OpenAI 後端
# ======================

def call_openai(api_key: str, model: str, scenario: dict, debug: bool = False, multi_turn: bool = False) -> list | None:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    sys_prompt = MULTI_TURN_GENERATOR_PROMPT if multi_turn else GENERATOR_SYSTEM_PROMPT
    max_tok = 3000 if multi_turn else 2000
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": build_user_prompt(scenario, multi_turn=multi_turn)},
            ],
            temperature=0.9,
            max_tokens=max_tok,
            response_format={"type": "json_object"},
        )
        return parse_flat_response(resp.choices[0].message.content or "", debug=debug, multi_turn=multi_turn)
    except Exception as e:
        print(f"[跳過] {e}")
        return None


# ======================
# Ollama 後端
# ======================

def call_ollama(model: str, scenario: dict, base_url: str = "http://localhost:11434", debug: bool = False, multi_turn: bool = False) -> list | None:
    sys_prompt = MULTI_TURN_GENERATOR_PROMPT if multi_turn else GENERATOR_SYSTEM_PROMPT
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": build_user_prompt(scenario, multi_turn=multi_turn)},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.7, "num_predict": 6000 if multi_turn else 4096},
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        content = data.get("message", {}).get("content", "")
        return parse_flat_response(content, debug=debug, multi_turn=multi_turn)
    except Exception as e:
        print(f"[跳過] {e}")
        return None


# ======================
# 共用解析
# ======================

def parse_flat_response(raw: str, debug: bool = False, multi_turn: bool = False) -> list | None:
    """把模型輸出的扁平 JSON 轉成 turns 清單，支援 2 輪（user1-2）和 3 輪（user1-3）。"""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        d = json.loads(raw)
    except Exception as e:
        if debug:
            print(f"\n  [除錯] JSON 解析失敗：{e}\n  原始：{raw[:300]}")
        return None

    required = ("user1", "assistant1", "user2", "assistant2")
    if not all(k in d for k in required):
        if debug:
            print(f"\n  [除錯] 缺少必要欄位，有：{list(d.keys())}")
        return None

    DISPATCH_MAP = {
        "火災": "建議派遣：消防隊", "醫療急症": "建議派遣：救護車",
        "暴力事件": "建議派遣：警察", "可疑人士": "建議派遣：警察",
        "噪音": "建議派遣：待確認", "交通事故": "建議派遣：警察與救護車",
        "待確認": "建議派遣：待確認",
    }

    STRATEGY_MAP = {
        "High":   "先穩定情緒，確認立即危險，給出行動步驟",
        "Medium": "先穩定情緒，再確認安全",
        "Low":    "釐清狀況，評估是否需要進一步行動",
    }

    def assistant_to_full_json(a: dict) -> str:
        category = a.get("category", "待確認")
        risk_level = a.get("risk_level", "Medium")
        strategy = a.get("reply_strategy") or STRATEGY_MAP.get(risk_level, "先穩定情緒，再確認安全")
        full = {
            "reply": a.get("reply", ""),
            "risk_score": a.get("risk_score", 0.5),
            "risk_level": risk_level,
            "should_escalate": a.get("should_escalate", risk_level == "High"),
            "next_question": a.get("next_question", ""),
            "semantic": {
                "intent": "求救" if risk_level == "High" else "通報",
                "primary_need": "立即安全協助" if risk_level == "High" else "釐清狀況",
                "emotion": "fearful" if risk_level in ["High", "Medium"] else "neutral",
                "reply_strategy": strategy,
                "entities": {"location": None, "injured": a.get("people_injured"),
                             "weapon": a.get("weapon"), "danger_active": a.get("danger_active")},
            },
            "extracted": {
                "category": category,
                "location": None,
                "people_injured": a.get("people_injured"),
                "weapon": a.get("weapon"),
                "danger_active": a.get("danger_active"),
                "reporter_role": None, "conscious": None,
                "breathing_difficulty": None, "fever": None, "symptom_summary": None,
                "dispatch_advice": a.get("dispatch_advice", DISPATCH_MAP.get(category, "建議派遣：待確認")),
                "description": None,
            },
        }
        return json.dumps(full, ensure_ascii=False)

    a1 = d["assistant1"] if isinstance(d["assistant1"], dict) else {}
    a2 = d["assistant2"] if isinstance(d["assistant2"], dict) else {}
    turns = [
        {"role": "user",      "content": str(d["user1"])},
        {"role": "assistant", "content": assistant_to_full_json(a1)},
        {"role": "user",      "content": str(d["user2"])},
        {"role": "assistant", "content": assistant_to_full_json(a2)},
    ]

    # 多輪模式：附加第 3 輪（如果存在）
    if multi_turn and "user3" in d and "assistant3" in d:
        a3 = d["assistant3"] if isinstance(d["assistant3"], dict) else {}
        turns.append({"role": "user",      "content": str(d["user3"])})
        turns.append({"role": "assistant", "content": assistant_to_full_json(a3)})

    return turns


def parse_turns(raw: str, debug: bool = False) -> list | None:
    raw = raw.strip()
    # 去掉 markdown code fence
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    # 找出第一個 [ 開頭的位置
    start = raw.find("[")
    if start < 0:
        if debug:
            print(f"\n  [除錯] 找不到 JSON 陣列，原始輸出：\n  {raw[:300]}")
        return None
    raw = raw[start:]
    try:
        turns = json.loads(raw)
    except Exception as e:
        if debug:
            print(f"\n  [除錯] JSON 解析失敗：{e}\n  原始輸出：\n  {raw[:300]}")
        return None

    if not isinstance(turns, list) or len(turns) < 2:
        return None

    # 修正：有些模型把 assistant content 輸出成 dict 而不是字串
    fixed = []
    for turn in turns:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "assistant" and isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        elif role == "assistant" and isinstance(content, str):
            # 確認 content 本身是合法 JSON
            try:
                json.loads(content)
            except Exception:
                if debug:
                    print(f"\n  [除錯] assistant content 不是合法 JSON：{content[:200]}")
                return None
        fixed.append({"role": role, "content": content})

    return fixed if len(fixed) >= 2 else None


# ======================
# 主流程
# ======================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",  default="scripts/data/generated.jsonl")
    parser.add_argument("--count",   type=int, default=100)
    parser.add_argument("--backend", choices=["openai", "ollama"], default="openai")
    parser.add_argument("--model",   default=None,
                        help="OpenAI: gpt-4o-mini（預設）  Ollama: llama3.1:8b（預設）")
    parser.add_argument("--delay",   type=float, default=0.5)
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--debug", action="store_true", help="顯示模型原始輸出（除錯用）")
    parser.add_argument("--multi-turn", action="store_true", help="生成 3 輪多輪對話（測試上下文記憶）")
    args = parser.parse_args()

    # 決定模型名稱預設值
    if args.model is None:
        args.model = "gpt-4o-mini" if args.backend == "openai" else "llama3.1:8b"

    # OpenAI 需要 Key
    api_key = None
    if args.backend == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("請設定 $env:OPENAI_API_KEY=sk-...")
            return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    scenario_pool = MULTI_TURN_SCENARIOS if args.multi_turn else SCENARIOS
    mode_label = "3 輪多輪" if args.multi_turn else "2 輪標準"
    print(f"後端：{args.backend}  模型：{args.model}  模式：{mode_label}")
    print(f"目標：{args.count} 筆  輸出：{output_path}\n")

    generated = failed = 0

    with output_path.open("w", encoding="utf-8") as f:
        scenario_index = 0
        while generated < args.count:
            scenario = scenario_pool[scenario_index % len(scenario_pool)]
            scenario_index += 1
            label = scenario['seed'][:22]
            print(f"[{generated+1}/{args.count}] {label}...", end=" ", flush=True)

            if args.backend == "openai":
                turns = call_openai(api_key, args.model, scenario, debug=args.debug, multi_turn=args.multi_turn)
            else:
                turns = call_ollama(args.model, scenario, args.ollama_url, debug=args.debug, multi_turn=args.multi_turn)

            if turns:
                record = {
                    "messages": [{"role": "system", "content": TRAINING_SYSTEM_PROMPT}] + turns
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                generated += 1
                n = len([t for t in turns if t["role"] == "user"])
                print(f"OK（{n} 輪）")
            else:
                failed += 1
                print("失敗")

            time.sleep(args.delay)

    print(f"\n完成：{generated} 筆成功，{failed} 筆失敗 → {output_path}")


if __name__ == "__main__":
    main()
