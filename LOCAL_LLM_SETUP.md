# Local Gemma Setup

This backend can now use a local OpenAI-compatible endpoint instead of Gemini.

## Environment variables

Use these values in PowerShell before starting the backend:

```powershell
$env:LLM_PROVIDER="gemma"
$env:LLM_MODEL="gemma-3-4b-it"
$env:GEMMA_BASE_URL="http://127.0.0.1:1234"
```

Optional values:

```powershell
$env:GEMMA_CHAT_PATH="/v1/chat/completions"
$env:GEMMA_API_KEY=""
```

## Notes

- If your local server base URL already ends with `/v1`, the backend will call `/chat/completions`.
- If it does not end with `/v1`, the backend will call `/v1/chat/completions`.
- `GEMMA_CHAT_PATH` lets you override that path when your local tool uses a custom route.

## Start backend

```powershell
cd D:\Ecare\Ecare
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
$env:LLM_PROVIDER="gemma"
$env:LLM_MODEL="gemma-3-4b-it"
$env:GEMMA_BASE_URL="http://127.0.0.1:1234"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Typical local tools

- LM Studio often uses `http://127.0.0.1:1234`
- Some OpenAI-compatible servers use `http://127.0.0.1:8000`
- Ollama is not OpenAI-compatible by default, so it usually needs a bridge/proxy or a different provider implementation
