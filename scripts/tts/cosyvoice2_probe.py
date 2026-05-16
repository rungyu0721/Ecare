#!/usr/bin/env python3
"""Generate a wav file with a local CosyVoice2-0.5B checkout.

This is an isolated experiment. It does not start the E-CARE backend and does
not change the chat flow.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_REPO_DIR = Path("external/CosyVoice")
DEFAULT_MODEL_DIR = Path("external/models/CosyVoice2-0.5B")
DEFAULT_OUTPUT = Path("scripts/output/cosyvoice2_probe.wav")
DEFAULT_TEXT = "系統已列為高風險通報，請確認患者是否有正常呼吸。"
DEFAULT_PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
DEFAULT_PROMPT_WAV = Path("external/CosyVoice/asset/zero_shot_prompt.wav")
DEFAULT_INSTRUCT_TEXT = "You are a helpful assistant. 请用清楚、冷静、稳定的语气说这句话。<|endofprompt|>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=DEFAULT_REPO_DIR,
        help=f"CosyVoice git checkout. Default: {DEFAULT_REPO_DIR}",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help=f"Downloaded CosyVoice2 model dir. Default: {DEFAULT_MODEL_DIR}",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Text to synthesize.",
    )
    parser.add_argument(
        "--mode",
        choices=("zero-shot", "instruct2", "sft"),
        default="zero-shot",
        help="Synthesis mode. Default: zero-shot",
    )
    parser.add_argument(
        "--speaker",
        default=None,
        help="SFT speaker name. Only used with --mode sft.",
    )
    parser.add_argument(
        "--prompt-text",
        default=DEFAULT_PROMPT_TEXT,
        help=f"Prompt transcript for zero-shot modes. Default: {DEFAULT_PROMPT_TEXT}",
    )
    parser.add_argument(
        "--prompt-wav",
        type=Path,
        default=DEFAULT_PROMPT_WAV,
        help=f"Prompt wav path for zero-shot modes. Default: {DEFAULT_PROMPT_WAV}",
    )
    parser.add_argument(
        "--instruct-text",
        default=DEFAULT_INSTRUCT_TEXT,
        help="Instruction text for --mode instruct2.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Enable streaming inference if supported by the model.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed. Default: 1.0",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output wav path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--list-speakers",
        action="store_true",
        help="Print available SFT speaker names when the model exposes them.",
    )
    return parser.parse_args()


def require_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise SystemExit(f"{label} not found: {resolved}")
    return resolved


def configure_import_path(repo_dir: Path) -> None:
    sys.path.insert(0, str(repo_dir))
    matcha_tts = repo_dir / "third_party" / "Matcha-TTS"
    if matcha_tts.exists():
        sys.path.insert(0, str(matcha_tts))


def get_speakers(model: Any) -> list[str]:
    for attr in ("spk2info", "spk2id", "frontend"):
        value = getattr(model, attr, None)
        if isinstance(value, dict):
            return sorted(str(key) for key in value.keys())
        nested = getattr(value, "spk2info", None)
        if isinstance(nested, dict):
            return sorted(str(key) for key in nested.keys())
    return []


def patch_torchaudio_load() -> None:
    """Avoid torchcodec-only torchaudio.load behavior in recent torchaudio."""
    try:
        import soundfile as sf
        import torch
        import torchaudio
    except ImportError as exc:
        raise SystemExit(
            "Missing audio dependency. Run the TTS requirements install first."
        ) from exc

    def load_with_soundfile(
        uri: str,
        frame_offset: int = 0,
        num_frames: int = -1,
        normalize: bool = True,
        channels_first: bool = True,
        format: str | None = None,
        buffer_size: int = 4096,
        backend: str | None = None,
    ) -> tuple[Any, int]:
        del normalize, format, buffer_size, backend
        stop = None if num_frames == -1 else frame_offset + num_frames
        data, sample_rate = sf.read(uri, start=frame_offset, stop=stop, dtype="float32")
        tensor = torch.from_numpy(data)
        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)
        elif channels_first:
            tensor = tensor.transpose(0, 1)
        return tensor.contiguous(), sample_rate

    torchaudio.load = load_with_soundfile


def save_wav(output: Path, speech: Any, sample_rate: int) -> None:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: soundfile. "
            "Install CosyVoice requirements first, then retry."
        ) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    audio = speech.detach().cpu()
    if audio.ndim == 2:
        audio = audio.transpose(0, 1)
    sf.write(str(output), audio.numpy(), sample_rate)


def resolve_prompt_wav(prompt_wav: Path) -> Path:
    prompt_path = prompt_wav
    if not prompt_path.is_absolute():
        prompt_path = (Path.cwd() / prompt_path).resolve()
    return require_path(prompt_path, "Prompt wav")


def main() -> None:
    args = parse_args()
    repo_dir = require_path(args.repo_dir, "CosyVoice repo")
    model_dir = require_path(args.model_dir, "CosyVoice2 model directory")
    configure_import_path(repo_dir)
    patch_torchaudio_load()

    try:
        from cosyvoice.cli.cosyvoice import AutoModel
    except ImportError as exc:
        raise SystemExit(
            "Could not import CosyVoice. Make sure you cloned the repo, "
            "initialized submodules, and installed its requirements."
        ) from exc

    print(f"Loading model: {model_dir}")
    load_started = time.perf_counter()
    cosyvoice = AutoModel(model_dir=str(model_dir))
    load_seconds = time.perf_counter() - load_started
    print(f"Model loaded in {load_seconds:.2f}s")

    speakers = get_speakers(cosyvoice)
    if args.list_speakers:
        if speakers:
            print("Available speakers:")
            for speaker in speakers:
                print(f"  - {speaker}")
        else:
            print("No speaker list was exposed by this CosyVoice build.")
        return

    if args.mode == "sft":
        if not speakers:
            raise SystemExit(
                "This model has no SFT speaker list. Use the default "
                "--mode zero-shot, or provide a model with spk2info.pt."
            )
        if not args.speaker:
            raise SystemExit("--mode sft requires --speaker.")
        if args.speaker not in speakers:
            print(f"Warning: speaker '{args.speaker}' was not found.")
            print("Available speakers:")
            for speaker in speakers[:20]:
                print(f"  - {speaker}")

    print(f"Synthesizing mode='{args.mode}'")
    synth_started = time.perf_counter()
    first_output = None

    if args.mode == "sft":
        iterator = cosyvoice.inference_sft(
            args.text,
            args.speaker,
            stream=args.stream,
            speed=args.speed,
        )
    else:
        prompt_wav = str(resolve_prompt_wav(args.prompt_wav))
        if args.mode == "instruct2":
            iterator = cosyvoice.inference_instruct2(
                args.text,
                args.instruct_text,
                prompt_wav,
                stream=args.stream,
                speed=args.speed,
            )
        else:
            iterator = cosyvoice.inference_zero_shot(
                args.text,
                args.prompt_text,
                prompt_wav,
                stream=args.stream,
                speed=args.speed,
            )

    for item in iterator:
        first_output = item
        break

    if not first_output or "tts_speech" not in first_output:
        raise SystemExit("CosyVoice did not return tts_speech.")

    save_wav(args.output, first_output["tts_speech"], cosyvoice.sample_rate)
    synth_seconds = time.perf_counter() - synth_started
    print(f"Saved wav: {args.output.resolve()}")
    print(f"Synthesis time: {synth_seconds:.2f}s")


if __name__ == "__main__":
    main()
