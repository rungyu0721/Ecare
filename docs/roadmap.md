# E-CARE Roadmap

這份文件用來記錄接下來要補強的功能與工程待辦。優先順序會隨 demo、測試結果與實際使用回饋調整。

## P0：穩定性與回歸檢查

- [x] 新增一鍵檢查腳本：`scripts/run_checks.ps1`
- [x] 後端單元測試、v4 語意測試、v4 上下文測試、Flutter analyze 串成固定流程
- [ ] 將重要 demo 場景整理成固定測試資料
- [ ] 針對 latency 建立基準測試，追蹤 v4 回覆秒數

## P1：語音播報與通報狀態

- [x] 後端 `ChatResponse` 新增 `voice_prompt`
- [x] 後端 `ChatResponse` 新增 `voice_priority`
- [x] 後端 `ChatResponse` 新增 `should_speak`
- [x] 後端 `ChatResponse` 新增 `report_status_hint`
- [x] Flutter 解析並顯示 `voice_prompt` / `report_status_hint`
- [x] Flutter 高風險時提供「重播語音提示」按鈕
- [x] Flutter 加入本機 TTS 作為短期 demo 方案
- [ ] 評估本地部署 TTS 模型，優先測試 `CosyVoice2-0.5B`
- [ ] 將雲端 TTS API 作為 fallback，而不是第一優先

### 本地 TTS 模型整合方向

目標：讓 E-CARE 在高風險情境能用自然語音播報 `voice_prompt`，例如「系統已列為高風險通報，請確認患者是否有正常呼吸」。

建議架構：

```text
Flutter -> FastAPI -> Local TTS service -> FastAPI -> Flutter
```

注意事項：

- Flutter 只呼叫自己的 FastAPI，不直接呼叫外部 TTS 服務。
- TTS 模型獨立成後端服務，避免阻塞 `/chat`。
- 優先支援繁體中文語音。
- 高風險、需要立即行動時才自動播報，避免一般對話過度打擾。
- 保留雲端 API 或系統 TTS fallback，避免本地模型啟動失敗時完全不能播報。

候選模型：

- [ ] `CosyVoice2-0.5B`：優先評估，較適合中文/多語 TTS。
- [ ] `VibeVoice-Realtime-0.5B`：低延遲候選，但官方定位偏英文，需實測中文效果。
- [ ] 雲端 TTS API：作為 fallback 或正式部署備案。

待確認項目：

- [ ] 本地 TTS 模型部署方式與 GPU/CPU 需求
- [ ] 中文輸入的延遲、音質、穩定性
- [ ] 是否支援串流輸出
- [ ] 後端新增 `/tts` 或 `/voice` endpoint
- [ ] Flutter 播放後端回傳音檔或串流
- [ ] 語音播報內容需明確標示為 AI 生成或系統提示
- [ ] 若使用雲端 TTS，需控管成本、額度與 API key 安全

## P1：v4 語意理解補強

- [ ] 人工審核 `scripts/data/v4_semantic_candidates*.jsonl`
- [ ] 分批吸收通過審核的候選資料到 `backend/data/v4_semantic_lexicon.json`
- [ ] 將重要候選案例加入 `scripts/data/v4_semantic_cases.jsonl`
- [ ] 補強下列容易混淆情境：
  - 交通事故 vs 醫療急症
  - 可疑人士 vs 暴力事件
  - 噪音 vs 暴力事件
  - 否定句：沒受傷、沒有武器、只是吵架
  - 模糊句：怪怪的、不太對勁、看起來快不行

## P2：通報流程產品化

- [x] 前端顯示通報狀態：
  - `high_risk_detected`
  - `report_recommended`
  - `report_created`
  - `waiting_for_update`
  - `monitoring`
- [ ] 高風險提醒彈窗改成更明確的 E-CARE 通報流程
- [ ] 加入「救援已抵達」、「情況緩和」、「我已安全」等狀態按鈕
- [ ] DB 記錄通報狀態歷程

## P2：急救知識資料化

- [ ] 將硬編碼在 `postprocess.py` 的急救回覆整理成資料檔
- [ ] 新增 `backend/data/first_aid_guides.json`
- [ ] 新增 `backend/services/first_aid_guides.py`
- [ ] 支援資料化情境：
  - CPR / AED
  - 異物哽塞
  - 大量出血
  - 燒燙傷
  - 癲癇
  - 中暑
  - 胸痛
  - 骨折

## P3：部署與安全

- [ ] CORS 改成環境變數控制，不再固定 `allow_origins=["*"]`
- [ ] 對外部署前加入 API key 或 token 驗證
- [ ] 敏感環境變數只放 `.env` 或部署平台 secret
- [ ] 建立正式資料庫 migration 流程
- [ ] 補充 Docker / Windows / 遠端 GPU 的部署文件
