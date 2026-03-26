const API_BASE = "http://10.0.2.2:8000";
const SHOW_VOICE_DEBUG = false;

const sendBtn = document.getElementById("sendBtn");
const userInput = document.getElementById("userInput");
const chatContainer = document.getElementById("chatContainer");
const recBtn = document.getElementById("recBtn");
const recHint = document.getElementById("recHint");

const riskBar = document.getElementById("riskBar");
const riskLevelEl = document.getElementById("riskLevel");
const riskScoreEl = document.getElementById("riskScore");
const riskHintEl = document.getElementById("riskHint");

const escalateModal = document.getElementById("escalateModal");
const escalateText = document.getElementById("escalateText");
const goReportCenterBtn = document.getElementById("goReportCenterBtn");
const cancelEscalateBtn = document.getElementById("cancelEscalateBtn");

const ASSISTANT_GREETING = "您好，我是 E-CARE，請問現在發生什麼事？我會一步步幫助您。";

let messages = [
  { role: "assistant", content: ASSISTANT_GREETING }
];
let lastAnalysis = null;
let currentLocation = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let recordStartTime = 0;

function scrollToBottom() {
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

function addMessage(text, type) {
  const div = document.createElement("div");
  div.classList.add("message", type === "user" ? "user" : "bot");
  div.textContent = text;
  chatContainer.appendChild(div);
  scrollToBottom();
}

function addTypingBubble() {
  const div = document.createElement("div");
  div.classList.add("message", "bot");
  div.textContent = "E-CARE 正在整理回應...";
  chatContainer.appendChild(div);
  scrollToBottom();
  return div;
}

function setRiskUI(data) {
  if (!riskBar || !data) return;

  const riskLevel = data.risk_level || "Low";
  const riskScore = Number(data.risk_score ?? 0).toFixed(2);

  riskBar.hidden = false;
  riskLevelEl.textContent = riskLevel;
  riskScoreEl.textContent = riskScore;
  riskBar.classList.remove("risk-low", "risk-medium", "risk-high");

  if (riskLevel === "High") {
    riskBar.classList.add("risk-high");
    riskHintEl.textContent = "高風險，請先確認自身安全並準備通報。";
  } else if (riskLevel === "Medium") {
    riskBar.classList.add("risk-medium");
    riskHintEl.textContent = "請保持冷靜，我會協助你整理重點。";
  } else {
    riskBar.classList.add("risk-low");
    riskHintEl.textContent = "低風險，請補充更多細節，我會協助整理。";
  }
}

async function clearServiceWorkersAndCaches() {
  try {
    if ("serviceWorker" in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((registration) => registration.unregister()));
      console.log("[E-CARE] cleared service workers:", registrations.length);
    }

    if ("caches" in window) {
      const cacheKeys = await caches.keys();
      await Promise.all(cacheKeys.map((key) => caches.delete(key)));
      console.log("[E-CARE] cleared caches:", cacheKeys);
    }
  } catch (error) {
    console.warn("[E-CARE] cleanup warning", error);
  }
}

async function runConnectivityProbe() {
  console.log("[E-CARE] API_BASE", API_BASE, "href", window.location.href);
  await clearServiceWorkersAndCaches();

  try {
    const response = await fetch(`${API_BASE}/reports`, {
      method: "GET",
      cache: "no-store"
    });

    console.log("[E-CARE] probe status", response.status, response.url);

    if (SHOW_VOICE_DEBUG) {
      addMessage(`API 連線成功：${API_BASE}`, "bot");
    }
  } catch (error) {
    console.error("[E-CARE] probe failed", error);
    if (SHOW_VOICE_DEBUG) {
      addMessage(`API 連線失敗：${API_BASE}\n${error.message || error}`, "bot");
    }
  }
}

function buildIncidentDescription(analysis) {
  const extracted = analysis?.extracted || {};
  const fallbackLocation = currentLocation
    ? `${currentLocation.lat.toFixed(6)}, ${currentLocation.lng.toFixed(6)} (±${Math.round(currentLocation.accuracy)}m)`
    : "未提供";

  return (
    extracted.description ||
    [
      `事件類型：${extracted.category || "未分類"}`,
      `地點：${extracted.location || fallbackLocation}`,
      `是否有人受傷：${extracted.people_injured === true ? "是" : extracted.people_injured === false ? "否" : "未知"}`,
      `是否涉及武器：${extracted.weapon === true ? "是" : extracted.weapon === false ? "否" : "未知"}`,
      `是否仍在危險中：${extracted.danger_active === true ? "是" : extracted.danger_active === false ? "否" : "未知"}`,
      `風險等級：${analysis?.risk_level || "Low"}`,
      extracted.dispatch_advice || "建議持續確認現場安全。"
    ].join(" | ")
  );
}

async function getLocationOnce() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("此裝置不支援定位"));
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy
        });
      },
      (err) => reject(err),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
    );
  });
}

function openEscalateModal(data) {
  if (!escalateModal) return;

  const dispatchAdvice = data?.extracted?.dispatch_advice || "建議盡快聯繫適當的報案單位。";
  const locationText = data?.extracted?.location || (currentLocation ? `${currentLocation.lat.toFixed(6)}, ${currentLocation.lng.toFixed(6)}` : "尚未取得");

  if (escalateText) {
    escalateText.textContent = `目前判定為高風險事件。\n位置：${locationText}\n${dispatchAdvice}`;
  }

  escalateModal.style.display = "flex";
  escalateModal.setAttribute("aria-hidden", "false");
}

function closeEscalateModal() {
  if (!escalateModal) return;
  escalateModal.style.display = "none";
  escalateModal.setAttribute("aria-hidden", "true");
}

async function createReportFromLast() {
  if (!lastAnalysis) {
    addMessage("目前沒有可建立通報的分析結果。", "bot");
    return;
  }

  const extracted = lastAnalysis.extracted || {};
  const payload = {
    title: extracted.category || "E-CARE 通報",
    category: extracted.category || "未分類",
    location: extracted.location || (currentLocation ? `${currentLocation.lat.toFixed(6)}, ${currentLocation.lng.toFixed(6)}` : "未提供"),
    risk_level: lastAnalysis.risk_level || "Low",
    risk_score: lastAnalysis.risk_score ?? 0,
    description: buildIncidentDescription(lastAnalysis)
  };

  goReportCenterBtn.disabled = true;
  goReportCenterBtn.textContent = "建立中...";

  try {
    const response = await fetch(`${API_BASE}/reports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    addMessage("已建立通報紀錄，並送往 AI 報案中心（Demo）。", "bot");
    closeEscalateModal();
  } catch (error) {
    addMessage(`建立通報失敗：${error.message || error}`, "bot");
  } finally {
    goReportCenterBtn.disabled = false;
    goReportCenterBtn.textContent = "前往 AI 報案中心（Demo）";
  }
}

async function sendMessageWithOptions(options = {}) {
  const {
    textOverride = null,
    audioContext = null,
    showUserBubble = true
  } = options;

  const text = (textOverride ?? userInput.value).trim();
  if (!text) return;

  if (showUserBubble) {
    addMessage(text, "user");
  }

  messages.push({ role: "user", content: text });
  userInput.value = "";

  try {
    if (!currentLocation) {
      currentLocation = await getLocationOnce();
      addMessage("已取得目前定位，可用於協助案件派遣。", "bot");
    }
  } catch (locationError) {
    console.warn("[E-CARE] location warning", locationError);
  }

  const typing = addTypingBubble();

  try {
    console.log("[E-CARE] POST", `${API_BASE}/chat`);
    const response = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        messages,
        audio_context: audioContext
      })
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const data = await response.json();
    typing.remove();

    addMessage(data.reply || "我收到你的訊息了。", "bot");
    messages.push({ role: "assistant", content: data.reply || "我收到你的訊息了。" });

    if (data.extracted?.dispatch_advice) {
      addMessage(`派遣建議：${data.extracted.dispatch_advice}`, "bot");
    }

    if (data.next_question) {
      addMessage(data.next_question, "bot");
    }

    setRiskUI(data);
    lastAnalysis = data;

    if (data.risk_level === "High") {
      setTimeout(() => openEscalateModal(data), 150);
      addMessage("這起事件風險偏高，如需要我可以協助你整理通報內容。", "bot");
    }
  } catch (error) {
    typing.remove();
    addMessage("連線後端失敗，請稍後再試。", "bot");
    console.error("[E-CARE] chat failed", error);
  }
}

async function sendMessage() {
  return sendMessageWithOptions();
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const mm = Math.floor(total / 60);
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function createWaveBars(count = 26) {
  const wave = document.createElement("div");
  wave.className = "voice-wave";

  for (let i = 0; i < count; i += 1) {
    const bar = document.createElement("span");
    bar.className = "voice-bar";
    bar.style.height = `${10 + ((i * 7) % 24)}px`;
    wave.appendChild(bar);
  }

  return wave;
}

function addVoiceMessage(audioUrl, durationSec, onAnalyze) {
  const wrapper = document.createElement("div");
  wrapper.className = "voice-message";

  const row = document.createElement("div");
  row.className = "voice-row";

  const playBtn = document.createElement("button");
  playBtn.type = "button";
  playBtn.className = "voice-play";
  playBtn.textContent = "▶";

  const audio = new Audio(audioUrl);
  const wave = createWaveBars();

  const duration = document.createElement("div");
  duration.className = "voice-duration";
  duration.textContent = formatDuration(durationSec);

  row.append(playBtn, wave, duration);

  const actions = document.createElement("div");
  actions.className = "voice-actions";

  const sendVoiceBtn = document.createElement("button");
  sendVoiceBtn.type = "button";
  sendVoiceBtn.textContent = "送出語音";
  actions.appendChild(sendVoiceBtn);

  const meta = document.createElement("div");
  meta.className = "voice-meta";
  meta.hidden = !SHOW_VOICE_DEBUG;
  meta.textContent = "錄音送出後，系統會分析語意、情緒與危急程度。";

  const analysis = document.createElement("div");
  analysis.className = "voice-analysis";
  analysis.hidden = !SHOW_VOICE_DEBUG;

  wrapper.append(row, actions, meta, analysis);
  chatContainer.appendChild(wrapper);
  scrollToBottom();

  playBtn.addEventListener("click", async () => {
    if (audio.paused) {
      await audio.play();
      playBtn.textContent = "⏸";
      wave.classList.add("playing");
    } else {
      audio.pause();
      playBtn.textContent = "▶";
      wave.classList.remove("playing");
    }
  });

  audio.addEventListener("ended", () => {
    playBtn.textContent = "▶";
    wave.classList.remove("playing");
  });

  sendVoiceBtn.addEventListener("click", async () => {
    sendVoiceBtn.disabled = true;
    sendVoiceBtn.textContent = "處理中...";

    try {
      if (SHOW_VOICE_DEBUG) {
        analysis.hidden = false;
        analysis.textContent = "正在辨識語音、情緒與風險...";
      }

      const result = await onAnalyze();
      const transcript = (result.transcript || "").trim();

      if (SHOW_VOICE_DEBUG) {
        analysis.hidden = false;
        analysis.innerHTML = [
          `語音文字：${transcript || "未辨識到有效內容"}`,
          `情緒辨識：${result.emotion || "unknown"}（${Number(result.emotion_score ?? 0).toFixed(2)}）`,
          `情境判斷：${result.situation || "未提供"}`,
          `危急程度：${result.risk_level || "Low"}（${Number(result.risk_score ?? 0).toFixed(2)}）`
        ].join("<br>");
      }

      if (!transcript) {
        addMessage("沒有辨識到清楚的語音內容，請再說一次。", "bot");
        return;
      }

      addMessage("我收到你的語音了，正在幫你整理重點。", "bot");
      await sendMessageWithOptions({
        textOverride: transcript,
        audioContext: {
          transcript,
          emotion: result.emotion || "unknown",
          emotion_score: result.emotion_score,
          situation: result.situation || "",
          risk_level: result.risk_level || "Low",
          risk_score: result.risk_score,
          extracted: result.extracted || null
        },
        showUserBubble: false
      });
    } catch (error) {
      if (SHOW_VOICE_DEBUG) {
        analysis.hidden = false;
        analysis.textContent = `語音分析失敗：${error.message || error}`;
      }

      addMessage("語音處理失敗，請再錄一次，或直接輸入文字。", "bot");
      console.error("[E-CARE] audio failed", error);
    } finally {
      sendVoiceBtn.disabled = false;
      sendVoiceBtn.textContent = "送出語音";
    }
  });
}

async function uploadAudio(blob) {
  const form = new FormData();
  form.append("audio", blob, "recording.webm");

  console.log("[E-CARE] POST", `${API_BASE}/audio`);
  const response = await fetch(`${API_BASE}/audio`, {
    method: "POST",
    cache: "no-store",
    body: form
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  const data = await response.json();
  return {
    transcript: (data.transcript || "").trim(),
    emotion: data.emotion || "unknown",
    emotion_score: data.emotion_score,
    situation: data.situation || "未提供",
    risk_level: data.risk_level || "Low",
    risk_score: data.risk_score,
    extracted: data.extracted || null
  };
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
    };

    recordStartTime = Date.now();
    mediaRecorder.start();
    isRecording = true;
    recBtn.classList.add("active");
    recHint.textContent = "開始錄音中，再按一次即可停止。";
    addMessage("開始錄音中，再按一次即可停止。", "bot");
  } catch (error) {
    alert(`無法取得麥克風權限：${error.message}`);
  }
}

async function stopRecordingAndPreview() {
  if (!mediaRecorder) return;

  const stopped = new Promise((resolve) => {
    mediaRecorder.addEventListener("stop", resolve, { once: true });
  });

  mediaRecorder.stop();
  isRecording = false;
  recBtn.classList.remove("active");
  recHint.textContent = "";

  await stopped;

  const blob = new Blob(audioChunks, { type: "audio/webm" });
  const durationSec = (Date.now() - recordStartTime) / 1000;
  const audioUrl = URL.createObjectURL(blob);

  addVoiceMessage(audioUrl, durationSec, async () => uploadAudio(blob));
}

if (sendBtn) {
  sendBtn.addEventListener("click", sendMessage);
}

if (userInput) {
  userInput.addEventListener("keypress", (event) => {
    if (event.key === "Enter") {
      sendMessage();
    }
  });
}

if (recBtn) {
  recBtn.addEventListener("click", async () => {
    if (isRecording) {
      await stopRecordingAndPreview();
    } else {
      await startRecording();
    }
  });
}

if (cancelEscalateBtn) {
  cancelEscalateBtn.addEventListener("click", closeEscalateModal);
}

if (goReportCenterBtn) {
  goReportCenterBtn.addEventListener("click", createReportFromLast);
}

if (escalateModal) {
  escalateModal.style.display = "none";
  escalateModal.setAttribute("aria-hidden", "true");
  escalateModal.addEventListener("click", (event) => {
    if (event.target === escalateModal) {
      closeEscalateModal();
    }
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeEscalateModal();
  }
});

runConnectivityProbe();


