#!/usr/bin/env python3
"""Run a local CosyVoice2 TTS service for E-CARE voice prompts."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

from cosyvoice2_runtime import (
    DEFAULT_INSTRUCT_TEXT,
    DEFAULT_MODEL_DIR,
    DEFAULT_REPO_DIR,
    CosyVoice2Runtime,
)


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)
    mode: str = Field("instruct2", pattern="^(zero-shot|instruct2)$")
    speed: float | None = Field(default=None, ge=0.5, le=1.5)


def build_app(
    runtime: CosyVoice2Runtime,
    output_dir: Path,
    backend: str,
) -> FastAPI:
    app = FastAPI(title="E-CARE Local TTS", version="0.1.0")

    @app.on_event("startup")
    def load_model() -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        if backend == "runtime":
            runtime.load()

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": runtime.is_loaded,
            "backend": backend,
            "model": str(runtime.model_dir),
            "mode": runtime.mode,
            "load_seconds": runtime.load_seconds,
            "prompt_wav": str(runtime.prompt_wav),
        }

    @app.post("/tts")
    async def synthesize(request: TtsRequest) -> FileResponse:
        output = output_dir / f"tts_{uuid4().hex}.wav"
        try:
            if backend == "runtime":
                result = runtime.synthesize(
                    request.text,
                    output=output,
                    mode=request.mode,
                    speed=request.speed,
                )
            else:
                result = synthesize_with_probe_subprocess(
                    runtime=runtime,
                    text=request.text,
                    output=output,
                    mode=request.mode,
                    speed=request.speed,
                )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        headers = {
            "X-ECARE-TTS-Mode": str(result["mode"]),
            "X-ECARE-TTS-Backend": str(result.get("backend", "runtime")),
            "X-ECARE-TTS-Speed": str(result["speed"]),
            "X-ECARE-TTS-Seconds": f"{result['synthesis_seconds']:.3f}",
            "X-ECARE-TTS-Sample-Rate": str(result["sample_rate"]),
        }
        return FileResponse(
            path=output,
            media_type="audio/wav",
            filename="ecare_voice_prompt.wav",
            headers=headers,
        )

    return app


def synthesize_with_probe_subprocess(
    *,
    runtime: CosyVoice2Runtime,
    text: str,
    output: Path,
    mode: str,
    speed: float | None,
) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cmd = [
        sys.executable, "-X", "utf8",
        str(Path(__file__).with_name("cosyvoice2_probe.py")),
        "--repo-dir",
        str(runtime.repo_dir),
        "--model-dir",
        str(runtime.model_dir),
        "--mode",
        mode,
        "--text-b64",
        text_b64,
        "--output",
        str(output),
    ]
    selected_speed = speed if speed is not None else runtime.speed
    cmd.extend(["--speed", str(selected_speed)])
    printable_cmd = subprocess.list2cmdline(cmd)

    started = time.perf_counter()
    completed = subprocess.run(
        cmd,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()[-1600:]
        stdout = completed.stdout.strip()[-1600:]
        detail = {
            "exit_code": completed.returncode,
            "command": printable_cmd,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
        }
        raise RuntimeError(json.dumps(detail, ensure_ascii=False))
    if not output.exists():
        detail = {
            "exit_code": completed.returncode,
            "command": printable_cmd,
            "stdout_tail": completed.stdout.strip()[-1600:],
            "stderr_tail": completed.stderr.strip()[-1600:],
            "missing_output": str(output),
        }
        raise RuntimeError(json.dumps(detail, ensure_ascii=False))

    elapsed = time.perf_counter() - started
    return {
        "output": str(output.resolve()),
        "mode": mode,
        "backend": "probe-subprocess",
        "speed": selected_speed,
        "sample_rate": runtime.sample_rate or 0,
        "synthesis_seconds": elapsed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--prompt-wav", type=Path, default=None)
    parser.add_argument("--prompt-text", default=None)
    parser.add_argument(
        "--mode",
        choices=("zero-shot", "instruct2"),
        default="instruct2",
    )
    parser.add_argument("--instruct-text", default=DEFAULT_INSTRUCT_TEXT)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--backend",
        choices=("subprocess", "runtime"),
        default="runtime",
        help="Use runtime to keep model in memory (lower latency); subprocess for isolation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "ecare_tts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = CosyVoice2Runtime(
        repo_dir=args.repo_dir,
        model_dir=args.model_dir,
        prompt_wav=args.prompt_wav,
        prompt_text=args.prompt_text,
        mode=args.mode,
        instruct_text=args.instruct_text,
        speed=args.speed,
    )
    app = build_app(runtime, args.output_dir, args.backend)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()