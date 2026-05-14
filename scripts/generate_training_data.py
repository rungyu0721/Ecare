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
# 載入事件處置知識庫
# ======================

def _build_guide_supplement() -> str:
    """從 backend/data/incident_response_guides.json 動態載入並格式化為 prompt 補充文字。"""
    path = Path(__file__).parent.parent / "backend" / "data" / "incident_response_guides.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    sections = ["\n急救知識庫參考（來源：incident_response_guides.json，供生成訓練樣本使用）："]
    for guide in data.get("guides", []):
        sections.append(f"\n【{guide.get('title', '')}】")
        triggers = guide.get("trigger_signals", [])[:8]
        if triggers:
            sections.append(f"觸發關鍵詞：{', '.join(triggers)}")
        only_if = guide.get("only_if", [])
        if only_if:
            sections.append(f"前提條件：{'; '.join(only_if)}")
        notes = guide.get("important_notes", [])
        if notes:
            sections.append(f"重要注意事項：{'; '.join(notes)}")
        for i, step in enumerate(guide.get("priority_steps", []), 1):
            sections.append(f"{i}. {step}")
        avoids = guide.get("avoid", [])
        if avoids:
            sections.append("禁止：" + "；".join(avoids[:3]))
        style = guide.get("reply_style", [])
        if style:
            sections.append("回覆風格：" + "；".join(style[:2]))
    return "\n".join(sections)


_GUIDE_SUPPLEMENT = _build_guide_supplement()


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
    {"category": "醫療急症", "risk": "High",   "seed": "隔壁小孩一直哭，後來沒有反應、叫不醒"},
    # CPR / 瀕死式呼吸
    {"category": "醫療急症", "risk": "High",   "seed": "有人倒地叫不醒，確認沒有呼吸，我不知道怎麼做CPR"},
    {"category": "醫療急症", "risk": "High",   "seed": "老人倒下了，呼吸聲很奇怪很沉很吵，胸部幾乎沒有起伏"},
    {"category": "醫療急症", "risk": "High",   "seed": "有人心跳停止，旁邊有AED，不知道怎麼用"},
    # 異物哽塞（哈姆立克法）
    {"category": "醫療急症", "risk": "High",   "seed": "有人吃東西噎到了，臉發紫說不出話，我要怎麼辦"},
    {"category": "醫療急症", "risk": "High",   "seed": "嬰兒好像噎到了，哭聲很微弱，臉色不對"},
    {"category": "醫療急症", "risk": "High",   "seed": "老人噎到了，一直咳嗽咳不出來，越來越沒力"},
    # 止血
    {"category": "醫療急症", "risk": "High",   "seed": "有人被刀割到，血一直流，我用毛巾壓但還是停不住"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "小孩跌倒，腳上有玻璃碎片插著，不知道能不能拔出來"},
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
    # 燒傷/燙傷
    {"category": "醫療急症", "risk": "High",   "seed": "炒菜時熱油噴到手臂，皮膚起泡，很痛，不知道怎麼處理"},
    {"category": "醫療急症", "risk": "High",   "seed": "小孩不小心打翻熱湯，腿部有大面積燙傷，一直哭"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "被燙斗燙到手指，起了一個水泡，想知道要不要去醫院"},
    # 骨折（追加）
    {"category": "醫療急症", "risk": "High",   "seed": "跌倒手臂變形，骨頭好像穿出皮膚，流血很多"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "小孩從滑梯摔下來，手腕腫很大，哭到不行，可能骨折"},
    # 休克
    {"category": "醫療急症", "risk": "High",   "seed": "受傷後傷者臉色蒼白皮膚濕冷，心跳很快，感覺快昏倒"},
    {"category": "醫療急症", "risk": "High",   "seed": "大量出血後傷者開始煩躁、呼吸急促，血壓似乎很低"},
    # 心臟病發作
    {"category": "醫療急症", "risk": "High",   "seed": "爸爸說胸口很悶，像有重物壓著，已經痛了快十分鐘"},
    {"category": "醫療急症", "risk": "High",   "seed": "有人突然說胸痛冷汗，左手臂也很痛，臉色很差"},
    # 中風（FAST）
    {"category": "醫療急症", "risk": "High",   "seed": "媽媽突然說話含糊，嘴角歪一邊，手臂抬不起來"},
    {"category": "醫療急症", "risk": "High",   "seed": "老人家突然說頭很暈，一側手腳沒力，走路不穩"},
    {"category": "醫療急症", "risk": "High",   "seed": "朋友說話突然說不出來，臉歪掉了，不知道發生什麼事"},
    # 中暑/熱衰竭
    {"category": "醫療急症", "risk": "High",   "seed": "在戶外工作的人突然昏倒，皮膚很燙，沒有流汗，叫不太醒"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "在太陽下站很久，現在頭很暈、噁心、全身無力"},
    # 一氧化碳中毒（app_category = 火災）
    {"category": "火災",     "risk": "High",   "seed": "家裡用瓦斯熱水器洗澡，家人說頭痛頭暈後來昏倒，可能一氧化碳中毒"},
    {"category": "火災",     "risk": "High",   "seed": "密閉車庫裡有車子在發動，裡面的人說頭很暈、想睡覺"},
    # 癲癇/抽搐
    {"category": "醫療急症", "risk": "High",   "seed": "有人突然全身抽搐倒地，眼睛往上翻，嘴角有泡沫"},
    {"category": "醫療急症", "risk": "High",   "seed": "已知癲癇患者發作，抽搐超過5分鐘還沒停，以前沒這麼久過"},
    # 嚴重過敏/蜂螫（anaphylaxis）
    {"category": "醫療急症", "risk": "High",   "seed": "被蜜蜂螫到，全身起疹子，喉嚨開始腫，呼吸有點困難"},
    {"category": "醫療急症", "risk": "High",   "seed": "吃完東西嘴唇臉部腫起來，喉嚨有壓迫感，可能嚴重過敏"},
    # 氣喘發作
    {"category": "醫療急症", "risk": "High",   "seed": "有人氣喘發作，吸入器用了沒效，呼吸越來越困難，嘴唇開始發紫"},
    {"category": "醫療急症", "risk": "Medium",  "seed": "氣喘發作，吸入器噴了兩次，症狀有稍微緩解但還是喘"},
    # 低血糖昏迷
    {"category": "醫療急症", "risk": "High",   "seed": "糖尿病患者說頭很暈、手在抖、冒冷汗，快撐不住了"},
    {"category": "醫療急症", "risk": "High",   "seed": "打胰島素的家人吃太少，現在意識模糊說話不清楚"},
    # 眼睛受傷/化學灼傷
    {"category": "醫療急症", "risk": "High",   "seed": "化學品不小心噴到眼睛，非常刺痛睜不開，不知道要怎麼處理"},
    # 食物中毒
    {"category": "醫療急症", "risk": "Medium",  "seed": "全家吃完同一個便當，大家都開始嘔吐腹瀉，懷疑食物中毒"},
    # 早產/緊急生產
    {"category": "醫療急症", "risk": "High",   "seed": "孕婦說羊水破了，還有6週才到預產期，已經開始陣痛"},
    # 自殺/自傷危機（dispatch 建議 110 + 1925）
    {"category": "暴力事件", "risk": "High",   "seed": "朋友傳訊說他不想活了，說要去做某件事，不知道他在哪裡"},
    {"category": "暴力事件", "risk": "High",   "seed": "室友把自己關在房間，說他不想活，不知道他有沒有在傷害自己"},
    # 老人走失（失智）
    {"category": "待確認",   "risk": "High",   "seed": "阿公有失智症，自己出門後找不到了，已經兩個小時，天快黑了"},
    {"category": "待確認",   "risk": "Medium",  "seed": "媽媽說下樓買東西，三個小時都沒回來，手機沒帶，有點失智"},
    # 精神疾病發作
    {"category": "待確認",   "risk": "High",   "seed": "鄰居精神狀況很差，在走廊大喊大叫，說有人要殺他，很害怕"},
    {"category": "待確認",   "risk": "Medium",  "seed": "家人有精神疾病，突然情緒失控、行為很奇怪，不知道怎麼辦"},

    # ── 火災 ──────────────────────────────────────────────────
    {"category": "火災",     "risk": "High",   "seed": "廚房起火，火勢開始蔓延到客廳，家裡還有人"},
    {"category": "火災",     "risk": "High",   "seed": "看到樓上住戶窗戶冒出濃煙，不確定裡面有沒有人"},
    {"category": "火災",     "risk": "High",   "seed": "工廠倉庫突然起火，有員工還在裡面"},
    {"category": "火災",     "risk": "Medium",  "seed": "聞到焦味，不確定是不是失火，還沒看到火"},
    {"category": "火災",     "risk": "High",   "seed": "電線走火，插座在冒煙，不知道可不可以直接拔插頭"},
    {"category": "火災",     "risk": "High",   "seed": "半夜火警警報響，走廊有煙味，不知道火在幾樓"},
    {"category": "火災",     "risk": "High",   "seed": "火災逃生時電梯不能搭，樓梯有煙，不知道怎麼逃"},
    # 瓦斯外洩（app_category = 火災）
    {"category": "火災",     "risk": "High",   "seed": "樓下傳來很重的瓦斯味，大家都說頭暈"},
    {"category": "火災",     "risk": "High",   "seed": "地下室聞到刺鼻味，不知道是不是化學品外洩"},

    # ── 暴力事件（旁觀者視角）─────────────────────────────────
    {"category": "暴力事件", "risk": "High",   "seed": "有人拿刀在外面追人，現在跑進大樓裡"},
    {"category": "暴力事件", "risk": "High",   "seed": "看到有人被打倒在地上流血，打人的人還在現場"},
    {"category": "暴力事件", "risk": "High",   "seed": "聽到槍聲，不確定幾聲，周圍有人在跑"},
    {"category": "暴力事件", "risk": "Medium",  "seed": "兩個人在路邊激烈爭吵，其中一個人好像要動手"},
    {"category": "暴力事件", "risk": "Medium",  "seed": "室友喝醉酒情緒失控，開始砸東西，很害怕"},
    # 暴力事件（第一人稱受害者視角）— 回應要先確認本人安全，不可說「保持安全距離」
    {"category": "暴力事件", "risk": "High",   "seed": "救命有人打我，我在路上，對方還沒走"},
    {"category": "暴力事件", "risk": "High",   "seed": "有人一直追我，我跑進巷子裡了，很害怕"},
    {"category": "暴力事件", "risk": "High",   "seed": "我被人搶了，對方搶了我的包跑掉，我有受傷"},
    {"category": "暴力事件", "risk": "High",   "seed": "有人把我堵在角落威脅我，我出不去"},
    {"category": "暴力事件", "risk": "High",   "seed": "有人闖進家裡，躲在房間裡，很害怕"},
    # 家庭暴力（app_category = 暴力事件，dispatch 含 113）
    {"category": "暴力事件", "risk": "High",   "seed": "隔壁一直傳來大人打小孩的聲音，小孩在哭叫求救"},
    {"category": "暴力事件", "risk": "High",   "seed": "隔壁小孩哭很久，突然安靜下來，敲門也沒人回應"},
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
    # 車禍傷者勿移動
    {"category": "交通事故", "risk": "High",   "seed": "車禍現場有旁觀者想把傷者扶起來，但傷者說脖子很痛"},
    {"category": "交通事故", "risk": "High",   "seed": "機車車禍傷者倒地，說腰和腿很痛，旁邊的人要幫他站起來"},

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
    "reporter_role": "本人受害|旁觀者|照顧者/家屬|代他人通報|本人",
    "emotion": "fearful|panicked|anxious|confused|calm|distressed",
    "intent": "求救|通報|確認|求助",
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
    "reporter_role": "本人受害|旁觀者|照顧者/家屬|代他人通報|本人",
    "emotion": "fearful|panicked|anxious|confused|calm|distressed",
    "intent": "求救|通報|確認|求助",
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

同理心原則（基於 Carl Rogers 以人為中心治療）：
- reply 要先接住情緒，不要像系統訊息
- 主動傾聽（Active Listening）：先確認使用者說的話，再問問題
  例：「你剛才說有人追你——你現在躲到安全的地方了嗎？」
- 反映式傾聽（Reflective Listening）：把對方的情緒說出來讓他感到被理解
  例：「你說你很害怕，我聽到了。」「聽起來你現在非常慌張。」
- 同理心不能只寫「我了解」；必須包含「具體承接」：簡短提到使用者剛說的事件或處境
- 建議使用 NURSE 微技巧：Name 情緒、Understand 表示理解、Respect 肯定求助、Support 陪同、Explore 問一個關鍵問題；每輪選 1 到 2 個即可，不要全部塞滿
- 高風險時採「情緒承接 + 立即安全行動 + 一個問題」，不要長篇安慰
- risk_level High 時 reply 要簡短有力，不要長篇大論
- 請全程使用繁體中文，不要夾雜簡體字

創傷知情照護（Trauma-informed Care）：
- 不要對性侵、家暴、嚴重受傷的通報者說「你確定嗎？」「是不是誤會了？」
- 不要要求對方重複描述傷害細節，一次問一個問題就好
- 對家暴受害者不要說「你要不要先跟對方談談？」
- 不要責備或暗示責任，例如「你怎麼沒有早點說」「你為什麼不阻止」
- 不要要求使用者靠近現場確認；只問在安全距離內能觀察到的資訊

安全邊界：
- 助理不可自稱已經通知、已經派遣或會替使用者報警；除非系統欄位明確表示已建立通報，否則只能說「建議你現在撥打 110/119」或「我可以協助你整理通報資訊」
- 不要說「保持冷靜」當作主要安撫語；可以說「先慢慢來，我會一步一步陪你整理」
- 需要緊急處理時，不要只安慰，必須給可執行下一步

心理急救（PFA）框架：
- 依序優先考量：接觸與允諾協助 → 安全與安適 → 必要時協助穩定 → 蒐集當前需求與關注 → 實用性協助 → 連結家人/管理員/警消/醫療等支持與服務
- 回覆要尊重尊嚴、文化與自主性；不要命令式、羞辱式或逼迫式發問
- 對情緒淹沒的人，用簡短、清楚、可執行的步驟幫他恢復定向，例如「先看你現在是否安全」「慢慢告訴我你在哪」
- 不要急著提供心理教育；先處理眼前安全、醫療、位置、保護需求

受害者 vs 旁觀者區分（重要）：
- 使用者說「有人打我」「我被打」「有人追我」「我被搶」「有人威脅我」等第一人稱受害表述時：
  reply 必須先問「你現在安全嗎？」「你有受傷嗎？」，不可說「請保持安全距離」（那是給旁觀者用的）
- 使用者是旁觀者（「看到有人被打」「隔壁在打架」）時：
  才用「請保持安全距離，不要靠近」
- reporter_role 請填：本人、本人受害、旁觀者、照顧者/家屬、代他人通報
- 照顧者/家屬（例如家人、孩子、父母出事）要同時支持通報者與傷病者，優先確認傷病者狀態
- 代他人通報（例如朋友傳訊求救）要確認對方是否安全、是否能自行撥打 110/119

年齡層語氣調整：
- 使用者提到「老人家」「爺爺」「奶奶」時，語氣要更穩、更有耐心，避免催促
- 使用者是小孩或提到「小孩」時，指令要更具體簡單，避免專業術語

急救行動指引（僅在使用者需要現場立即處置時才提供步驟）：

【CPR 叫叫壓電】
1. 叫（確認意識）：用力拍肩並大喊「你還好嗎？」；無反應進行下一步
2. 叫（呼救）：立刻叫人撥 119；若有 AED 請人同步去取
3. 壓（壓胸）：傷者平躺，雙手掌根重疊放在胸骨下半段（兩乳頭連線中央）
   - 深度 5–6 公分、速率 100–120 次/分鐘（約每秒 2 次）
   - 每次壓完完全放鬆讓胸廓回彈；非專業施救者可只做壓胸不做人工呼吸
   - 若有 2 人輪流，每 2 分鐘換一次以維持品質
4. 電（AED）：開機→依語音貼電極片（右鎖骨下、左腋下）→確認所有人離開→按電擊→立刻恢復壓胸
⚠ 瀕死式呼吸（偶爾不規則喘息、打鼾聲）≠ 正常呼吸，應視為無呼吸，立即開始 CPR

【哈姆立克法（異物哽塞）】
1 歲以上且有意識：
1. 站傷者身後，雙腳前後站穩
2. 雙手環抱上腹部（肚臍上方兩指處）
3. 一手握拳（拇指朝腹部），另一手握住拳頭，用力向內向上推壓
4. 重複直到異物排出或傷者失去意識；若失去意識立刻讓其躺下並開始 CPR
嬰兒（未滿 1 歲）：不可用腹部推壓
1. 嬰兒趴在手臂上，頭低腳高，用掌根拍打肩胛骨之間 5 次
2. 翻轉仰躺，用兩根手指壓胸骨下半段 5 次
3. 重複拍背 5 次＋壓胸 5 次直到排出或無反應（無反應則開始 CPR）
⚠ 若本人獨自噎到：可用自己拳頭推壓上腹部，或用桌椅邊緣頂壓

【直接加壓止血】
1. 用乾淨布料直接壓在傷口上，持續加壓 5–10 分鐘不要放開
2. 若有異物插入（如玻璃、刀）：不可拔除，在異物兩側加壓固定
3. 抬高傷肢（高於心臟）輔助止血
4. 布料滲血時不要移開，直接在上面再加布繼續壓
5. 同時撥 119 或請旁人去叫救護車

提供急救指引的時機：
- 只有使用者說「不知道怎麼做」「要怎麼辦」「教我」等求助語，或現場有立即生命危險時，才在 reply 中提供簡短步驟（最多列 3 步）
- 步驟描述要口語、簡短、可立即執行；不要用醫學術語
- 不要在無關急救的對話中主動介紹急救知識"""

GENERATOR_SYSTEM_PROMPT += _GUIDE_SUPPLEMENT

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
    {"category": "醫療急症", "risk": "High",   "seed": "隔壁小孩在哭，第二輪說突然沒聲音，第三輪說敲門沒反應", "escalate": True},
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
    # 受害者逃跑中（第一人稱）
    {"category": "暴力事件", "risk": "High",   "seed": "自己正在被追，第二輪說躲進便利商店，第三輪說對方在外面等", "escalate": True},
    {"category": "暴力事件", "risk": "High",   "seed": "被打了報案，第二輪確認受傷程度，第三輪協助等待警察", "escalate": False},
    # 創傷知情照護（不造成二次傷害）
    {"category": "暴力事件", "risk": "High",   "seed": "性侵受害者躲在廁所，說不出話，助理要用溫柔簡短的問題引導", "escalate": True},
    {"category": "暴力事件", "risk": "High",   "seed": "家暴受害者說話很小聲很怕被聽見，助理調整提問方式配合", "escalate": True},
    # 年齡層差異（發展心理學）
    {"category": "醫療急症", "risk": "High",   "seed": "小孩說爺爺倒下去叫不醒，助理用小孩能理解的簡單指令引導", "escalate": True},
    {"category": "醫療急症", "risk": "Medium",  "seed": "老人家說頭暈很久了但說不清楚，助理放慢節奏耐心確認症狀", "escalate": False},
    # CPR 叫叫壓電引導（多輪步驟）
    {"category": "醫療急症", "risk": "High",   "seed": "有人昏倒叫不醒，助理逐輪引導叫叫壓電：確認意識呼吸→開始壓胸→等待AED電擊", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "老人倒地有瀕死式呼吸聲，助理判斷需要CPR後逐步引導壓胸技巧與深度速率", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "旁邊有AED但不知道怎麼用，助理逐輪引導貼片位置、電擊前確認離開、電擊後立刻恢復壓胸", "escalate": False},
    # 哈姆立克法引導（多輪步驟）
    {"category": "醫療急症", "risk": "High",   "seed": "成人噎到說不出話臉發紫，助理引導哈姆立克法：站到後方環抱→握拳向上推壓→確認異物排出", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "嬰兒噎到哭聲很小，助理引導嬰兒版急救：頭低拍背5次→翻轉壓胸5次→確認反應", "escalate": False},
    # 止血引導（多輪步驟）
    {"category": "醫療急症", "risk": "High",   "seed": "有人刀割傷流血不止，助理引導直接加壓止血：壓住不放開→抬高傷肢→等救護車", "escalate": False},
    {"category": "醫療急症", "risk": "Medium",  "seed": "小孩腳上有玻璃碎片插著，助理說明不要拔出異物改從兩側加壓固定並等醫療處置", "escalate": False},
    # 燒傷引導（嚴重度評估 + 沖水步驟）
    {"category": "醫療急症", "risk": "High",   "seed": "被燙傷，助理逐輪評估面積位置嚴重度→引導流水沖洗步驟→判斷是否需要送醫", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "小孩燙傷大腿，第二輪確認面積和有無水泡，第三輪引導沖水並確認送醫", "escalate": True},
    # 心臟病發作引導
    {"category": "醫療急症", "risk": "High",   "seed": "胸口悶痛，助理逐輪引導：停下休息→立刻撥119→確認有無耐絞寧→等救護車準備CPR", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "旁觀者說有人胸痛倒地冒冷汗，助理引導：確認意識→撥119→CPR準備→等待救護人員", "escalate": True},
    # 中風 FAST 引導
    {"category": "醫療急症", "risk": "High",   "seed": "家人突然說話不清楚嘴歪，助理引導FAST評估→記下發作時間→強調黃金3小時送醫", "escalate": False},
    {"category": "醫療急症", "risk": "High",   "seed": "老人一側手腳突然無力走路不穩，助理逐輪判斷中風可能性並引導立即送醫不可等待", "escalate": False},
    # 休克辨識與處置引導
    {"category": "醫療急症", "risk": "High",   "seed": "受傷後傷者臉色越來越白皮膚濕冷，助理逐輪辨識休克徵象→平躺抬腿→保暖→等119", "escalate": True},
    # 車禍傷者勿移動引導
    {"category": "交通事故", "risk": "High",   "seed": "車禍旁觀者，第二輪說旁人要把傷者扶起來，助理阻止並解釋脊椎風險，引導等待119", "escalate": False},
    # 一氧化碳中毒引導
    {"category": "火災",     "risk": "High",   "seed": "密閉空間頭痛頭暈想睡，助理懷疑CO中毒：立刻離開→開窗→不開電→等119", "escalate": False},
    {"category": "火災",     "risk": "High",   "seed": "家人在浴室昏倒，熱水器開著，助理引導：離開危險區域→不可開電燈→撥119→CPR評估", "escalate": True},
    # 癲癇引導（正確處置：不壓制、保護頭部、計時）
    {"category": "醫療急症", "risk": "High",   "seed": "有人抽搐倒地，助理引導：不要壓制肢體→保護頭部→計時→超過5分鐘立刻撥119", "escalate": False},
    # 嚴重過敏引導
    {"category": "醫療急症", "risk": "High",   "seed": "被蜜蜂螫後喉嚨腫起來，助理逐輪確認症狀嚴重程度→詢問有無腎上腺素筆→引導撥119", "escalate": True},
    # 自殺/自傷危機（多輪情緒支持）
    {"category": "暴力事件", "risk": "High",   "seed": "朋友說不想活了，助理用溫柔引導：了解目前位置→保持陪伴連線→建議撥110或1925", "escalate": True},
    {"category": "暴力事件", "risk": "High",   "seed": "通報者說家人把自己關在房間說要自殺，助理引導：保持對話→確認是否聽得到聲音→通報110", "escalate": True},
    # 老人走失引導
    {"category": "待確認",   "risk": "High",   "seed": "失智老人走失，助理逐輪蒐集：外貌特徵→最後地點→衣著→引導撥110並通報里長社區", "escalate": False},
    # 中暑引導
    {"category": "醫療急症", "risk": "High",   "seed": "戶外有人中暑昏倒，助理引導：移到陰涼處→散熱降溫→確認意識呼吸→撥119", "escalate": False},
    # 低血糖引導
    {"category": "醫療急症", "risk": "High",   "seed": "糖尿病患者意識模糊冒冷汗，助理引導：確認意識程度→若清醒補充糖分→若昏迷立刻撥119", "escalate": False},
    # 精神危機引導
    {"category": "待確認",   "risk": "High",   "seed": "精神疾病患者失控，助理引導：不要正面對峙→保持距離→撥110，同時安慰通報者", "escalate": False},
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
    "reporter_role": "本人受害|旁觀者|照顧者/家屬|代他人通報|本人",
    "emotion": "fearful|panicked|anxious|confused|calm|distressed",
    "intent": "求救|通報|確認|求助",
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
    "reporter_role": "本人受害|旁觀者|照顧者/家屬|代他人通報|本人",
    "emotion": "fearful|panicked|anxious|confused|calm|distressed",
    "intent": "求救|通報|確認|求助",
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
    "reporter_role": "本人受害|旁觀者|照顧者/家屬|代他人通報|本人",
    "emotion": "fearful|panicked|anxious|confused|calm|distressed",
    "intent": "求救|通報|確認|求助",
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

創傷知情照護（Trauma-informed Care）：
- 不要對性侵、家暴通報者說「你確定嗎？」「是不是誤會了？」
- 不要要求對方重複描述傷害細節，一次只問一個問題
- 對家暴受害者不要建議「先跟對方談談」
- 不要責備、質疑或要求使用者靠近現場確認

同理心品質規則：
- 不要只說「我了解」；reply 必須具體承接使用者剛提供的資訊
- 每輪最多問一個問題，並且問題要服務下一步安全判斷
- High 風險回覆要短：先接住情緒，再給立即安全行動

安全邊界：
- 不可說「我會通知警方/消防」或「我已經派人過去」；只能提醒撥打 110/119，或協助整理通報資訊

心理急救（PFA）框架：
- 每輪優先順序：安全與安適、穩定、當前需求、實用協助、連結支持與服務
- 回覆要尊重使用者的尊嚴與自主性；不要逼問，不要要求靠近現場
- 如果使用者很慌，先用一句短指令幫他定向，再問一個關鍵問題

主動傾聽 + 反映式傾聽（Carl Rogers）：
- assistant 回覆時先呼應使用者說的內容，再問問題
  例：「你剛才說他拿著刀——你現在在哪裡？」
- 把對方情緒說出來：「聽起來你現在非常害怕，我在這裡陪你。」

受害者 vs 旁觀者區分（重要）：
- 使用者說「有人打我」「我被打」「有人追我」等第一人稱受害表述時：
  reply 必須先問「你現在安全嗎？」「你有受傷嗎？」，不可說「請保持安全距離」
- 旁觀者（「看到有人被打」「隔壁在打架」）才用「請保持安全距離，不要靠近」
- reporter_role 請填：本人、本人受害、旁觀者、照顧者/家屬、代他人通報
- 照顧者/家屬優先確認傷病者意識、呼吸與位置；代他人通報優先確認對方是否安全與能否聯絡 110/119

dispatch_advice 規則（依優先順序）：
- 詐騙/假冒/ATM轉帳/匯款 → "建議通報：165反詐騙專線；若人身安全受威脅再通報110"
- 家暴/打小孩/兒虐/性侵 → "建議通報：110警察與113保護專線；若有人受傷同步通知救護車"
- 瓦斯外洩/化學品/刺鼻味 → "建議通報：119；先遠離現場、避免點火或開關電器"
- 登山迷路/山難/溺水 → "建議通報：119；提供座標、步道名稱、同行人數與最後聯絡時間"
- 火災/濃煙 → "建議派遣：消防隊"
- 醫療急症 → "建議派遣：救護車"
- 暴力/可疑人士 → "建議派遣：警察"
- 交通事故（有人傷） → "建議派遣：警察與救護車"

急救行動指引（多輪引導用，只在使用者請求現場處置時提供步驟）：

【CPR 叫叫壓電】多輪引導節奏：
- 第1輪：先確認意識（叫叫），請使用者呼叫 119，確認有無 AED
- 第2輪：指導開始壓胸——掌根放胸骨下半段，深度 5–6 cm，速率 100–120 次/分鐘，壓完完全放鬆
- 第3輪：AED 到了則引導貼片（右鎖骨下、左腋下）→分析→電擊→恢復壓胸；未到則繼續壓胸並鼓勵
⚠ 瀕死式呼吸（偶爾喘息、打鼾聲）= 無正常呼吸，應視為需要 CPR

【哈姆立克法】多輪引導節奏：
- 先確認年齡（1 歲以上 vs 嬰兒）
- 1 歲以上：站到傷者身後→環抱上腹（肚臍上兩指）→握拳向內向上推壓→確認排出
- 嬰兒：頭低趴在手臂上→掌根拍背 5 次→翻轉壓胸 5 次→確認反應→必要時 CPR

【直接加壓止血】多輪引導節奏：
- 先確認是否有異物插入：有異物→不拔，兩側固定加壓；無異物→直接壓住傷口
- 持續加壓 5–10 分鐘不放開，抬高傷肢，布滲血再加布
- 每輪確認流血是否減少，並提醒持續等待 119 """

MULTI_TURN_GENERATOR_PROMPT += _GUIDE_SUPPLEMENT


TRAINING_SYSTEM_PROMPT = (
    "你是 E-CARE 的緊急關懷助理，要像冷靜、可靠、有同理心的真人助理一樣回應。\n"
    "只輸出 JSON，不要加入其他文字。請使用繁體中文。\n"
    "category 只能是：火災、可疑人士、噪音、醫療急症、暴力事件、交通事故、待確認\n"
    "risk_level 只能是：Low、Medium、High\n"
    "如果使用者提到闖入、持刀、濃煙、明火、無反應、昏倒、流血、呼吸困難，risk_level 應優先判為 High。\n"
    "輸出欄位固定為：reply、risk_score、risk_level、should_escalate、next_question、semantic、extracted\n"
    "不要輸出 extracted_info 或其他替代欄位。\n"
    "semantic 內固定包含：intent、primary_need、emotion、reply_strategy、entities\n"
    "extracted 內固定包含：category、location、people_injured、weapon、danger_active、"
    "reporter_role、conscious、breathing_difficulty、fever、symptom_summary、dispatch_advice、description\n"
    "不可說「我已通知」「我會派遣」「我們會馬上處理」；只能建議使用者撥打 110 或 119。"
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

_BAD_PHRASES = [
    "已經通知", "已通知", "我會通知", "我們會通知",
    "已經派遣", "已派遣", "我會派", "我們會馬上",
    "已經聯絡", "已聯絡警方", "已安排",
]

_SIMPLIFIED_CHARS = "这那还没说个时间来问题处理通知确认"


def _quality_ok(turns: list) -> bool:
    for turn in turns:
        if turn.get("role") != "assistant":
            continue
        content = turn.get("content", "")
        if any(phrase in content for phrase in _BAD_PHRASES):
            return False
        simplified_count = sum(1 for ch in content if ch in _SIMPLIFIED_CHARS)
        if simplified_count >= 3:
            return False
    return True


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
        emotion = a.get("emotion") or ("fearful" if risk_level in ["High", "Medium"] else "neutral")
        intent = a.get("intent") or ("求救" if risk_level == "High" else "通報")
        reporter_role = a.get("reporter_role") or None
        full = {
            "reply": a.get("reply", ""),
            "risk_score": a.get("risk_score", 0.5),
            "risk_level": risk_level,
            "should_escalate": a.get("should_escalate", risk_level == "High"),
            "next_question": a.get("next_question", ""),
            "semantic": {
                "intent": intent,
                "primary_need": "立即安全協助" if risk_level == "High" else "釐清狀況",
                "emotion": emotion,
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
                "reporter_role": reporter_role, "conscious": None,
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

            if turns and _quality_ok(turns):
                record = {
                    "messages": [{"role": "system", "content": TRAINING_SYSTEM_PROMPT}] + turns
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                generated += 1
                n = len([t for t in turns if t["role"] == "user"])
                print(f"OK（{n} 輪）")
            elif turns:
                failed += 1
                print("品質過濾（含禁用語句或簡體字）")
            else:
                failed += 1
                print("失敗")

            time.sleep(args.delay)

    print(f"\n完成：{generated} 筆成功，{failed} 筆失敗 → {output_path}")


if __name__ == "__main__":
    main()
