# Capacitor Setup

## 目前已完成

- 已建立 `package.json`
- 已建立 `capacitor.config.json`
- `webDir` 目前直接指向專案根目錄，沿用現有 `html/css/js`

## 下一步

在專案根目錄執行：

```powershell
npm.cmd install
npx cap add android
npx cap sync
npx cap open android
```

## 注意

- Android App 內的頁面會由 App 自己提供，不再是 `http://192.168.x.x:5500`
- 這樣麥克風權限會比現在用區網 HTTP 頁面穩定很多
- FastAPI 後端仍可維持用 `http://192.168.50.254:8000`
- 如果之後 API 位址變動，只要改 `ecare.js` 的 `API_BASE`

## 建議後續

- 之後可再加 `@capacitor/geolocation`
- 若錄音要更穩，也可改成 Capacitor / 原生 plugin 路線
