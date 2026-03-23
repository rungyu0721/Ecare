from datasets import load_dataset

print("開始下載測試資料...")

ds = load_dataset("AIDC-AI/CSEMOTIONS", split="train[:5]")

print("成功！")
print(ds)
print("欄位：", ds.column_names)
print("features：", ds.features)