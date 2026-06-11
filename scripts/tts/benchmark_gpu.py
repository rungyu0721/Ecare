"""Quick GPU inference benchmark for CosyVoice2."""
import sys, time, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/Ecare/Ecare/external/CosyVoice')
sys.path.insert(0, 'D:/Ecare/Ecare/external/CosyVoice/third_party/Matcha-TTS')

import torch, soundfile as sf

def _load(uri, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, buffer_size=4096, backend=None):
    stop = None if num_frames == -1 else frame_offset + num_frames
    data, sr = sf.read(uri, start=frame_offset, stop=stop, dtype='float32')
    t = torch.from_numpy(data)
    if t.ndim == 1: t = t.unsqueeze(0)
    elif channels_first: t = t.transpose(0, 1)
    return t.contiguous(), sr

import torchaudio; torchaudio.load = _load

from cosyvoice.cli.cosyvoice import AutoModel

print('Loading model...')
t0 = time.perf_counter()
model = AutoModel(model_dir='D:/Ecare/Ecare/external/models/CosyVoice2-0.5B')
load_time = time.perf_counter() - t0
used_gb = round((torch.cuda.mem_get_info()[1] - torch.cuda.mem_get_info()[0]) / 1e9, 2)
print(f'  loaded in {load_time:.1f}s | GPU VRAM used: {used_gb} GB')

p = next(model.model.llm.parameters())
print(f'  LLM device: {p.device}')

PROMPT_WAV  = 'D:/Ecare/Ecare/scripts/data/tts_prompt_ecare.wav'
PROMPT_TEXT = '您好，我是紧急助手。请保持冷静，我会一步一步协助您确认现场状况。'

tests = [
    '我在，先别慌。先看胸口有没有起伏，有没有正常呼吸。',
    '我在，先别慌。请旁边的人找自动体外心脏电击器，你先确认他有没有正常呼吸。',
]

for text in tests:
    print(f'\nSynth: "{text}"')
    t1 = time.perf_counter()
    for item in model.inference_zero_shot(text, PROMPT_TEXT, PROMPT_WAV, stream=False, speed=1.0):
        if 'tts_speech' in item:
            speech_len = item['tts_speech'].shape[1] / model.sample_rate
            elapsed = time.perf_counter() - t1
            rtf = elapsed / speech_len
            print(f'  audio={speech_len:.2f}s  synthesis={elapsed:.2f}s  RTF={rtf:.3f}  {"✓ real-time" if rtf < 1 else "✗ slower than real-time"}')
            break

print('\nDone.')
