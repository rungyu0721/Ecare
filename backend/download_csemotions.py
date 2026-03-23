from datasets import load_dataset, Audio
import os
import shutil

print("開始載入 CSEMOTIONS...")

# 不解碼音訊，直接拿原始 bytes/path
ds = load_dataset("AIDC-AI/CSEMOTIONS", split="train")
ds = ds.cast_column("audio", Audio(decode=False))

out_dir = "datasets/csemotions"
os.makedirs(out_dir, exist_ok=True)

print("開始匯出音檔...")

for i, item in enumerate(ds):
    emotion = str(item["emotion"]).lower()
    text = str(item["text"])
    speaker = str(item["speaker"])

    emotion_dir = os.path.join(out_dir, emotion)
    os.makedirs(emotion_dir, exist_ok=True)

    base_name = f"{speaker}_{i}"
    wav_path = os.path.join(emotion_dir, f"{base_name}.wav")
    txt_path = os.path.join(emotion_dir, f"{base_name}.txt")

    audio_info = item["audio"]

    # 情況 1：有原始 bytes
    if audio_info.get("bytes") is not None:
        with open(wav_path, "wb") as f:
            f.write(audio_info["bytes"])

    # 情況 2：只有 path，就直接複製
    elif audio_info.get("path") is not None:
        shutil.copyfile(audio_info["path"], wav_path)

    else:
        print(f"跳過第 {i} 筆：沒有 bytes 也沒有 path")
        continue

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    if i % 200 == 0:
        print(f"已匯出 {i} 筆...")

print("全部完成！")