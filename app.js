// app.js（保留原本功能 + 新增使用者資料整合版本）
const API_BASE = "http://192.168.50.254:8000"; // ← 改成你的 FastAPI 電腦 IP

// UI
const holdBtn = document.getElementById("holdBtn");
const progressBar = document.getElementById("progressBar");
const holdHint = document.getElementById("holdHint");
const locText = document.getElementById("locText");
const statusText = document.getElementById("statusText");
const resultBox = document.getElementById("resultBox");
const welcomeText = document.getElementById("welcomeText");

const testCallBtn = document.getElementById("testCallBtn");
const resetBtn = document.getElementById("resetBtn");

const goEcare = document.getElementById("goEcare");
const goHistory = document.getElementById("goHistory");
const goTypes = document.getElementById("goTypes");
const goProfile = document.getElementById("goProfile");

// ===== 使用者資料 =====
const PROFILE_KEY = "ecare_user_profile";

function getUserProfile() {
  try {
    return JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}");
  } catch (e) {
    console.error("讀取使用者資料失敗：", e);
    return {};
  }
}

function hasValidProfile(profile) {
  return Boolean(profile && profile.name && profile.phone);
}

function ensureUserProfile() {
  const profile = getUserProfile();

  if (!hasValidProfile(profile)) {
    window.location.href = "profile.html";
    return null;
  }

  return profile;
}

function buildProfileText(profile) {
  return [
    `報案人姓名：${profile.name || "未提供"}`,
    `報案人電話：${profile.phone || "未提供"}`,
    `緊急聯絡人：${profile.emergencyName || "未提供"}`,
    `緊急聯絡電話：${profile.emergencyPhone || "未提供"}`,
    `常用地址：${profile.address || "未提供"}`,
    `關係：${profile.relationship || "未提供"}`,
    `備註：${profile.note || "未提供"}`
  ].join(" | ");
}

// ===== UI 文案（統一管理）=====
const TIP_TEXT =
  "💡 提示：緊急通報時會自動取得定位並建立通報紀錄（可在「通報紀錄」查看地圖）。";

// PWA: service worker
//if ("serviceWorker" in navigator) {
//  navigator.serviceWorker.register("./sw.js").catch(console.error);
//}

// ===== 定位（主畫面只顯示狀態，不顯示經緯度）=====
let lastLoc = null;

function setLocUI(state, accuracyM = null) {
  if (!locText || !statusText) return;

  if (state === "idle") {
    locText.textContent = "未啟用";
    statusText.textContent = "待命";
    return;
  }

  if (state === "loading") {
    locText.textContent = "取得中…";
    statusText.textContent = "正在取得定位…";
    return;
  }

  if (state === "ok") {
    locText.textContent = accuracyM != null ? `已取得（±${accuracyM}m）` : "已取得";
    statusText.textContent = "定位已取得";
    return;
  }

  if (state === "fail") {
    locText.textContent = "未啟用";
    statusText.textContent = "定位失敗（未授權或逾時）";
  }
}

function getLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      setLocUI("fail");
      return reject(new Error("此裝置不支援定位"));
    }

    setLocUI("loading");

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        lastLoc = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        };

        setLocUI("ok", Math.round(lastLoc.accuracy));
        resolve(lastLoc);
      },
      (err) => {
        setLocUI("fail");
        reject(err);
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
    );
  });
}

async function postJSON(path, payload) {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!r.ok) throw new Error(`API 錯誤 ${r.status}: ${await r.text()}`);
  return r.json();
}

// ===== 長按 3 秒緊急 =====
let holdTimer = null;
let startTime = 0;
let rafId = null;
const HOLD_MS = 3000;

function resetHoldUI() {
  if (progressBar) progressBar.style.width = "0%";
  if (holdHint) {
    holdHint.textContent = "長按以啟動緊急流程";
    holdHint.style.background = "rgba(0,0,0,.18)";
  }
}

function updateProgress() {
  const elapsed = Date.now() - startTime;
  const pct = Math.min(100, (elapsed / HOLD_MS) * 100);
  if (progressBar) progressBar.style.width = pct.toFixed(1) + "%";

  if (elapsed < HOLD_MS) {
    rafId = requestAnimationFrame(updateProgress);
  }
}

async function triggerEmergency() {
  try {
    const profile = ensureUserProfile();
    if (!profile) return;

    if (holdHint) holdHint.textContent = "已觸發：送出定位通報中…";
    if (statusText) statusText.textContent = "緊急通報中…";

    const loc = lastLoc || (await getLocation());
    const profileText = buildProfileText(profile);

    const payload = {
      title: "緊急通報",
      category: "緊急",
      location: `${loc.lat.toFixed(6)},${loc.lng.toFixed(6)} (±${Math.round(loc.accuracy)}m)`,
      risk_level: "High",
      risk_score: 1.0,
      description:
        `緊急按鈕觸發（長按 3 秒）。timestamp=${new Date().toISOString()}\n${profileText}`,
    };

    const data = await postJSON("/reports", payload);

    if (navigator.vibrate) {
      navigator.vibrate([200, 100, 200]);
    }

    if (resultBox) {
      const id = data?.id ?? "(無ID)";
      const st = data?.status ?? "已建立";
      resultBox.textContent =
        `✅ 已建立通報：${id}（${st}）\n` +
        `👤 報案人：${profile.name || "未提供"}\n` +
        `📌 可至「通報紀錄」查看詳細位置與地圖。`;
    }

    if (statusText) statusText.textContent = "緊急通報已送出 ✅";
    if (holdHint) holdHint.textContent = "即將跳出撥號（110）…";

    window.location.href = "tel:110";
  } catch (e) {
    if (resultBox) resultBox.textContent = `❌ 通報失敗：${e.message}`;
    if (statusText) statusText.textContent = "緊急通報失敗 ❌";
    alert(e.message);
  } finally {
    resetHoldUI();
  }
}

function startHold() {
  if (holdTimer) return;

  startTime = Date.now();
  if (holdHint) {
    holdHint.textContent = "保持按住…（3 秒後啟動）";
    holdHint.style.background = "rgba(0,0,0,.28)";
  }

  rafId = requestAnimationFrame(updateProgress);

  holdTimer = setTimeout(() => {
    holdTimer = null;
    if (rafId) cancelAnimationFrame(rafId);
    triggerEmergency();
  }, HOLD_MS);
}

function cancelHold() {
  if (holdTimer) {
    clearTimeout(holdTimer);
    holdTimer = null;
  }
  if (rafId) cancelAnimationFrame(rafId);
  resetHoldUI();
}

// mouse + touch
if (holdBtn) {
  holdBtn.addEventListener("mousedown", startHold);
  holdBtn.addEventListener("mouseup", cancelHold);
  holdBtn.addEventListener("mouseleave", cancelHold);

  holdBtn.addEventListener(
    "touchstart",
    (e) => {
      e.preventDefault();
      startHold();
    },
    { passive: false }
  );

  holdBtn.addEventListener("touchend", cancelHold);
  holdBtn.addEventListener("touchcancel", cancelHold);
}

// 測試撥號
if (testCallBtn) {
  testCallBtn.addEventListener("click", () => {
    window.location.href = "tel:110";
  });
}

// 重置
if (resetBtn) {
  resetBtn.addEventListener("click", () => {
    lastLoc = null;
    setLocUI("idle");

    if (resultBox) resultBox.textContent = TIP_TEXT;

    resetHoldUI();
  });
}

// ===== 主畫面導頁 =====
if (goEcare) {
  goEcare.addEventListener("click", () => {
    window.location.href = "ecare.html";
  });
}

if (goHistory) {
  goHistory.addEventListener("click", () => {
    window.location.href = "records.html";
  });
}

if (goTypes) {
  goTypes.addEventListener("click", () => {
    alert("事件類型說明頁（types.html）尚未建立");
  });
}

if (goProfile) {
  goProfile.addEventListener("click", () => {
    window.location.href = "profile.html";
  });
}

// 初始化
(function init() {
  const profile = ensureUserProfile();
  if (!profile) return;

  resetHoldUI();
  setLocUI("idle");

  if (welcomeText && profile.name) {
    welcomeText.textContent = `您好，${profile.name} 👋`;
  }

  if (resultBox) {
    resultBox.textContent =
      `${TIP_TEXT}\n` +
      `👤 目前使用者：${profile.name || "未提供"} / ${profile.phone || "未提供"}`;
  }
})();