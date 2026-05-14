# E-CARE

E-CARE 是一個緊急事件輔助系統，後端使用 FastAPI，前端使用 Flutter，LLM 主線使用本機 Ollama 模型 `ecare-v4:latest`。

目前 v4 版本重點：

- 事件分類：醫療急症、交通事故、火災、暴力事件、可疑人士、噪音。
- 語意理解：支援否定句、不確定句、模糊描述與多輪上下文。
- 高風險處理：以「系統列為高風險通報」為主，不重複要求使用者自行撥打 119。
- 急救引導：支援無反應/呼吸異常、AED、噎到、出血、癲癇、中暑、胸痛、骨折等基本情境。

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

目前已確認：

- `pytest`: 77 passed
- `scripts/test_v4_semantics.py`: 36/36 passed
- `scripts/test_v4_context.py`: 52/52 passed
- `flutter analyze`: No issues found

## 主要 API

- `/chat`：文字對話、事件抽取、風險判斷、多輪上下文。
- `/audio`：語音輸入與轉文字。
- `/reports`：事件通報資料 CRUD。

詳細格式請看 `API_SPEC.md`。

## 訓練與語意資料

重要資料：

- `scripts/data/v4_semantic_cases.jsonl`：語意規則回歸測試。
- `scripts/data/v4_context_cases.jsonl`：多輪上下文回歸測試。
- `backend/data/v4_semantic_lexicon.json`：v4 語意詞庫。
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
