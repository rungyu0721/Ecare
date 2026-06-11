"""Debug TTS text normalization step-by-step."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, 'external/CosyVoice')
sys.path.insert(0, 'external/CosyVoice/third_party/Matcha-TTS')

from cosyvoice2_runtime import configure_import_path, patch_torchaudio_load, convert_for_tts
from pathlib import Path

configure_import_path(Path('external/CosyVoice'))
patch_torchaudio_load()

# Step 1: OpenCC conversion
original = "系統已列為高風險通報，請確認患者是否有正常呼吸。"
converted = convert_for_tts(original)
print(f"[1] Original : {original}")
print(f"[1] Converted: {converted}")

# Step 2: Load model
from cosyvoice.cli.cosyvoice import AutoModel
print("[2] Loading model...")
model = AutoModel(model_dir='external/models/CosyVoice2-0.5B')
print("[2] Model loaded")

# Step 3: text_normalize
print("[3] Calling text_normalize(tts_text, split=True)...")
result = model.frontend.text_normalize(converted, split=True)
print(f"[3] text_normalize returned {len(result)} items: {result}")

prompt_text_orig = "您好，我是紧急助手。请保持冷静，我会一步一步协助您确认现场状况。"
prompt_text_norm = model.frontend.text_normalize(prompt_text_orig, split=False)
print(f"[4] prompt_text_normalize (split=False) returned: repr={repr(prompt_text_norm[:40])}")

# Step 4: Try inference manually (first step only)
if result:
    print("[5] text_normalize OK, trying frontend_zero_shot...")
    try:
        import os
        prompt_wav = str(Path('external/CosyVoice/asset/zero_shot_prompt.wav').resolve())
        model_input = model.frontend.frontend_zero_shot(
            result[0], prompt_text_norm, prompt_wav, model.sample_rate, ''
        )
        print(f"[5] frontend_zero_shot OK, keys: {list(model_input.keys())}")
    except Exception as e:
        print(f"[5] frontend_zero_shot FAILED: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # Step 5: Try model.tts()
    print("[6] Calling model.tts()...")
    try:
        count = 0
        for output in model.model.tts(**model_input, stream=False, speed=1.0):
            count += 1
            keys = list(output.keys()) if isinstance(output, dict) else type(output)
            print(f"[6] Got output #{count}, keys={keys}")
            if count >= 2:
                break
        print(f"[6] model.tts() total outputs: {count}")
    except Exception as e:
        print(f"[6] model.tts() FAILED: {e}")
        import traceback; traceback.print_exc()
else:
    print("[5] SKIPPED - text_normalize returned empty!")
