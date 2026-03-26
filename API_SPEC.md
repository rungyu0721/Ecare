# E-CARE FastAPI 串接規格

## 1. Base URL

請依實際部署環境替換：

```text
http://<your-fastapi-host>:8000
```

範例：

```text
http://192.168.50.254:8000
```

## 2. 認證方式

目前版本：

- 不需要登入
- 不需要 Bearer Token
- 不需要 API Key 才能呼叫本地 FastAPI

注意：

- 若未來要對外網開放，建議再補 API Key 或 Token 驗證

## 3. API 一覽

目前可串接的 API：

- `POST /chat`
- `POST /audio`
- `GET /reports`
- `POST /reports`

---

## 4. `POST /chat`

用途：

- 傳入聊天內容
- 由後端進行情境判斷、風險評估、語意理解
- 回傳助理回覆、追問、事件抽取與語意分析結果

### Request Body

```json
{
  "messages": [
    {
      "role": "user",
      "content": "有人受傷了，快幫我"
    }
  ],
  "audio_context": {
    "transcript": "有人受傷了，快幫我",
    "emotion": "panic",
    "emotion_score": 0.92,
    "situation": "醫療急症",
    "risk_level": "High",
    "risk_score": 0.91,
    "extracted": {
      "category": "醫療急症",
      "location": "台北車站",
      "people_injured": true,
      "weapon": false,
      "danger_active": true,
      "dispatch_advice": "建議派遣：消防/救護",
      "description": "現場有人受傷"
    }
  }
}
```

### Request 欄位說明

- `messages`: 對話陣列
- `messages[].role`: `user` 或 `assistant`
- `messages[].content`: 對話文字
- `audio_context`: 可選，語音分析結果
- `audio_context.transcript`: 語音轉文字內容
- `audio_context.emotion`: 情緒標籤，例如 `panic`、`sad`、`angry`
- `audio_context.emotion_score`: 情緒信心分數
- `audio_context.situation`: 語音分析得到的情境
- `audio_context.risk_level`: `Low`、`Medium`、`High`
- `audio_context.risk_score`: 風險分數
- `audio_context.extracted`: 語音分析抽出的事件欄位

### Response Body

```json
{
  "reply": "我知道你現在很慌，我會先陪你把重點整理清楚。",
  "risk_score": 0.91,
  "risk_level": "High",
  "should_escalate": true,
  "next_question": "你現在人在哪裡？請告訴我地址、明顯地標，或附近路名。",
  "extracted": {
    "category": "醫療急症",
    "location": "台北車站",
    "people_injured": true,
    "weapon": false,
    "danger_active": true,
    "dispatch_advice": "建議派遣：消防/救護",
    "description": "案件類型：醫療急症 | 地點：台北車站 | 傷勢：現場有人受傷或需要醫療協助 | 危險狀況：事件仍在持續 | 風險等級：High | 建議派遣：消防/救護"
  },
  "semantic": {
    "intent": "求救",
    "primary_need": "立即安全協助",
    "emotion": "panic",
    "reply_strategy": "先安撫，再確認位置與安全",
    "entities": {
      "location": "台北車站",
      "injured": true,
      "weapon": false,
      "danger_active": true
    }
  }
}
```

### Response 欄位說明

- `reply`: 給使用者看的助理回覆
- `risk_score`: 風險分數，`0.0 ~ 1.0`
- `risk_level`: `Low`、`Medium`、`High`
- `should_escalate`: 是否建議升級處理
- `next_question`: 下一個追問
- `extracted`: 事件抽取結果
- `semantic`: 文字語意理解結果

### `extracted` 欄位

- `category`: 事件類型
- `location`: 地點
- `people_injured`: 是否有人受傷
- `weapon`: 是否有武器
- `danger_active`: 危險是否仍在持續
- `dispatch_advice`: 建議派遣方式
- `description`: 後端整理後的摘要

### `semantic` 欄位

- `intent`: 使用者意圖，例如 `求救`、`通報`、`詢問`
- `primary_need`: 當下最主要需求
- `emotion`: 語意層判斷的情緒
- `reply_strategy`: 助理建議回應策略
- `entities`: 語意層抽出的重點資訊

---

## 5. `POST /audio`

用途：

- 上傳錄音檔
- 後端做語音辨識、情緒辨識、風險分析

### Request

Content-Type:

```text
multipart/form-data
```

欄位：

- `audio`: 檔案欄位

支援格式：

- `.webm`
- `.wav`
- `.mp3`
- `.m4a`
- `.ogg`
- `.aac`

### Response Body

```json
{
  "transcript": "有人受傷了，快幫我",
  "emotion": "panic",
  "emotion_score": 0.92,
  "situation": "醫療急症",
  "risk_level": "High",
  "risk_score": 0.91,
  "extracted": {
    "category": "醫療急症",
    "location": "台北車站",
    "people_injured": true,
    "weapon": false,
    "danger_active": true,
    "dispatch_advice": "建議派遣：消防/救護",
    "description": "現場有人受傷"
  }
}
```

---

## 6. `GET /reports`

用途：

- 取得目前所有案件紀錄

### Response Body

```json
[
  {
    "id": "A123",
    "title": "醫療急症",
    "category": "醫療急症",
    "location": "台北車站",
    "status": "待處理",
    "created_at": "2026/03/26 14:30",
    "risk_level": "High",
    "risk_score": 0.91,
    "description": "案件摘要"
  }
]
```

---

## 7. `POST /reports`

用途：

- 建立案件紀錄

### Request Body

```json
{
  "title": "醫療急症",
  "category": "醫療急症",
  "location": "台北車站",
  "risk_level": "High",
  "risk_score": 0.91,
  "description": "案件摘要"
}
```

### Response Body

```json
{
  "id": "A123",
  "title": "醫療急症",
  "category": "醫療急症",
  "location": "台北車站",
  "status": "待處理",
  "created_at": "2026/03/26 14:30",
  "risk_level": "High",
  "risk_score": 0.91,
  "description": "案件摘要"
}
```

---

## 8. 建議資料庫欄位

如果組員要把 FastAPI 結果存進資料庫，建議至少準備兩類資料表。

### A. 案件主表 `reports`

建議欄位：

- `id`: string
- `title`: string
- `category`: string
- `location`: string
- `status`: string
- `created_at`: datetime 或 string
- `risk_level`: string
- `risk_score`: float
- `description`: text

### B. 聊天分析表 `chat_logs` 或 `chat_analysis`

建議欄位：

- `id`: string / uuid
- `session_id`: string
- `user_message`: text
- `assistant_reply`: text
- `next_question`: text
- `risk_level`: string
- `risk_score`: float
- `should_escalate`: boolean
- `intent`: string
- `primary_need`: string
- `emotion`: string
- `reply_strategy`: string
- `category`: string
- `location`: string
- `people_injured`: boolean
- `weapon`: boolean
- `danger_active`: boolean
- `dispatch_advice`: string
- `created_at`: datetime

---

## 9. 型別建議

- `risk_score`: `FLOAT`
- `emotion_score`: `FLOAT`
- `should_escalate`: `BOOLEAN`
- `people_injured`: `BOOLEAN NULL`
- `weapon`: `BOOLEAN NULL`
- `danger_active`: `BOOLEAN NULL`
- `description`: `TEXT`
- `reply`: `TEXT`
- `next_question`: `TEXT`

---

## 10. 錯誤處理

常見狀況：

- `400`: 請求格式錯誤
- `500`: 後端處理錯誤
- `503`: 模型未載入完成，例如 Whisper / Emotion model / Gemini 未就緒

建議組員串接時至少處理：

- HTTP status code
- timeout
- 回傳欄位缺漏時的 fallback

---

## 11. 串接注意事項

- `POST /chat` 的 `audio_context` 是可選欄位
- `POST /audio` 上傳時必須用 `multipart/form-data`
- `POST /reports` 目前是記憶體暫存，若 FastAPI 重啟，資料會消失
- 若要正式接資料庫，建議把 `REPORTS = []` 改成真正 DB 存取
- `GOOGLE_API_KEY` 沒設定時，`/chat` 會走 fallback 邏輯，不一定會有完整 LLM 品質

---

## 12. 建議你給組員的最小資訊包

你可以直接把下面這些丟給組員：

1. `Base URL`
2. `POST /chat` request / response 範例
3. `POST /audio` request / response 範例
4. `GET /reports` / `POST /reports` 格式
5. 建議資料庫欄位清單
6. 是否需要認證
7. 哪些欄位可能為 `null`

