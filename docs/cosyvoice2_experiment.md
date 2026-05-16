# CosyVoice2-0.5B TTS Experiment

這份文件是 E-CARE 的本地 TTS 實驗流程。目標是先確認
`CosyVoice2-0.5B` 能不能把 `voice_prompt` 轉成繁中語音檔，再決定是否接進
FastAPI `/tts`。

目前這些步驟不會改動正式後端，也不會影響 Flutter 聊天流程。

## 1. 建議目錄

```text
Ecare/
├── external/
│   ├── CosyVoice/
│   └── models/
│       └── CosyVoice2-0.5B/
├── scripts/
│   └── tts/
│       ├── download_cosyvoice2.py
│       └── cosyvoice2_probe.py
└── requirements-tts.txt
```

`external/` 建議保持 untracked，只放下載或 clone 下來的第三方內容。

## 2. Clone CosyVoice

```powershell
New-Item -ItemType Directory -Force external
git clone https://github.com/FunAudioLLM/CosyVoice.git external/CosyVoice
cd external/CosyVoice
git submodule update --init --recursive
cd ..\..
```

## 3. 安裝實驗依賴

先使用你目前專案的 `.venv`，或另外開一個 TTS 專用 venv。CosyVoice 會需要
PyTorch / torchaudio，CUDA 版本依你的電腦或 4080 環境調整。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-tts.txt
.\.venv\Scripts\python.exe -m pip install -r external\CosyVoice\requirements.txt
```

如果 PyTorch / torchaudio 安裝失敗，請改用 PyTorch 官方指令安裝符合你 CUDA
版本的 wheel，再重跑 CosyVoice requirements。

## 4. 下載模型

```powershell
.\.venv\Scripts\python.exe scripts\tts\download_cosyvoice2.py
```

預設會下載到：

```text
external/models/CosyVoice2-0.5B
```

## 5. 測試產生 wav

```powershell
.\.venv\Scripts\python.exe scripts\tts\cosyvoice2_probe.py
```

預設使用 CosyVoice2 官方範例的 zero-shot 方式，會用
`external/CosyVoice/asset/zero_shot_prompt.wav` 當參考音色。

預設測試句：

```text
系統已列為高風險通報，請確認患者是否有正常呼吸。
```

輸出檔：

```text
scripts/output/cosyvoice2_probe.wav
```

自訂文字：

```powershell
.\.venv\Scripts\python.exe scripts\tts\cosyvoice2_probe.py --text "請先確認胸口有沒有起伏，並請旁邊的人協助找 AED。"
```

列出可用說話人：

```powershell
.\.venv\Scripts\python.exe scripts\tts\cosyvoice2_probe.py --list-speakers
```

如果模型沒有 `spk2info.pt`，`--list-speakers` 可能會顯示沒有可用 speaker。
這是 CosyVoice2 zero-shot 模型常見狀況，不代表模型壞掉。請直接用預設
`zero-shot` mode 測試。

指定說話人：

```powershell
.\.venv\Scripts\python.exe scripts\tts\cosyvoice2_probe.py --mode sft --speaker "中文女"
```

使用 instruct2 控制語氣：

```powershell
.\.venv\Scripts\python.exe scripts\tts\cosyvoice2_probe.py --mode instruct2 --text "請確認胸口有沒有起伏，並請旁邊的人協助找 AED。"
```

## 6. 評估標準

- 中文是否自然、清楚。
- 是否能穩定讀繁體中文。
- 第一次載入模型花多久。
- 單句 `voice_prompt` 合成花多久。
- CPU / GPU 記憶體是否可接受。
- Windows 本機與遠端 4080 哪個環境比較適合部署。

## 7. 成功後下一步

如果 probe 成功，下一階段再新增：

```text
FastAPI /tts endpoint
Flutter -> /tts -> wav -> audioplayers
```

正式接入後，Flutter 仍然只呼叫 E-CARE 後端，不直接依賴 CosyVoice。
