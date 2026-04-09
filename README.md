# E-CARE

E-CARE 是一個緊急事件協助專案，目前架構分成兩部分：

- `backend/`：FastAPI 後端，負責聊天分析、語音分析、通報紀錄
- `flutter_app/`：Flutter 前端，取代原本的 Web / Capacitor 版本

## 專案結構

```text
Ecare/
├─ backend/
├─ flutter_app/
├─ API_SPEC.md
└─ README.md
```

## 開發需求

- Python 3.11 以上
- Flutter SDK
- PostgreSQL
- FFmpeg

## 後端啟動方式

### 建議方式：直接使用啟動腳本

請在專案根目錄 `d:\Ecare\Ecare` 執行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_backend.ps1
```

`start_backend.ps1` 會先幫你設定：

- PostgreSQL 連線資訊
- Neo4j 連線資訊
- Gemma / LLM 相關環境變數
- 優先使用 `.venv\Scripts\python.exe`

因此平常開發請優先用 `.\start_backend.ps1`，不要直接手動打 `uvicorn`。

如果你看到下面這些訊息，通常代表你是直接跑了 `uvicorn`，沒有載入腳本內的環境變數：

- `PostgreSQL 連線失敗 ... localhost:5432`
- `找不到 GOOGLE_API_KEY，/chat 將使用 fallback`
- `Neo4j 連線失敗：NEO4J_URI 或 NEO4J_PASSWORD 尚未設定`

### 手動啟動方式

只有在你想自行排錯或改連線設定時，才建議手動啟動。

1. 建立並啟用虛擬環境：

```powershell
cd C:\Users\User\Documents\Ecare
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. 安裝後端需要的套件  
如果你之後有整理 `requirements.txt`，就改成用那份安裝。  
目前可先安裝後端實際使用到的套件：

```powershell
pip install fastapi uvicorn whisper psycopg2-binary numpy librosa joblib python-multipart openai-whisper google-genai
```

3. 設定資料庫環境變數：

```powershell
$env:DB_HOST="192.168.50.7"
$env:DB_PORT="5432"
$env:DB_NAME="ecare_db"
$env:DB_USER="postgres"
$env:DB_PASSWORD="你的密碼"
```

4. 如果要使用 Gemini，也要設定：

```powershell
$env:GOOGLE_API_KEY="你的 API Key"
```

5. 啟動 FastAPI：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

如果啟動成功，通常會看到：

- `PostgreSQL 已連線`
- `Gemini 已初始化`
- `Emotion model 已載入`

## Flutter 前端啟動方式

1. 開新的終端機：

```powershell
cd C:\Users\User\Documents\Ecare\flutter_app
```

2. 安裝 Flutter 套件：

```powershell
flutter pub get
```

3. 啟動桌面版：

```powershell
flutter run -d windows
```

## 目前本機開發流程

建議同時開兩個終端機：

- 終端機 1：跑 FastAPI 後端
- 終端機 2：跑 Flutter 前端

目前 Flutter 預設連線位址是：

```text
http://127.0.0.1:8000
```

設定位置在：

```text
flutter_app/lib/src/config/api_config.dart
```

## 目前功能

- 聊天頁串接 `/chat`
- 語音上傳串接 `/audio`
- 緊急通報與通報紀錄串接 `/reports`
- 個人資料本地儲存
- 位置抓取與地址顯示 fallback

## 注意事項

- 不要把資料庫密碼或 API key commit 到 GitHub
- `.venv/`、`node_modules/`、Flutter build 產物、編輯器本機設定都已經在 `.gitignore`
- 舊的 Web / Capacitor 前端已從 repo 移除

## 常用指令

後端：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_backend.ps1
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
deactivate
```

Flutter：

```powershell
flutter pub get
flutter run -d windows
```

Git：

```powershell
git status
git add -A
git commit -m "你的訊息"
git push
```
