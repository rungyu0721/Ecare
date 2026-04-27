const API_BASE = "http://192.168.50.223:8000/";
const listEl = document.getElementById("caseList");
const statTotalEl = document.getElementById("statTotal");
const statHighEl = document.getElementById("statDanger");
const statMediumEl = document.getElementById("statWarn");
const statLowEl = document.getElementById("statSafe");

let lastIds = new Set();

function riskWeight(level) {
  if (level === "High") return 3;
  if (level === "Medium") return 2;
  return 1;
}

function riskClass(level) {
  if (level === "High") return "high";
  if (level === "Medium") return "medium";
  return "low";
}

function riskLabel(level) {
  if (level === "High") return "高風險";
  if (level === "Medium") return "中風險";
  return "低風險";
}

function escapeHtml(str = "") {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function extractDispatchAdvice(description = "") {
  const match = String(description).match(/建議派遣：[^|。\n]+/);
  return match ? match[0] : "建議派遣：待確認";
}

function buildMapLink(location = "") {
  const text = String(location).trim();
  if (!text || text === "未提供") return null;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(text)}`;
}

function updateStats(data) {
  const total = data.length;
  const high = data.filter(x => x.risk_level === "High").length;
  const medium = data.filter(x => x.risk_level === "Medium").length;
  const low = data.filter(x => x.risk_level === "Low").length;

  if (statTotalEl) statTotalEl.textContent = total;
  if (statHighEl) statHighEl.textContent = high;
  if (statMediumEl) statMediumEl.textContent = medium;
  if (statLowEl) statLowEl.textContent = low;
}

function renderCases(data) {
  if (!listEl) return;

  if (!data.length) {
    listEl.innerHTML = `<div class="empty">目前沒有案件通報</div>`;
    return;
  }

  const sorted = [...data].sort((a, b) => {
    const riskDiff = riskWeight(b.risk_level) - riskWeight(a.risk_level);
    if (riskDiff !== 0) return riskDiff;
    return String(b.created_at || "").localeCompare(String(a.created_at || ""));
  });

  listEl.innerHTML = sorted.map(item => {
    const riskCls = riskClass(item.risk_level);
    const riskText = riskLabel(item.risk_level);
    const dispatchAdvice = extractDispatchAdvice(item.description);
    const mapLink = buildMapLink(item.location);
    const score = typeof item.risk_score === "number"
      ? item.risk_score.toFixed(2)
      : (item.risk_score ?? "-");

    return `
      <div class="case-card ${riskCls}">
        <div class="case-top">
          <div>
            <div class="case-title">${escapeHtml(item.title || item.category || "未命名案件")}</div>
            <div class="case-id">案件編號：${escapeHtml(item.id || "-")}</div>
          </div>
          <div class="risk-badge ${riskCls}">${escapeHtml(riskText)}</div>
        </div>

        <div class="case-grid">
          <div><span class="k">案件類型：</span>${escapeHtml(item.category || "待確認")}</div>
          <div><span class="k">風險分數：</span>${escapeHtml(score)}</div>
          <div><span class="k">處理狀態：</span>${escapeHtml(item.status || "處理中")}</div>
          <div><span class="k">建立時間：</span>${escapeHtml(item.created_at || "-")}</div>
        </div>

        <div class="case-section">
          <div class="k">地點</div>
          <div class="location-row">
            <div class="location-text">${escapeHtml(item.location || "未提供")}</div>
            ${mapLink
        ? `<a class="map-btn" href="${mapLink}" target="_blank" rel="noopener noreferrer">📍 查看地圖</a>`
        : ""
      }
          </div>
        </div>

        <div class="case-section">
          <div class="k">派遣建議</div>
          <div class="dispatch-box">${escapeHtml(dispatchAdvice)}</div>
        </div>

        <div class="case-section">
          <div class="k">案件摘要</div>
          <div class="summary-text">${escapeHtml(item.description || "（無摘要）")}</div>
        </div>
      </div>
    `;
  }).join("");
}

function notifyNewCases(data) {
  const currentIds = new Set(data.map(x => x.id));
  const newItems = data.filter(x => !lastIds.has(x.id));

  if (lastIds.size > 0 && newItems.length > 0) {
    const highNew = newItems.some(x => x.risk_level === "High");
    alert(highNew ? "🚨 警示：有新的高風險案件通報！" : "📢 有新的案件通報！");
  }

  lastIds = currentIds;
}

async function loadCases() {
  try {
    const res = await fetch(`${API_BASE}/reports`);
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    notifyNewCases(data);
    updateStats(data);
    renderCases(data);
  } catch (err) {
    console.error(err);
    if (listEl) {
      listEl.innerHTML = `<div class="empty">❌ 無法連線到後端，請確認 FastAPI 是否正在執行</div>`;
    }
  }
}

loadCases();
setInterval(loadCases, 3000);