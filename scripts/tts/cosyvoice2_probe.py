#!/usr/bin/env python3
"""Generate a wav file with a local CosyVoice2-0.5B checkout."""

from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from cosyvoice2_runtime import (
    DEFAULT_INSTRUCT_TEXT,
    DEFAULT_MODEL_DIR,
    DEFAULT_OUTPUT,
    DEFAULT_REPO_DIR,
    DEFAULT_TEXT,
    CosyVoice2Runtime,
    get_speakers,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--text-b64", default=None,
                        help="Base64-encoded UTF-8 text (bypasses Windows argv encoding issues)")
    parser.add_argument(
        "--mode",
        choices=("zero-shot", "instruct2"),
        default="zero-shot",
    )
    parser.add_argument("--prompt-text", default=None)
    parser.add_argument("--prompt-wav", type=Path, default=None)
    parser.add_argument("--instruct-text", default=DEFAULT_INSTRUCT_TEXT)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--list-speakers", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.text_b64:
        args.text = base64.b64decode(args.text_b64.encode("ascii")).decode("utf-8")
    runtime = CosyVoice2Runtime(
        repo_dir=args.repo_dir,
        model_dir=args.model_dir,
        prompt_wav=args.prompt_wav,
        prompt_text=args.prompt_text,
        mode=args.mode,
        instruct_text=args.instruct_text,
        speed=args.speed,
    )

    print(f"Loading model: {args.model_dir}")
    runtime.load()
    print(f"Model loaded in {runtime.load_seconds:.2f}s")

    if args.list_speakers:
        speakers = get_speakers(runtime.model)
        if speakers:
            print("Available speakers:")
            for speaker in speakers:
                print(f"  - {speaker}")
        else:
            print("No speaker list was exposed by this CosyVoice build.")
        return

    print(f"Synthesizing mode='{args.mode}'")
    result = runtime.synthesize(args.text, output=args.output)
    print(f"Saved wav: {result['output']}")
    print(f"Synthesis time: {result['synthesis_seconds']:.2f}s")
    if result["tts_text"] != result["text"]:
        print(f"TTS normalized text: {result['tts_text']}")


if __name__ == "__main__":
    main()
