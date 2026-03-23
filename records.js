const API_BASE = "http://192.168.50.254:8000"; // ← 改成你的 FastAPI 電腦 IP
const list = document.getElementById("list");

function tagClass(level) {
  if (level === "High") return "high";
  if (level === "Medium") return "medium";
  return "low";
}

// ===== 解析座標 =====
function parseLatLng(locationStr) {
  if (!locationStr) return null;

  const head = locationStr.split(" ")[0].trim();
  const parts = head.split(",");

  if (parts.length !== 2) return null;

  const lat = Number(parts[0]);
  const lng = Number(parts[1]);

  if (Number.isFinite(lat) && Number.isFinite(lng)) {
    return { lat, lng };
  }

  return null;
}

function mapsUrlFromLocation(locationStr) {
  const ll = parseLatLng(locationStr);
  if (!ll) return null;
  return `https://www.google.com/maps?q=${ll.lat},${ll.lng}`;
}

// ===== 取得 AI 派遣建議 =====
function extractDispatchAdvice(desc) {
  if (!desc) return null;

  const match = desc.match(/建議派遣：[^|]+/);
  if (match) return match[0];

  return null;
}

// ===== 反向地理編碼 =====
const GEO_CACHE_KEY = "ecare_geo_cache_v1";

const geoCache = (() => {
  try {
    return JSON.parse(localStorage.getItem(GEO_CACHE_KEY) || "{}");
  } catch {
    return {};
  }
})();

function geoKey(lat, lng) {
  return `${lat.toFixed(5)},${lng.toFixed(5)}`;
}

function saveGeoCache() {
  localStorage.setItem(GEO_CACHE_KEY, JSON.stringify(geoCache));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let geoQueue = Promise.resolve();

async function reverseGeocode(lat, lng) {
  const key = geoKey(lat, lng);

  if (geoCache[key]) return geoCache[key];

  geoQueue = geoQueue.then(async () => {
    await sleep(1000);

    const url =
      `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}&accept-language=zh-TW`;

    const res = await fetch(url, { referrerPolicy: "no-referrer" });

    if (!res.ok) throw new Error("反向地理編碼失敗");

    const data = await res.json();
    const addr = data.display_name || "";

    geoCache[key] = addr;
    saveGeoCache();
  });

  await geoQueue;
  return geoCache[key] || null;
}

// ===== 載入通報 =====
async function load() {
  list.innerHTML = "<div class='card'>載入中...</div>";

  try {
    const r = await fetch(`${API_BASE}/reports`);

    if (!r.ok) throw new Error(await r.text());

    const data = await r.json();

    data.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    if (!data.length) {
      list.innerHTML = "<div class='card'>目前沒有通報紀錄</div>";
      return;
    }

    list.innerHTML = "";

    for (const item of data) {
      const card = document.createElement("div");
      card.className = "card";

      const mapUrl = mapsUrlFromLocation(item.location);

      const score =
        typeof item.risk_score === "number"
          ? item.risk_score.toFixed(2)
          : item.risk_score;

      const desc = item.description || "（無）";
      const dispatchAdvice = extractDispatchAdvice(desc);
      const rawLocation = item.location || "未提供";
      const ll = parseLatLng(item.location);

      card.innerHTML = `
        <div class="row">
          <div class="tag ${tagClass(item.risk_level)}">
            ${item.id}｜${item.risk_level}
          </div>

          <div class="status">${item.status}</div>
        </div>

        <div class="meta">
          <div class="meta-line">案件類型：${item.category}</div>
          <div class="meta-line">風險分數：${score}</div>

          <div class="loc-row">
            <div class="loc-left">
              <div class="loc-line">
                <span class="loc-label">位置：</span>
                <span class="loc-primary">${rawLocation}</span>
              </div>

              <div class="loc-secondary" style="display:none;"></div>
            </div>

            ${mapUrl ? `<a class="map-btn" href="${mapUrl}" target="_blank">📍 地圖</a>` : ""}
          </div>

          ${
            dispatchAdvice
              ? `<div class="dispatch">${dispatchAdvice}</div>`
              : ""
          }

          <div class="meta-line">案件摘要：${desc}</div>
          <div class="meta-line small">${item.created_at}</div>
        </div>
      `;

      list.appendChild(card);

      if (ll) {
        try {
          const addr = await reverseGeocode(ll.lat, ll.lng);

          if (addr) {
            const primary = card.querySelector(".loc-primary");
            const secondary = card.querySelector(".loc-secondary");

            if (primary) primary.textContent = addr;

            if (secondary) {
              secondary.style.display = "block";
              secondary.textContent = `座標：${ll.lat.toFixed(6)}, ${ll.lng.toFixed(6)}`;
            }
          }
        } catch (e) {
          console.warn("地址轉換失敗：", e);
        }
      }
    }
  } catch (e) {
    list.innerHTML =
      "<div class='card'>❌ 無法載入通報紀錄，請確認後端正在執行，且 API_BASE 設定正確</div>";

    console.error(e);
  }
}

load();