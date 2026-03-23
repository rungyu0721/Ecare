import os
import numpy as np
import librosa
import joblib

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

DATASET_DIR = "datasets/csemotions"

# 你可以先挑幾個重要情緒
KEEP_LABELS = {"neutral", "sad", "angry", "fearful", "happy"}

def extract_features(file_path):
    y, sr = librosa.load(file_path, sr=16000, mono=True)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_delta = librosa.feature.delta(mfcc)
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=40)
    zcr = librosa.feature.zero_crossing_rate(y)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)

    feats = np.concatenate([
        np.mean(mfcc, axis=1),
        np.std(mfcc, axis=1),
        np.mean(mfcc_delta, axis=1),
        np.std(mfcc_delta, axis=1),
        np.mean(mel, axis=1),
        np.std(mel, axis=1),
        [np.mean(zcr), np.std(zcr)],
        [np.mean(centroid), np.std(centroid)],
        [np.mean(rms), np.std(rms)],
    ])

    return feats.astype(np.float32)

def build_dataset():
    X, y = [], []

    for label in os.listdir(DATASET_DIR):
        label_path = os.path.join(DATASET_DIR, label)

        if not os.path.isdir(label_path):
            continue

        if label not in KEEP_LABELS:
            continue

        for fn in os.listdir(label_path):
            if not fn.endswith(".wav"):
                continue

            path = os.path.join(label_path, fn)

            try:
                feats = extract_features(path)
                X.append(feats)
                y.append(label)
            except Exception as e:
                print("跳過:", path, e)

    return np.array(X), np.array(y)

def main():
    print("讀取資料中...")
    X, y = build_dataset()

    print("資料量:", len(X))
    print("類別分布:")
    for label in set(y):
        print(label, np.sum(y == label))

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(n_estimators=200))
    ])

    print("開始訓練...")
    model.fit(X_train, y_train)

    pred = model.predict(X_test)

    print("\n結果：")
    print(classification_report(y_test, pred))

    joblib.dump(model, "emotion_model.pkl")
    print("\n✅ 模型已存成 emotion_model.pkl")

if __name__ == "__main__":
    main()