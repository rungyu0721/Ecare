# E-CARE FastAPI 串接規格

## 1. Base URL

請依實際部署環境替換：

```text
http://<your-fastapi-host>:8000
```

範例：

```text
http://192.168.x.x:8000
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
- `POST /tts`
- `GET /reports`
- `POST /reports`

---

## 4. `POST /chat`

用途：

- 傳入聊天內容
- 由後端進行情境判斷、風險評估、語意理解
- 依事件內容判斷應建議 119、110，或兩者都需要
- 山域/偏鄉/國家公園情境會優先整理 GPS、地標、同行人數、傷勢、手機電量與訊號
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
  "voice_prompt": "系統已列為高風險通報。請保持手機可接通，確認患者是否有正常呼吸。",
  "voice_priority": "high",
  "should_speak": true,
  "tts_key": "8b5d0f9b3d1f4c2a9e10",
  "report_status_hint": "report_recommended",
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
- `voice_prompt`: 適合語音播報的短句，通常比 `reply` 更短、更行動導向
- `voice_priority`: 語音提示優先度，可能值為 `low`、`medium`、`high`
- `should_speak`: 前端是否建議播報 `voice_prompt`
- `tts_key`: 後端預先合成語音的快取 key；前端可先呼叫 `GET /tts/ready/{tts_key}` 取得 wav，失敗時再 fallback 到 `POST /tts`
- `report_status_hint`: 通報狀態提示，供前端顯示 UI 狀態
- `extracted`: 事件抽取結果
- `semantic`: 文字語意理解結果

### 110 / 119 分流原則

`/chat` 不會宣稱已替使用者完成派遣，只會依情境建議使用者聯絡合適單位：

- 醫療急症、火災、山域/水域救援、受困、失溫、中暑、高山症、溪水暴漲：通常建議 119
- 暴力、犯罪、持刀、跟蹤、闖入、人身威脅：通常建議 110
- 若同時有人受傷、火災或受困：提醒 110 與 119 都需要
- 山區/偏鄉不假設附近有 AED；除非使用者明確說現場有 AED，否則不主動要求尋找 AED

### `report_status_hint` 可能值

- `none`: 不需要顯示通報狀態
- `monitoring`: 持續觀察中
- `high_risk_detected`: 已偵測高風險，但資料仍不完整
- `report_recommended`: 建議建立通報
- `report_created`: 通報已建立
- `waiting_for_update`: 等待現場更新

### `extracted` 欄位

- `category`: 事件類型
- `location`: 地點
- `people_injured`: 是否有人受傷
- `weapon`: 是否有武器
- `danger_active`: 危險是否仍在持續
- `dispatch_advice`: 建議派遣方式
- `description`: 後端整理後的摘要

山域/偏鄉情境通常會把「疑似山域水域救援」保留在 `symptom_summary` 或 `description`，並在 `dispatch_advice` 裡提示使用者提供 GPS 座標、步道/地標、同行人數、傷勢、可否移動、手機電量與天候。暴力或犯罪情境則會在 `dispatch_advice` 中偏向警察，若有人受傷則同步提醒救護。

### `semantic` 欄位

- `intent`: 使用者意圖，例如 `求救`、`通報`、`詢問`
- `primary_need`: 當下最主要需求
- `emotion`: 語意層判斷的情緒
- `reply_strategy`: 助理建議回應策略
- `entities`: 語意層抽出的重點資訊

---

## 5. `POST /tts`

用途：

- 將 `voice_prompt` 轉成 wav 語音。
- 前端只呼叫 E-CARE FastAPI，不直接碰本地 CosyVoice2 service。
- 後端會代理到 `TTS_BASE_URL`，預設是 `http://127.0.0.1:8011`。

啟動需求：

```powershell
.\start_tts.ps1
.\start_backend.ps1
```

### Request Body

```json
{
  "text": "系統已列為高風險通報，請確認患者是否有正常呼吸。",
  "mode": "zero-shot",
  "speed": 1.0
}
```

欄位：

- `text`: 必填，1 到 300 字，建議使用 `ChatResponse.voice_prompt`
- `mode`: 可選，`zero-shot` 或 `instruct2`，預設 `zero-shot`
- `speed`: 可選，0.5 到 1.5，預設由 TTS service 決定

### Response

成功時回傳 `audio/wav`。

```text
Content-Type: audio/wav
```

常見錯誤：

- `503`: 本地 TTS service 沒啟動，或 `TTS_BASE_URL` 連不到
- `502`: 本地 TTS service 有回應，但合成失敗或沒有產生音訊

PowerShell 測試：

```powershell
$body = [System.Text.Encoding]::UTF8.GetBytes('{"text":"系統已列為高風險通報，請確認患者是否有正常呼吸。"}')
Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/tts `
  -Method POST `
  -ContentType "application/json" `
  -Body $body `
  -OutFile scripts\output\fastapi_tts_test.wav
```

---

## 6. `GET /tts/ready/{key}`

用途：

- 取得 `/chat` 回傳 `tts_key` 對應的預先合成語音。
- 主要給 Flutter 在收到聊天回覆後立即播放，降低等待語音合成的體感延遲。
- 如果 key 過期、尚未建立或合成失敗，前端應 fallback 到 `POST /tts`。

### Response

成功時回傳 `audio/wav`。

常見錯誤：

- `404`: 找不到此 `tts_key`，通常代表沒有預合成或快取已被清掉
- `504`: 等待預合成逾時
- `502`: 預合成任務失敗

PowerShell 測試：

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/tts/ready/<tts_key> `
  -OutFile scripts\output\fastapi_tts_ready_test.wav
```

---

## 7. `POST /audio`

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

## 8. `GET /reports`

用途：

- 取得目前所有案件紀錄

### Response Body

```json
[
  {
    "id": "A202607090001",
    "title": "醫療急症",
    "category": "醫療急症",
    "location": "台北車站",
    "latitude": 25.047756,
    "longitude": 121.517030,
    "status": "待處理",
    "created_at": "2026/03/26 14:30",
    "risk_level": "High",
    "risk_score": 0.91,
    "description": "案件摘要"
  }
]
```

---

## 9. `POST /reports`

用途：

- 建立案件紀錄

### Request Body

```json
{
  "title": "醫療急症",
  "category": "醫療急症",
  "location": "台北車站",
  "latitude": 25.047756,
  "longitude": 121.517030,
  "risk_level": "High",
  "risk_score": 0.91,
  "description": "案件摘要"
}
```

### Response Body

```json
{
  "id": "A202607090001",
  "title": "醫療急症",
  "category": "醫療急症",
  "location": "台北車站",
  "latitude": 25.047756,
  "longitude": 121.517030,
  "status": "待處理",
  "created_at": "2026/03/26 14:30",
  "risk_level": "High",
  "risk_score": 0.91,
  "description": "案件摘要"
}
```

管理端顯示建議：

- `location`、`latitude`、`longitude` 屬於位置資訊，建議集中顯示在位置區塊或地圖按鈕旁。
- `description` 只放通報內容、人員資訊與補充說明；不要再從 `description` 解析位置，避免與上方位置欄重複。
- `id` 採 `AYYYYMMDDNNNN` 格式，例如 `A202607090001`，前 8 碼日期代表建立日期，最後 4 碼為當日流水號。管理端建議完整顯示或至少保留日期與流水號，不要只截取末 4 碼。

---

## 10. 建議資料庫欄位

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

## 11. 型別建議

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

## 12. 錯誤處理

常見狀況：

- `400`: 請求格式錯誤
- `500`: 後端處理錯誤
- `503`: 模型或服務未載入完成，例如 Whisper、Emotion model、Ollama v4 未就緒

建議組員串接時至少處理：

- HTTP status code
- timeout
- 回傳欄位缺漏時的 fallback

---

## 13. 串接注意事項

- `POST /chat` 的 `audio_context` 是可選欄位
- `POST /audio` 上傳時必須用 `multipart/form-data`
- `POST /reports` 會寫入 PostgreSQL；資料庫不可用時後端會回傳錯誤
- 目前主要 LLM provider 是 Ollama，建議使用 `LLM_MODEL=ecare-v4:latest`
- 若 Ollama 或指定模型未啟動，`/chat` 會走 fallback 邏輯，品質會低於 v4 模型

---

## 14. 建議你給組員的最小資訊包

你可以直接把下面這些丟給組員：

1. `Base URL`
2. `POST /chat` request / response 範例
3. `POST /audio` request / response 範例
4. `GET /reports` / `POST /reports` 格式
5. 建議資料庫欄位清單
6. 是否需要認證
7. 哪些欄位可能為 `null`
