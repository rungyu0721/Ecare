#!/usr/bin/env python3
"""Download CosyVoice2-0.5B into a local experiment directory."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_MODEL_ID = "FunAudioLLM/CosyVoice2-0.5B"
DEFAULT_OUTPUT_DIR = Path("external/models/CosyVoice2-0.5B")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help=f"Hugging Face model id. Default: {DEFAULT_MODEL_ID}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Local model directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub. "
            "Run: pip install -r requirements-tts.txt"
        ) from exc

    output_dir = args.output_dir
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    path = snapshot_download(
        repo_id=args.model_id,
        local_dir=str(output_dir),
        local_dir_use_symlinks=False,
    )
    print(f"Downloaded {args.model_id} -> {path}")


if __name__ == "__main__":
    main()
