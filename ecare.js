const API_BASE = "http://192.168.50.254:8000"; // ← 改成你的 FastAPI 電腦 IP

const sendBtn = document.getElementById("sendBtn");
const userInput = document.getElementById("userInput");
const chatContainer = document.getElementById("chatContainer");

// 風險卡
const riskBar = document.getElementById("riskBar");
const riskLevelEl = document.getElementById("riskLevel");
const riskScoreEl = document.getElementById("riskScore");
const riskHintEl = document.getElementById("riskHint");

// ✅ High 彩窗
const escalateModal = document.getElementById("escalateModal");
const escalateText = document.getElementById("escalateText");
const goReportCenterBtn = document.getElementById("goReportCenterBtn");
const cancelEscalateBtn = document.getElementById("cancelEscalateBtn");

// 🎙️錄音
const recBtn = document.getElementById("recBtn");
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
const SHOW_VOICE_DEBUG = false;

let messages = [
  { role: "assistant", content: "您好，我是 E-CARE 🤖 請問現在發生什麼事？我會一步步幫助您。" }
];

// ✅ 暫存最後一次分析結果（用來建立通報）
let lastAnalysis = null;

// ✅ 定位暫存（lat/lng/accuracy）
let currentLocation = null;

sendBtn.addEventListener("click", sendMessage);
userInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") sendMessage();
});

function addMessage(text, type) {
  const div = document.createElement("div");
  div.classList.add("message", type === "user" ? "user" : "bot");
  div.textContent = text;
  chatContainer.appendChild(div);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

function setRiskUI(data) {
  if (!riskBar) return;

  riskBar.hidden = false;
  riskLevelEl.textContent = data.risk_level;
  riskScoreEl.textContent = Number(data.risk_score).toFixed(2);

  riskBar.classList.remove("risk-low", "risk-medium", "risk-high");

  if (data.risk_level === "High") {
    riskBar.classList.add("risk-high");
    riskHintEl.textContent = "高風險：建議立即通報並遠離危險。";
  } else if (data.risk_level === "Medium") {
    riskBar.classList.add("risk-medium");
    riskHintEl.textContent = "中風險：請補充地點與現場狀況。";
  } else {
    riskBar.classList.add("risk-low");
    riskHintEl.textContent = "低風險：請描述更多細節，我會協助整理。";
  }
}

// ✅ 把 AI 分析結果整理成較完整的文字
function buildIncidentDescription(analysis) {
  const ex = analysis?.extracted || {};

  const category = ex.category || "待確認";

  const location =
    ex.location ||
    (currentLocation
      ? `${currentLocation.lat.toFixed(6)}, ${currentLocation.lng.toFixed(6)}（±${Math.round(currentLocation.accuracy)}m）`
      : "未提供");

  const injured =
    ex.people_injured === true
      ? "有人受傷或需要醫療協助"
      : ex.people_injured === false
      ? "目前回報無人受傷"
      : "未知";

  const weapon =
    ex.weapon === true
      ? "現場可能有武器"
      : ex.weapon === false
      ? "目前未發現武器"
      : "武器狀況未知";

  const danger =
    ex.danger_active === true
      ? "危險仍在持續"
      : ex.danger_active === false
      ? "危險似乎已暫時解除"
      : "危險狀況未知";

  const dispatch = ex.dispatch_advice || "建議派遣：待確認";
  const risk = analysis?.risk_level || "Low";

  return (
    ex.description ||
    [
      `案件類型：${category}`,
      `地點：${location}`,
      `傷勢：${injured}`,
      `武器：${weapon}`,
      `狀況：${danger}`,
      `風險等級：${risk}`,
      dispatch
    ].join(" | ")
  );
}

// ✅ 取得定位（一次）
async function getLocationOnce() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("此瀏覽器不支援定位"));

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        resolve({ lat: latitude, lng: longitude, accuracy });
      },
      (err) => reject(err),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
    );
  });
}

// ✅ 彩窗顯示/關閉
function openEscalateModal(data) {
  if (!escalateModal) return;

  const hasExtractedLocation = Boolean(data?.extracted?.location);
  const hasGeo = Boolean(currentLocation);
  const dispatchAdvice = data?.extracted?.dispatch_advice || "建議派遣：待確認";

  if (escalateText) {
    if (!hasExtractedLocation && !hasGeo) {
      escalateText.textContent =
        `系統判定可能有立即危害，建議立刻通報。⚠️ 為了快速派遣，請允許定位或手動輸入地址。\n${dispatchAdvice}\n按下「AI 報案中心」將建立一筆通報紀錄。`;
    } else {
      escalateText.textContent =
        `系統判定可能有立即危害，建議立刻通報。\n${dispatchAdvice}\n按下「AI 報案中心」將建立一筆虛擬通報紀錄。`;
    }
  }

  escalateModal.style.display = "flex";
  escalateModal.setAttribute("aria-hidden", "false");
}

function closeEscalateModal() {
  if (!escalateModal) return;
  escalateModal.style.display = "none";
  escalateModal.setAttribute("aria-hidden", "true");
}

// 初始先確保關閉
if (escalateModal) {
  escalateModal.style.display = "none";
  escalateModal.setAttribute("aria-hidden", "true");
}

// 點背景也能關
if (escalateModal) {
  escalateModal.addEventListener("click", (e) => {
    if (e.target === escalateModal) closeEscalateModal();
  });
}

// ESC 關閉
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeEscalateModal();
});

if (cancelEscalateBtn) {
  cancelEscalateBtn.addEventListener("click", () => {
    closeEscalateModal();
    lastAnalysis = null;
    addMessage("了解！如果狀況升級或你感到不安全，請立刻通報並移動到安全處。", "bot");
  });
}

if (goReportCenterBtn) {
  goReportCenterBtn.addEventListener("click", async () => {
    goReportCenterBtn.disabled = true;
    goReportCenterBtn.textContent = "建立通報中…";

    try {
      closeEscalateModal();
      await createReportFromLast();
      userInput.value = "";
      lastAnalysis = null;
    } finally {
      goReportCenterBtn.disabled = false;
      goReportCenterBtn.textContent = "連線 AI 報案中心（Demo）";
    }
  });
}

async function sendMessage() {
  return sendMessageWithOptions();
}

async function sendMessageWithOptions(options = {}) {
  const {
    textOverride = null,
    audioContext = null,
    showUserBubble = true
  } = options;

  const text = (textOverride ?? userInput.value).trim();
  if (!text) return;

  try {
    if (!currentLocation) {
      currentLocation = await getLocationOnce();
      addMessage("📍 已取得目前定位，可用於協助案件派遣。", "bot");
    }
  } catch (e) {
    console.warn("定位取得失敗：", e);
  }

  if (showUserBubble) {
    addMessage(text, "user");
  }
  messages.push({ role: "user", content: text });
  userInput.value = "";

  const typing = document.createElement("div");
  typing.classList.add("message", "bot");
  typing.textContent = "（E-CARE 正在分析…）";
  chatContainer.appendChild(typing);
  chatContainer.scrollTop = chatContainer.scrollHeight;

  try {
    const r = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages,
        audio_context: audioContext
      })
    });

    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();

    typing.remove();

    addMessage(data.reply, "bot");
    messages.push({ role: "assistant", content: data.reply });

    if (data.extracted?.dispatch_advice) {
      addMessage(`🚨 ${data.extracted.dispatch_advice}`, "bot");
      messages.push({ role: "assistant", content: data.extracted.dispatch_advice });
    }

    if (data.next_question) {
      addMessage(data.next_question, "bot");
      messages.push({ role: "assistant", content: data.next_question });
    }

    setRiskUI(data);

    const isRealUserMessage = text && text.length > 0;

    if (isRealUserMessage && data.risk_level === "High") {
      lastAnalysis = data;

      setTimeout(() => openEscalateModal(data), 150);

      addMessage("⚠️ 系統判定高風險：建議立刻通報。我可以協助你建立通報（Demo）。", "bot");
    } else {
      lastAnalysis = data;
    }
  } catch (e) {
    typing.remove();
    addMessage("❌ 連線後端失敗，請確認 FastAPI 是否正在執行，且 API_BASE IP 設定正確。", "bot");
    console.error(e);
  }
}

let recordStartTime = 0;
let lastRecordedBlob = null;

function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const mm = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function createWaveBars(count = 26) {
  let html = "";
  for (let i = 0; i < count; i++) {
    const h = 10 + Math.floor(Math.random() * 28);
    html += `<div class="voice-bar" style="height:${h}px"></div>`;
  }
  return html;
}

function addVoiceMessage(audioUrl, durationSec, onAnalyze) {
  const wrap = document.createElement("div");
  wrap.className = "message user";
  wrap.innerHTML = `
    <div class="voice-message">
      <div class="voice-row">
        <button class="voice-play" type="button">▶</button>
        <div class="voice-wave">${createWaveBars()}</div>
        <div class="voice-duration">${formatDuration(durationSec)}</div>
      </div>

      <div class="voice-actions">
        <button class="voice-send" type="button">送出分析</button>
      </div>

      <div class="voice-meta">🎤 已錄製語音訊息，送出後系統會分析情緒、語意與危急程度。</div>
      <div class="voice-analysis" hidden></div>
    </div>
  `;

  const audio = new Audio(audioUrl);
  const playBtn = wrap.querySelector(".voice-play");
  const wave = wrap.querySelector(".voice-wave");
  const sendBtn = wrap.querySelector(".voice-send");
  const analysisBox = wrap.querySelector(".voice-analysis");
  const metaBox = wrap.querySelector(".voice-meta");

  if (sendBtn) sendBtn.textContent = "送出語音";
  if (metaBox && !SHOW_VOICE_DEBUG) metaBox.hidden = true;
  if (analysisBox && !SHOW_VOICE_DEBUG) analysisBox.hidden = true;

  let playing = false;

  playBtn.addEventListener("click", async () => {
    try {
      if (!playing) {
        await audio.play();
        playing = true;
        playBtn.textContent = "❚❚";
        wave.classList.add("playing");
      } else {
        audio.pause();
        audio.currentTime = 0;
        playing = false;
        playBtn.textContent = "▶";
        wave.classList.remove("playing");
      }
    } catch (err) {
      console.error("播放失敗：", err);
    }
  });

  audio.addEventListener("ended", () => {
    playing = false;
    playBtn.textContent = "▶";
    wave.classList.remove("playing");
  });

  sendBtn.addEventListener("click", async () => {
    sendBtn.disabled = true;
    sendBtn.textContent = "分析中...";
    analysisBox.hidden = false;
    analysisBox.innerHTML = "⏳ 系統正在分析語音內容、情緒與危急程度...";

    try {
      const result = await onAnalyze();

      const transcript = (result.transcript || "").trim();
      const emotion = result.emotion || "unknown";
      const emotionScore =
        result.emotion_score !== undefined && result.emotion_score !== null
          ? Number(result.emotion_score).toFixed(2)
          : "-";
      const situation = result.situation || "未判定";
      const riskLevel = result.risk_level || "未知";
      const riskScore =
        result.risk_score !== undefined && result.risk_score !== null
          ? Number(result.risk_score).toFixed(2)
          : "-";

      analysisBox.innerHTML = `
        <strong>語音轉文字：</strong>${transcript || "（未辨識到文字）"}<br>
        <strong>情緒辨識：</strong>${emotion}（${emotionScore}）<br>
        <strong>情境判斷：</strong>${situation}<br>
        <strong>危急程度：</strong>${riskLevel}（${riskScore}）
      `;

      if (transcript) {
        userInput.value = transcript;
      }

      if (typeof setRiskUI === "function" && result.risk_level) {
        setRiskUI({
          risk_level: result.risk_level,
          risk_score: result.risk_score || 0
        });
      }

      if (typeof addMessage === "function") {
        addMessage("✅ 語音分析完成。", "bot");
      }
      if (typeof addMessage === "function") {
        addMessage("我已經整理出你剛剛說的內容，接著會依照語意、情緒和風險來回覆你。", "bot");
      }

      if (transcript) {
        await sendMessageWithOptions({
          textOverride: transcript,
          audioContext: {
            transcript,
            emotion,
            emotion_score: result.emotion_score,
            situation,
            risk_level: result.risk_level,
            risk_score: result.risk_score,
            extracted: result.extracted || null
          },
          showUserBubble: false
        });
      }
    } catch (e) {
      analysisBox.innerHTML = "❌ 音訊上傳或分析失敗";
      console.error(e);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "重新分析";
    }
  });

  chatContainer.appendChild(wrap);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Override the earlier debug-heavy version with a user-facing voice flow.
function addVoiceMessage(audioUrl, durationSec, onAnalyze) {
  const wrap = document.createElement("div");
  wrap.className = "message user";
  wrap.innerHTML = `
    <div class="voice-message">
      <div class="voice-row">
        <button class="voice-play" type="button">▶</button>
        <div class="voice-wave">${createWaveBars()}</div>
        <div class="voice-duration">${formatDuration(durationSec)}</div>
      </div>
      <div class="voice-actions">
        <button class="voice-send" type="button">送出語音</button>
      </div>
      <div class="voice-meta" ${SHOW_VOICE_DEBUG ? "" : "hidden"}>
        錄音送出後，系統會分析語意、情緒與危急程度。
      </div>
      <div class="voice-analysis" hidden></div>
    </div>
  `;

  const audio = new Audio(audioUrl);
  const playBtn = wrap.querySelector(".voice-play");
  const wave = wrap.querySelector(".voice-wave");
  const sendBtn = wrap.querySelector(".voice-send");
  const analysisBox = wrap.querySelector(".voice-analysis");

  let playing = false;

  playBtn.addEventListener("click", async () => {
    try {
      if (!playing) {
        await audio.play();
        playing = true;
        playBtn.textContent = "■";
        wave.classList.add("playing");
      } else {
        audio.pause();
        audio.currentTime = 0;
        playing = false;
        playBtn.textContent = "▶";
        wave.classList.remove("playing");
      }
    } catch (err) {
      console.error("音訊播放失敗", err);
    }
  });

  audio.addEventListener("ended", () => {
    playing = false;
    playBtn.textContent = "▶";
    wave.classList.remove("playing");
  });

  sendBtn.addEventListener("click", async () => {
    sendBtn.disabled = true;
    sendBtn.textContent = "處理中...";

    if (SHOW_VOICE_DEBUG) {
      analysisBox.hidden = false;
      analysisBox.innerHTML = "正在辨識語音、情緒與風險...";
    } else {
      analysisBox.hidden = true;
      analysisBox.innerHTML = "";
    }

    try {
      const result = await onAnalyze();
      const transcript = (result.transcript || "").trim();
      const emotion = result.emotion || "unknown";
      const emotionScore =
        result.emotion_score !== undefined && result.emotion_score !== null
          ? Number(result.emotion_score).toFixed(2)
          : "-";
      const situation = result.situation || "未判定";
      const riskLevel = result.risk_level || "未知";
      const riskScore =
        result.risk_score !== undefined && result.risk_score !== null
          ? Number(result.risk_score).toFixed(2)
          : "-";

      if (SHOW_VOICE_DEBUG) {
        analysisBox.hidden = false;
        analysisBox.innerHTML = `
          <strong>語音文字：</strong>${transcript || "未辨識到有效內容"}<br>
          <strong>情緒辨識：</strong>${emotion}（${emotionScore}）<br>
          <strong>情境判斷：</strong>${situation}<br>
          <strong>危急程度：</strong>${riskLevel}（${riskScore}）
        `;
      } else {
        analysisBox.hidden = true;
        analysisBox.innerHTML = "";
      }

      if (transcript) {
        userInput.value = transcript;
      }

      if (typeof setRiskUI === "function" && result.risk_level) {
        setRiskUI({
          risk_level: result.risk_level,
          risk_score: result.risk_score || 0
        });
      }

      addMessage("我收到你的語音了，正在幫你整理重點。", "bot");

      if (transcript) {
        await sendMessageWithOptions({
          textOverride: transcript,
          audioContext: {
            transcript,
            emotion,
            emotion_score: result.emotion_score,
            situation,
            risk_level: result.risk_level,
            risk_score: result.risk_score,
            extracted: result.extracted || null
          },
          showUserBubble: false
        });
      }
    } catch (e) {
      if (SHOW_VOICE_DEBUG) {
        analysisBox.hidden = false;
        analysisBox.innerHTML = "語音分析失敗，請再試一次。";
      } else {
        analysisBox.hidden = true;
        analysisBox.innerHTML = "";
      }

      addMessage("語音處理失敗，請再錄一次，或直接輸入文字。", "bot");
      console.error(e);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "送出語音";
    }
  });

  chatContainer.appendChild(wrap);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

// ====== 🎙️ 錄音→語音泡泡→播放→送出分析 ======
if (recBtn) {
  recBtn.addEventListener("click", async () => {
    if (!isRecording) await startRecording();
    else await stopRecordingAndPreview();
  });
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];

    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    recordStartTime = Date.now();
    mediaRecorder.start();
    isRecording = true;
    recBtn.classList.add("active");
    addMessage("🎙️ 開始錄音中…再次按下即可停止。", "bot");
  } catch (e) {
    alert("無法取得麥克風權限：" + e.message);
  }
}

async function stopRecordingAndPreview() {
  if (!mediaRecorder) return;

  const stopped = new Promise((resolve) => {
    mediaRecorder.onstop = resolve;
  });

  mediaRecorder.stop();
  isRecording = false;
  recBtn.classList.remove("active");
  await stopped;

  const blob = new Blob(audioChunks, { type: "audio/webm" });
  lastRecordedBlob = blob;

  const durationSec = (Date.now() - recordStartTime) / 1000;
  const audioUrl = URL.createObjectURL(blob);

  addVoiceMessage(audioUrl, durationSec, async () => {
    return await uploadAudio(blob);
  });
}

async function uploadAudio(blob) {
  const form = new FormData();
  form.append("audio", blob, "recording.webm");

  const r = await fetch(`${API_BASE}/audio`, {
    method: "POST",
    body: form
  });

  if (!r.ok) throw new Error(await r.text());

  const data = await r.json();

  return {
    transcript: (data.transcript || "").trim(),
    emotion: data.emotion || "",
    emotion_score: data.emotion_score,
    situation: data.situation || "",
    risk_level: data.risk_level || "",
    risk_score: data.risk_score,
    extracted: data.extracted || null
  };
}

// ====== ✅ 建立通報（Demo）→ 導去 records.html ======
async function createReportFromLast() {
  if (!lastAnalysis) {
    addMessage("目前沒有可建立的通報資料（請先描述事件讓我分析）。", "bot");
    return;
  }

  const ex = lastAnalysis.extracted || {};
  const category = ex.category || "待確認";

  const location =
    ex.location ||
    (currentLocation
      ? `${currentLocation.lat.toFixed(6)},${currentLocation.lng.toFixed(6)} (±${Math.round(currentLocation.accuracy)}m)`
      : "未提供");

  const description = buildIncidentDescription(lastAnalysis);
  const title = `${category}`;

  try {
    addMessage("📡 正在連線 AI 報案中心（Demo）並建立通報紀錄…", "bot");

    const r = await fetch(`${API_BASE}/reports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        category,
        location,
        risk_level: lastAnalysis.risk_level,
        risk_score: lastAnalysis.risk_score,
        description
      })
    });

    if (!r.ok) throw new Error(await r.text());
    const created = await r.json();

    addMessage(`✅ 通報已建立：${created.id}（${created.status}）`, "bot");

    window.location.href = "records.html";
  } catch (e) {
    addMessage("❌ 建立通報失敗（請確認後端 /reports 正在執行）", "bot");
    console.error(e);
  }
}
