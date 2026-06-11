# CosyVoice2-0.5B TTS Experiment

這份文件記錄 E-CARE 本地語音播報實驗。目標是把後端產生的 `voice_prompt` 轉成語音，之後可以由 Flutter 播放。

目前結論：

- CosyVoice2 可以在本機產生中文語音。
- 繁體文字直接送進模型時，發音較容易糊或不穩。
- 實作上保留 UI 繁體，但在 TTS 前自動做繁轉簡，語音品質明顯穩定很多。
- TTS 環境建議和主專案 `.venv` 分開，避免 PyTorch / torchaudio 版本影響後端。

## 1. Directory Layout

```text
Ecare/
├── external/
│   ├── CosyVoice/
│   └── models/
│       └── CosyVoice2-0.5B/
├── scripts/
│   └── tts/
│       ├── download_cosyvoice2.py
│       ├── cosyvoice2_probe.py
│       ├── cosyvoice2_runtime.py
│       └── serve_tts.py
└── requirements-tts.txt
```

`external/`、`.venv-tts/`、wav/mp3 輸出都不進 git。

## 2. Clone CosyVoice

```powershell
New-Item -ItemType Directory -Force external
git clone https://github.com/FunAudioLLM/CosyVoice.git external/CosyVoice
cd external/CosyVoice
git submodule update --init --recursive
cd ..\..
```

## 3. 建立 TTS 環境

```powershell
py -3.11 -m venv .venv-tts
.\.venv-tts\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-tts\Scripts\python.exe -m pip install -r requirements-tts.txt
```

CosyVoice 的 requirements 會拉到 `openai-whisper`，在 Windows 上可能遇到 build isolation 缺 `pkg_resources`。可用這個方式處理：

```powershell
.\.venv-tts\Scripts\python.exe -m pip install --no-build-isolation openai-whisper
Get-Content external\CosyVoice\requirements.txt |
  Where-Object { $_ -notmatch 'whisper' } |
  Set-Content external\CosyVoice\requirements-no-whisper.txt
.\.venv-tts\Scripts\python.exe -m pip install -r external\CosyVoice\requirements-no-whisper.txt
```

RTX 50 系列如果遇到 `no kernel image is available for execution on the device`，代表 PyTorch wheel 不支援目前 GPU 架構。需要改裝支援 Blackwell 的 PyTorch，或先用 CPU 測試。

## 4. Download Model

```powershell
.\.venv-tts\Scripts\python.exe scripts\tts\download_cosyvoice2.py
```

模型會下載到：

```text
external/models/CosyVoice2-0.5B
```

## 5. 準備 Zero-Shot Prompt

建議放一段清楚、穩定、13 秒左右的中文語音：

```text
scripts/data/tts_prompt_ecare.mp3
```

轉成 CosyVoice 比較穩的 wav 格式：

```powershell
ffmpeg -i scripts\data\tts_prompt_ecare.mp3 -ar 16000 -ac 1 scripts\data\tts_prompt_ecare.wav
```

建議 prompt 文字和錄音內容一致，並使用簡體：

```text
您好，我是紧急助手。请保持冷静，我会一步一步协助您确认现场状况。请先注意自身安全，并依照画面提示回报最新变化。
```

## 6. Probe

```powershell
.\.venv-tts\Scripts\python.exe scripts\tts\cosyvoice2_probe.py `
  --prompt-wav scripts\data\tts_prompt_ecare.wav `
  --prompt-text "您好，我是紧急助手。请保持冷静，我会一步一步协助您确认现场状况。请先注意自身安全，并依照画面提示回报最新变化。" `
  --text "系統已列為高風險通報，請確認患者是否有正常呼吸。"
```

輸出：

```text
scripts/output/cosyvoice2_probe.wav
```

播放：

```powershell
Start-Process .\scripts\output\cosyvoice2_probe.wav
```

## 7. Local TTS Service

`serve_tts.py` 會讓 CosyVoice2 常駐載入，避免每次播報都重新載模型。

建議平常直接用根目錄的啟動腳本：

```powershell
.\start_tts.ps1
```

預設使用 `subprocess` backend。它會慢一點，但行為最接近已驗證成功的 `cosyvoice2_probe.py`。

若之後要測常駐模型低延遲模式，可以另外跑：

```powershell
.\start_tts.ps1 -Backend runtime
```

如果要手動指定參數，也可以直接執行 service：

```powershell
.\.venv-tts\Scripts\python.exe scripts\tts\serve_tts.py `
  --prompt-wav scripts\data\tts_prompt_ecare.wav `
  --prompt-text "您好，我是紧急助手。请保持冷静，我会一步一步协助您确认现场状况。请先注意自身安全，并依照画面提示回报最新变化。" `
  --backend subprocess
```

預設服務：

```text
http://127.0.0.1:8011
```

健康檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8011/health
```

產生一段語音：

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8011/tts `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"text":"系統已列為高風險通報，請確認患者是否有正常呼吸。"}' `
  -OutFile scripts\output\tts_service_test.wav
```

播放：

```powershell
Start-Process .\scripts\output\tts_service_test.wav
```

可調語速：

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8011/tts `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"text":"請保持冷靜，先確認患者是否有正常呼吸。","speed":0.9}' `
  -OutFile scripts\output\tts_service_test.wav
```

## 8. Next

- 後端新增 TTS client，呼叫 `http://127.0.0.1:8011/tts`。
- Flutter 改成播放後端回傳或代理的 wav，而不是只用 Windows 系統語音。
- 保留 Windows 系統語音作為 fallback。
- 針對高風險通報、CPR、AED、燒燙傷等常用語句做固定 voice prompt 測試。
