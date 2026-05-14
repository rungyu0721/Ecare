# Local Ollama Setup

This backend now supports `LLM_PROVIDER=ollama` directly and uses Ollama's OpenAI-compatible API.

## 1. Install and pull the model

Use Ollama to download Qwen2.5 locally and build the E-CARE fine-tuned model:

```powershell
ollama create ecare-v4:latest -f Modelfile.v4
```

For current app testing, use `ecare-v4:latest`. Older models such as `ecare:latest`, `ecare-local-q4:latest`, or `ecare-qwen2.5:latest` are legacy test models.

If the Ollama service is not already running on your machine, start it:

```powershell
ollama serve
```

## 2. Environment variables

Use these values in PowerShell before starting the backend:

```powershell
$env:LLM_PROVIDER="ollama"
$env:LLM_MODEL="ecare-v4:latest"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

Optional values:

```powershell
$env:OLLAMA_CHAT_PATH="/v1/chat/completions"
$env:OLLAMA_API_KEY=""
$env:OLLAMA_MAX_TOKENS="384"
$env:COMPACT_OLLAMA_MAX_TOKENS="192"
$env:CHAT_CONTEXT_TURNS="3"
$env:FOLLOWUP_CONTEXT_TURNS="2"
$env:ENABLE_LLM_GRAPH_PLANNER="0"
$env:ENABLE_LLM_SEMANTIC_UNDERSTANDING="1"
$env:WARMUP_LLM_ON_STARTUP="1"
```

## 3. Start backend

```powershell
cd D:\Ecare\Ecare
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_backend.ps1
```

Or start it manually:

```powershell
cd D:\Ecare\Ecare
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
$env:LLM_PROVIDER="ollama"
$env:LLM_MODEL="ecare-v4:latest"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Notes

- If the base URL already ends with `/v1`, the backend will call `/chat/completions`.
- If it does not end with `/v1`, the backend will call `/v1/chat/completions`.
- `OLLAMA_CHAT_PATH` lets you override the chat route when needed.
- `OLLAMA_MAX_TOKENS` and `COMPACT_OLLAMA_MAX_TOKENS` help control latency.
- Legacy `GEMMA_*` variables are still accepted for backward compatibility.
- If your goal is to add your own domain knowledge, switch to Ollama first. After that, prefer prompt tuning, retrieval/RAG, or a custom `Modelfile` before attempting full fine-tuning.
