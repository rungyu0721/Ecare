# E-CARE Flutter App

這個資料夾是 E-CARE 的 Flutter 前端。

## 目前功能

- 首頁
- 緊急通報流程
- 聊天頁串接 `/chat`
- 錄音上傳串接 `/audio`
- 通報紀錄頁串接 `/reports`
- 個人資料本地儲存
- 位置顯示與地址查詢 fallback

## 執行方式

```powershell
cd C:\Users\User\Documents\Ecare\flutter_app
flutter pub get
flutter run -d windows
```

## 後端需求

Flutter 前端目前預設連到：

```text
http://127.0.0.1:8000
```

設定位置：

```text
lib/src/config/api_config.dart
```

## 常用指令

```powershell
flutter pub get
flutter analyze
flutter test
flutter run -d windows
```

## 補充

- 目前最方便的開發目標是 Windows 桌面版
- 真正要打包手機版之前，還是要再驗證 Android 的錄音、權限、定位行為
