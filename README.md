# E-CARE

緊急事件關懷對話系統。後端使用 FastAPI + Ollama（本地 LLM），前端使用 Flutter。

## 架構

```
Ecare/
├── backend/          # FastAPI 後端（聊天、語音、通報）
├── flutter_app/      # Flutter 前端（Windows / Android / iOS）
├── scripts/          # 訓練腳本與測試工具
├── Modelfile         # Ollama 模型設定（ecare-v4）
├── docker-compose.yml
└── requirements.txt
```

## 開發環境需求

- Python 3.11+
- Flutter SDK 3.3+
- [Ollama](https://ollama.com)（本地 LLM）
- PostgreSQL
- Neo4j（選用）
- FFmpeg（語音功能）

---

## 後端啟動

### 1. 建立 Ollama 模型

```powershell
ollama create ecare-v4:latest -f Modelfile
```

### 2. 啟動後端

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_backend.ps1
```

`start_backend.ps1` 會自動從 `.env` 載入環境變數（資料庫、Neo4j、LLM 設定）。

**啟動成功應看到：**
```
PostgreSQL 已連線
Ollama 已初始化
Emotion model 已載入
```

### 環境變數（.env）

複製 `.env.example` 為 `.env` 並填入設定：

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

### 手動安裝套件（首次設定）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> GPU 版 torch（CUDA）需另外從 PyTorch 官網安裝，requirements.txt 記錄的是目前 .venv 的版本。

---

## Docker 啟動（PostgreSQL + Neo4j）

只需啟動資料庫服務時使用（Ollama 仍在宿主機執行）：

```powershell
docker compose up -d postgres neo4j
```

或完整啟動含後端：

```powershell
docker compose up -d
```

---

## Flutter 前端啟動

```powershell
cd flutter_app
flutter pub get
flutter run -d windows
```

預設連線後端：`http://127.0.0.1:8000`

部署到其他裝置時指定後端位址：

```powershell
flutter run -d android --dart-define=API_BASE_URL=http://192.168.x.x:8000
```

---

## 測試

### 單元測試（不需要 GPU 或資料庫）

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### 整合測試（需要後端正在執行）

```powershell
.\.venv\Scripts\python.exe scripts/test_chat_scenarios.py
.\.venv\Scripts\python.exe scripts/test_v4_semantics.py
```

---

## 目前功能

- `/chat`：多輪對話、風險評分、語意理解、slot 填充
- `/audio`：語音轉文字（Whisper）+ 情緒分析
- `/reports`：緊急通報紀錄 CRUD（PostgreSQL）

---

## 注意事項

- **不要 commit `.env`**（已在 .gitignore）
- `.venv/`、Flutter build 產物、模型 .gguf 均已 gitignore
- `scripts/output/` 的模型檔不進 git，請自行備份

## 常用指令

```powershell
# 後端
.\start_backend.ps1

# 測試
.\.venv\Scripts\python.exe -m pytest

# Flutter
cd flutter_app && flutter run -d windows

# Git
git status
git add -A
git commit -m "訊息"
git push
```
