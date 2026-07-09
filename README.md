# E-CARE

E-CARE 是一個面向偏鄉、山區與國家公園場域的緊急救援輔助系統。後端使用 FastAPI，前端使用 Flutter，LLM 主線使用本機 Ollama 模型 `ecare-v4:latest`。

目前 v4 版本重點：

- 使用情境：偏鄉急症、登山迷路、山域/水域受困、國家公園救援、天然災害、電梯受困、失蹤走失、交通事故、火災、自殺危機、暴力事件。
- 事件分類：醫療急症、火災、天然災害、受困救援、自殺危機、失蹤走失、山域水域救援、交通事故、暴力事件、可疑人士、噪音、待確認。
- 語意理解：支援否定句、不確定句、模糊描述與多輪上下文。
- 高風險處理：若判斷需要警察、消防或醫療單位協助，立即引導撥打 110 或 119；系統依事件自動分流，醫療/消防/天然災害/受困救援/山域水域救援偏 119，自殺危機同步 119 與 110，失蹤走失/暴力/犯罪/人身威脅偏 110，混合情境提醒同步通報。
- 救援資訊整理：優先整理 GPS 座標、步道/地標、同行人數、傷勢、可否移動、手機電量、訊號、天候與天色。
- 急救引導：支援無反應/呼吸異常、噎到、出血、癲癇、中暑、失溫、胸痛、骨折等基本情境；山區/偏鄉不假設附近有 AED，除非使用者明確表示現場有 AED。

## 系統架構

```text
使用者文字/語音 + GPS 定位
  -> Flutter 前端
  -> FastAPI /chat
  -> 事件抽取、風險判斷、多輪狀態整理
  -> RAG / Neo4j / incident taxonomy 補充救援知識
  -> 110/119 建議、救援資訊摘要、語音提示
  -> 通報紀錄與狀態更新
```

E-CARE 的重點是把使用者混亂或片段式的描述整理成救援單位需要的資訊，例如位置、地標、同行人數、傷勢、是否受困、手機電量與現場危險。

## RAG 與知識來源

E-CARE 使用兩層知識輔助聊天機器人：

- Neo4j 知識圖譜：若本機 Neo4j 有事件節點、關鍵字與建議處置，系統會查詢並注入 prompt。
- 本地 taxonomy fallback：若 Neo4j 沒有資料或查不到，系統仍會使用 `backend/data/incident_taxonomy.json` 的台灣事件分類與山域/水域救援關鍵字。
- Prompt 補強規則：山區、偏鄉、國家公園、步道、溪谷、林道、手機快沒電、失溫、中暑、高山症等情境會被額外注入為山域/偏鄉救援脈絡；系統仍會依事件判斷 119、110 或同步提醒。

因此即使 demo 環境沒有完整 Neo4j 資料，山域/偏鄉救援判斷仍可透過本地規則穩定運作。

## 支援事件類型與分流

目前聊天機器人會將使用者描述整理成下列主要事件類型：

- `醫療急症`：OHCA、沒呼吸、昏倒、中風、心肌梗塞、胸痛、大量出血、中暑、失溫等，通常建議 119。
- `火災`：火災、濃煙、瓦斯味、爆炸、電梯冒煙受困等，通常建議 119。
- `天然災害`：地震、颱風、淹水、土石流、建築物倒塌、道路中斷等，通常建議 119 或地方災害應變單位。
- `受困救援`：電梯受困、困在電梯、電梯門打不開等，通常建議 119。
- `自殺危機`：自殺、跳樓、割腕、吞藥、燒炭、上吊等，通常同步建議 119 與 110。
- `失蹤走失`：市區老人走失、小孩失蹤、家人失聯等，通常建議 110；若在山區、水域、偏鄉或可能受困受傷，會同步提醒 119。
- `山域水域救援`：山區、步道、國家公園、溪谷、林道的迷路、失聯、受困、低電量、沒訊號、落石坍方、溪水暴漲等，通常建議 119。
- `交通事故`、`暴力事件`、`可疑人士`、`噪音`：依是否有人受傷、武器、持續危險或犯罪情境，建議 110、119 或同步通報。

## 使用限制

- E-CARE 不能取代 119、110 或專業救援人員。
- 系統不能保證已完成派遣；高風險時仍會引導使用者直接撥打 119 或 110。
- GPS 可能有誤差，山區或偏鄉應搭配步道名稱、里程牌、登山口、山屋、溪谷、明顯地標與同行人數描述。
- 山區訊號不穩或手機快沒電時，應優先保留電力；若是受困、受傷、火災、水域或醫療急症，將座標與地標提供給 119；若是暴力、犯罪或人身威脅，將位置與對方特徵提供給 110。
- 山區/偏鄉不假設附近有 AED；只有使用者明確說現場有 AED 時，系統才會進入 AED 操作引導。
- 急救建議僅作為等待專業救援前的基本安全引導，現場若有 119 指示，應以 119 指示為準。

## Demo 場景

建議展示情境請看 `docs/demo_scenarios.md`，目前整理了：

- 國家公園步道迷路，手機快沒電
- 山上摔傷不能走
- 溪水暴漲受困
- 山上失溫與手機低電量
- 偏鄉家人胸痛、冒冷汗且救護車定位困難
- 地震後建築物倒塌，有人被壓住
- 電梯受困且有人不舒服
- 市區小孩走失，最後出現在公園附近
- 自殺危機或跳樓通報，需要同步 119 與 110

## 專案結構

```text
Ecare/
├── backend/          # FastAPI 後端、事件判斷、風險評估、LLM 對話流程
├── flutter_app/      # Flutter 前端，支援 Windows / Android / iOS
├── scripts/          # 訓練資料、語意候選、測試與模型工具
├── Modelfile         # Ollama v4 模型設定
├── docker-compose.yml
├── requirements.txt
└── requirements-train.txt
```

## 需求

- Python 3.11+
- Flutter SDK
- Ollama
- PostgreSQL
- Neo4j
- FFmpeg

## 後端啟動

### 1. 建立 Ollama 模型

```powershell
ollama create ecare-v4:latest -f Modelfile
```

確認模型：

```powershell
ollama ps
```

### 2. 建立 `.env`

複製 `.env.example` 為 `.env`，再填入本機資料庫設定。

```env
LLM_PROVIDER=ollama
LLM_MODEL=ecare-v4:latest
OLLAMA_BASE_URL=http://127.0.0.1:11434

DB_HOST=your_postgres_host
DB_PORT=5432
DB_NAME=ecare_db
DB_USER=postgres
DB_PASSWORD=your_password

NEO4J_URI=bolt://your_neo4j_host:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

### 3. 安裝後端依賴

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

若要訓練模型或執行 LoRA/GPU 相關工具，再另外安裝：

```powershell
pip install -r requirements-train.txt
```

GPU 版 PyTorch 請依照自己的 CUDA 版本到 PyTorch 官方指令安裝，不建議直接把本機 `pip freeze` 的 dev wheel 當成通用需求。

### 4. 啟動後端

第一次設定時，先複製範例啟動腳本：

```powershell
Copy-Item start_backend.ps1.example start_backend.ps1
```

如果你的本機需要特殊環境變數，可以修改複製出來的 `start_backend.ps1`。這個檔案已被 `.gitignore` 排除，避免不小心提交密碼或 API key。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_backend.ps1
```

`start_backend.ps1` 是本機啟動腳本，會讀取 `.env` 並啟動 FastAPI。請不要把含有真實密碼或 API key 的版本提交到 git。

## Docker

只啟動資料庫：

```powershell
docker compose up -d postgres neo4j
```

啟動完整服務：

```powershell
docker compose up -d
```

## Flutter 啟動

```powershell
cd flutter_app
flutter pub get
flutter run -d windows
```

Android 實機測試時，請把 API 位址改成電腦的區網 IP：

```powershell
flutter run -d android --dart-define=API_BASE_URL=http://192.168.x.x:8000
```

## 測試

後端單元測試：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

v4 語意與上下文回歸測試：

```powershell
.\.venv\Scripts\python.exe scripts/test_v4_semantics.py
.\.venv\Scripts\python.exe scripts/test_v4_context.py
```

Flutter 靜態檢查：

```powershell
cd flutter_app
flutter analyze
```

也可以一次跑完整檢查：

```powershell
.\scripts\run_checks.ps1
```

目前已確認：

- `pytest`: 77 passed
- `scripts/test_v4_semantics.py`: 36/36 passed
- `scripts/test_v4_context.py`: 52/52 passed
- `flutter analyze`: No issues found

## 主要 API

- `/chat`：文字對話、事件抽取、風險判斷、多輪上下文與山域/偏鄉救援資訊整理。
- `/audio`：語音輸入與轉文字。
- `/reports`：事件通報資料 CRUD。

詳細格式請看 `API_SPEC.md`。

## Roadmap

後續功能待辦與語音播報規劃請看 `docs/roadmap.md`。

## 訓練與語意資料

重要資料：

- `scripts/data/v4_semantic_cases.jsonl`：語意規則回歸測試。
- `scripts/data/v4_context_cases.jsonl`：多輪上下文回歸測試。
- `backend/data/v4_semantic_lexicon.json`：v4 語意詞庫。
- `backend/data/incident_taxonomy.json`：台灣事件分類、山域/水域救援關鍵字與 110/119 建議。
- `backend/data/incident_response_guides.json`：事件與急救知識參考。

大型訓練資料與模型輸出不進 git：

- `scripts/data/ecare_train_*.jsonl`
- `scripts/data/v4_standard.jsonl`
- `scripts/data/v4_multiturn.jsonl`
- `scripts/data/v4_semantic_candidates*.jsonl`
- `scripts/output/*.gguf`

## Git 注意事項

請勿提交：

- `.env`
- `.venv/`
- `scripts/output/`
- `*.gguf`
- `torch_wheels/`
- `wheels_linux/`
- Flutter build 產物

建議提交：

- 後端程式碼
- Flutter 程式碼
- v4 語意詞庫
- v4 回歸測試資料
- README / API 文件

## 常用指令

```powershell
# 後端
.\start_backend.ps1

# 後端測試
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/test_v4_semantics.py
.\.venv\Scripts\python.exe scripts/test_v4_context.py
.\scripts\run_checks.ps1

# Flutter
cd flutter_app
flutter run -d windows
flutter analyze

# Git
git status
git add -A
git commit -m "整理 v4 專案"
git push
```
