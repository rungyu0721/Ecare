"""Shared CosyVoice2 runtime helpers for local TTS experiments."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_REPO_DIR = Path("external/CosyVoice")
DEFAULT_MODEL_DIR = Path("external/models/CosyVoice2-0.5B")
DEFAULT_OUTPUT = Path("scripts/output/cosyvoice2_probe.wav")
DEFAULT_TEXT = "系統已列為高風險通報，請確認患者是否有正常呼吸。"
DEFAULT_PROMPT_TEXT = "您好，我是紧急助手。请保持冷静，我会一步一步协助您确认现场状况。请先注意自身安全，并依照画面提示回报最新变化。"
DEFAULT_PROMPT_WAV = Path("scripts/data/tts_prompt_ecare.wav")
DEFAULT_FALLBACK_PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
DEFAULT_FALLBACK_PROMPT_WAV = Path("external/CosyVoice/asset/zero_shot_prompt.wav")
DEFAULT_INSTRUCT_TEXT = "请用温柔、稳定、充满关怀的语气说这句话，像在陪伴一个非常慌张的人，语速放慢，每个停顿都要自然，让对方感受到你在陪着他。<|endofprompt|>"


def require_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def configure_import_path(repo_dir: Path) -> Path:
    repo_dir = require_path(repo_dir, "CosyVoice repo")
    repo_text = str(repo_dir)
    if repo_text not in sys.path:
        sys.path.insert(0, repo_text)

    matcha_tts = repo_dir / "third_party" / "Matcha-TTS"
    if matcha_tts.exists():
        matcha_text = str(matcha_tts)
        if matcha_text not in sys.path:
            sys.path.insert(0, matcha_text)
    return repo_dir


def patch_torchaudio_load() -> None:
    """Avoid torchcodec-only torchaudio.load behavior in recent torchaudio."""
    import soundfile as sf
    import torch
    import torchaudio

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
    import soundfile as sf

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


def get_speakers(model: Any) -> list[str]:
    for attr in ("spk2info", "spk2id", "frontend"):
        value = getattr(model, attr, None)
        if isinstance(value, dict):
            return sorted(str(key) for key in value.keys())
        nested = getattr(value, "spk2info", None)
        if isinstance(nested, dict):
            return sorted(str(key) for key in nested.keys())
    return []


def default_prompt() -> tuple[Path, str]:
    if DEFAULT_PROMPT_WAV.exists():
        return DEFAULT_PROMPT_WAV, DEFAULT_PROMPT_TEXT
    return DEFAULT_FALLBACK_PROMPT_WAV, DEFAULT_FALLBACK_PROMPT_TEXT


def convert_for_tts(text: str) -> str:
    """Convert Traditional Chinese prompts to Simplified for CosyVoice stability."""
    try:
        from opencc import OpenCC
    except ImportError:
        return text
    return OpenCC("t2s").convert(text)


class CosyVoice2Runtime:
    def __init__(
        self,
        repo_dir: Path = DEFAULT_REPO_DIR,
        model_dir: Path = DEFAULT_MODEL_DIR,
        prompt_wav: Path | None = None,
        prompt_text: str | None = None,
        mode: str = "zero-shot",
        instruct_text: str = DEFAULT_INSTRUCT_TEXT,
        speed: float = 1.0,
    ) -> None:
        self.repo_dir = repo_dir
        self.model_dir = model_dir
        self.prompt_wav, default_text = default_prompt()
        if prompt_wav is not None:
            self.prompt_wav = prompt_wav
        self.prompt_text = prompt_text or default_text
        self.mode = mode
        self.instruct_text = instruct_text
        self.speed = speed
        self.model: Any | None = None
        self.sample_rate: int | None = None
        self.load_seconds: float | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        configure_import_path(self.repo_dir)
        patch_torchaudio_load()
        model_dir = require_path(self.model_dir, "CosyVoice2 model directory")

        from cosyvoice.cli.cosyvoice import AutoModel

        started = time.perf_counter()
        self.model = AutoModel(model_dir=str(model_dir))
        self.sample_rate = int(self.model.sample_rate)
        self.load_seconds = time.perf_counter() - started

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def synthesize(
        self,
        text: str,
        *,
        output: Path,
        mode: str | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        if self.model is None or self.sample_rate is None:
            raise RuntimeError("CosyVoice2 model is not loaded.")

        tts_text = convert_for_tts(text.strip())
        if not tts_text:
            raise ValueError("TTS text is empty.")

        selected_mode = mode or self.mode
        selected_speed = speed if speed is not None else self.speed
        prompt_wav = str(resolve_prompt_wav(self.prompt_wav))
        started = time.perf_counter()

        with self._lock:
            if selected_mode == "instruct2":
                iterator = self.model.inference_instruct2(
                    tts_text,
                    self.instruct_text,
                    prompt_wav,
                    stream=False,
                    speed=selected_speed,
                )
            elif selected_mode == "zero-shot":
                iterator = self.model.inference_zero_shot(
                    tts_text,
                    convert_for_tts(self.prompt_text),
                    prompt_wav,
                    stream=False,
                    speed=selected_speed,
                )
            else:
                raise ValueError(f"Unsupported mode: {selected_mode}")

            first_output = None
            observed_keys: list[str] = []
            for item in iterator:
                if isinstance(item, dict):
                    observed_keys.extend(str(key) for key in item.keys())
                    if "tts_speech" in item:
                        first_output = item
                        break

            if not first_output or "tts_speech" not in first_output:
                keys = ", ".join(sorted(set(observed_keys))) or "none"
                raise RuntimeError(f"CosyVoice did not return tts_speech. observed keys: {keys}")

            save_wav(output, first_output["tts_speech"], self.sample_rate)

        synth_seconds = time.perf_counter() - started
        return {
            "output": str(output.resolve()),
            "mode": selected_mode,
            "speed": selected_speed,
            "sample_rate": self.sample_rate,
            "load_seconds": self.load_seconds,
            "synthesis_seconds": synth_seconds,
            "text": text,
            "tts_text": tts_text,
        }