/**
 * E-CARE 緊急報案系統 - 主要邏輯
 * ====================================================
 * 資料來源：FastAPI 後端 GET /reports
 * API 資料欄位：
 *   id, title, category, risk_level (High/Medium/Low),
 *   risk_score, status, created_at, location,
 *   description (含「建議派遣：」字串)
 * ====================================================
 */

'use strict';

// ====================================================
// 設定
// ====================================================
const API_BASE = 'http://192.168.50.223:8000';
const POLL_INTERVAL = 3000;

// ====================================================
// 全域狀態
// ====================================================
let cases = [];   // 目前所有案件（正規化後）
let localChanges = {};   // { id: { status } } 本地操作覆寫
let logs = [];   // 操作日誌
let selectedCaseId = null;
let soundEnabled = true;
let statsView = 'month';
let lastIds = new Set();

// ====================================================
// API 欄位正規化 - 將後端 raw 資料轉為 UI 統一格式
// ====================================================
function normalizeCase(raw) {
  const level = String(raw.risk_level || 'Low');

  // 風險分數：後端可能是 0~1 的 float 或 0~100 int
  const rawScore = typeof raw.risk_score === 'number' ? raw.risk_score : 0;
  const riskScore = rawScore <= 1 ? Math.round(rawScore * 100) : Math.round(rawScore);

  // 從 description 抽出派遣建議
  const desc = String(raw.description || '');
  const dispatchMatch = desc.match(/建議派遣：[^|。\n]+/);
  const aiSuggestion = dispatchMatch
    ? dispatchMatch[0].replace('建議派遣：', '').trim()
    : '待確認';

  // 解析 location：後端回傳純地址字串，座標由 geocoding 非同步填入
  // 初始 lat/lng 設為 null，geocodeAddress() 會在背景填入後更新地圖
  let lat = null, lng = null;
  const locStr = String(raw.location || '');

  // 若 location 本身含座標格式（備用，防止未來後端改格式）
  const coordMatch = locStr.match(/([-]?\d{1,3}\.\d{4,})[,\s]+([-]?\d{1,3}\.\d{4,})/);
  if (coordMatch) {
    const a = parseFloat(coordMatch[1]);
    const b = parseFloat(coordMatch[2]);
    if (a >= 20 && a <= 27 && b >= 118 && b <= 125) { lat = a; lng = b; }
    else if (b >= 20 && b <= 27 && a >= 118 && a <= 125) { lat = b; lng = a; }
    else { lat = a; lng = b; }
  }

  const createdAt = raw.created_at ? new Date(raw.created_at) : new Date();

  // 本地操作覆寫（例如已標記誤報）
  const local = localChanges[raw.id] || {};
  const status = local.status || raw.status || '處理中';
  const isInactive = (status === '誤報' || status === '已處理');

  const dotClass =
    isInactive ? 'inactive' :
      level === 'High' ? 'danger' :
        level === 'Medium' ? 'warn' : 'safe';

  return {
    id: raw.id,
    code: raw.id ? ('#' + String(raw.id).slice(-4).toUpperCase()) : '#???',
    type: raw.category || raw.title || '未知類型',
    riskScore,
    rawScore,
    riskLevel: level,
    timeAgo: formatTimeAgo(createdAt),
    address: String(raw.location || '地點未提供'),
    level: level === 'High' ? '高風險' : level === 'Medium' ? '中風險' : '低風險',
    dangerLevel: level === 'High' ? '高' : level === 'Medium' ? '中' : '低',
    aiSuggestion,
    eventType: raw.category || raw.title || '未知',
    sceneStatus: desc,
    status,
    statusClass: dotClass,
    lat, lng,
    createdAt,
  };
}

function formatTimeAgo(date) {
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 60) return diff + ' 秒前';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分鐘前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前';
  return Math.floor(diff / 86400) + ' 天前';
}

// ====================================================
// Geocoding：地址 → 座標（Nominatim，免費無需 API key）
// 後端 location 為純地址字串，需 geocode 取得 lat/lng
// ====================================================
var geocodeCache = {};  // { "地址": {lat,lng} | 'pending' | 'failed' }
var geocodeQueue = [];
var geocodeBusy = false;

function cleanAddress(addr) {
  // 移除精度說明，如 "(+/- 89m)"、"(±103m)"
  return String(addr || '').replace(/\s*\(\+\/\-\s*\d+m\)/gi, '').replace(/\s*\(±\d+m\)/gi, '').trim();
}

async function geocodeAddress(addr) {
  var clean = cleanAddress(addr);
  if (!clean) return;
  geocodeCache[clean] = 'pending';
  try {
    var url = 'https://nominatim.openstreetmap.org/search?format=json&limit=1' +
      '&q=' + encodeURIComponent(clean + ', 台灣') +
      '&countrycodes=tw&accept-language=zh-TW';
    var res = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    if (data && data.length > 0) {
      var lat = parseFloat(data[0].lat);
      var lng = parseFloat(data[0].lon);
      geocodeCache[clean] = { lat: lat, lng: lng };
      // 回填所有使用此地址的案件
      cases.forEach(function (c) {
        if (cleanAddress(c.address) === clean && c.lat == null) {
          c.lat = lat; c.lng = lng;
        }
      });
      // 立刻重繪今日地圖標記
      if (typeof renderTodayMapDots === 'function') renderTodayMapDots();
      if (typeof setupMapDots === 'function') setupMapDots();
    } else {
      geocodeCache[clean] = 'failed';
    }
  } catch (e) {
    geocodeCache[clean] = 'failed';
    console.warn('[E-CARE geocode] 失敗:', clean, e.message);
  }
}

async function processGeocodeQueue() {
  if (geocodeBusy) return;
  geocodeBusy = true;
  while (geocodeQueue.length > 0) {
    var addr = geocodeQueue.shift();
    var clean = cleanAddress(addr);
    var cached = geocodeCache[clean];
    if (cached && cached !== 'failed') continue; // 已有結果
    await geocodeAddress(addr);
    await new Promise(function (r) { setTimeout(r, 1200); }); // 避免 rate limit
  }
  geocodeBusy = false;
}

function queueGeocode(addr) {
  if (!addr || addr === '地點未提供') return;
  var clean = cleanAddress(addr);
  var cached = geocodeCache[clean];
  if (cached && cached !== 'failed') {
    // 已有快取，直接回填
    return cached;
  }
  if (geocodeQueue.indexOf(addr) === -1) geocodeQueue.push(addr);
  return null;
}

// ====================================================
// API 輪詢（每 3 秒）
// ====================================================
async function loadCases() {
  try {
    const res = await fetch(API_BASE + '/reports');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const rawData = await res.json();

    const newCases = rawData.map(normalizeCase);
    const currentIds = new Set(newCases.map(x => x.id));

    // 偵測新案件 → Toast 提示
    if (lastIds.size > 0) {
      const newItems = newCases.filter(x => !lastIds.has(x.id));
      if (newItems.length > 0) {
        const hasHigh = newItems.some(x => x.riskLevel === 'High');
        showToast(
          hasHigh
            ? '🚨 新高風險案件：' + newItems[0].type
            : '📢 新案件通報：' + newItems[0].type,
          hasHigh ? 'danger' : 'warn'
        );
      }
    }
    lastIds = currentIds;

    // 保留本地修改過的欄位
    cases = newCases.map(c => {
      const local = localChanges[c.id];
      if (!local) return c;
      return {
        ...c, status: local.status || c.status,
        statusClass: (local.status === '誤報' || local.status === '已處理')
          ? 'inactive' : c.statusClass
      };
    });

    // ★ 對沒有座標的案件，從 geocode cache 回填或加入查詢 queue
    cases.forEach(function (c) {
      if (c.lat != null) return; // 已有座標
      var clean = cleanAddress(c.address);
      var cached = geocodeCache[clean];
      if (cached && cached !== 'pending' && cached !== 'failed') {
        c.lat = cached.lat; c.lng = cached.lng;
      } else {
        queueGeocode(c.address);
      }
    });
    // 啟動 geocode 背景處理
    processGeocodeQueue();

    renderList();
    setupMapDots();       // 頁面二小地圖（已移除 div，此函式內部會 early return）
    updateHeaderStats();

    // ★ 同步更新頁面一今日地圖
    if (typeof renderTodayMapDots === 'function') renderTodayMapDots();
    if (typeof updateMapStats === 'function') updateMapStats();

    // 輪詢時：若有選中案件，只做「局部文字更新」，不重建 DOM
    // 避免地圖 flyTo 抖動、統計圖閃爍、操作日誌跳動
    if (selectedCaseId && cases.find(x => x.id === selectedCaseId)) {
      patchDetailTexts(selectedCaseId);
    }

    document.getElementById('apiErrorBanner')?.remove();
  } catch (err) {
    console.error('API 錯誤:', err);
    showApiError();
  }
}

function showApiError() {
  if (document.getElementById('apiErrorBanner')) return;
  const el = document.createElement('div');
  el.id = 'apiErrorBanner';
  el.style.cssText = [
    'position:fixed', 'top:var(--header-h,110px)', 'left:0', 'right:0',
    'z-index:9500', 'background:rgba(239,68,68,0.12)',
    'border-bottom:1px solid #ef4444', 'color:#ef4444',
    'text-align:center', 'padding:8px 16px', 'font-size:13px',
  ].join(';');
  el.textContent = '⚠️ 無法連線到後端（192.168.50.254:8000），請確認 FastAPI 是否運行中';
  document.body.appendChild(el);
}

// ====================================================
// 初始化
// ====================================================
document.addEventListener('DOMContentLoaded', function () {
  setupSoundToggle();
  setupAddCaseBtn();
  setupStatsToggle();
  initLeafletMap();
  renderList();       // 先渲染空列表（顯示「載入中」）
  loadCases();        // 拉取 API
  setInterval(loadCases, POLL_INTERVAL);
});

// ====================================================
// 渲染左欄案件列表
// ====================================================
function renderList() {
  const container = document.getElementById('caseList');
  if (!container) return;

  if (cases.length === 0) {
    container.innerHTML =
      '<div style="padding:20px;color:var(--text-dim);font-size:13px;text-align:center;">載入中…</div>';
    return;
  }

  // 排序：High > Medium > Low，同級依建立時間新→舊
  const sorted = cases.slice().sort(function (a, b) {
    const w = { High: 3, Medium: 2, Low: 1 };
    const diff = (w[b.riskLevel] || 0) - (w[a.riskLevel] || 0);
    return diff !== 0 ? diff : b.createdAt - a.createdAt;
  });

  container.innerHTML = '';
  sorted.forEach(function (c) {
    const isInactive = (c.status === '誤報' || c.status === '已處理');
    const card = document.createElement('div');
    card.className = [
      'case-card',
      isInactive ? 'inactive' : '',
      selectedCaseId === c.id ? 'active' : '',
    ].filter(Boolean).join(' ');
    card.dataset.id = c.id;
    card.dataset.risk = c.riskLevel;   // ← 供 CSS 色條使用
    card.setAttribute('tabindex', isInactive ? '-1' : '0');
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', '案件 ' + c.code + '，' + c.type + '，' + c.timeAgo);

    const dotClass =
      isInactive ? 'inactive' :
        c.riskLevel === 'High' ? 'danger' :
          c.riskLevel === 'Medium' ? 'warn' : 'safe';

    // 狀態標籤（只在有特殊狀態時顯示）
    var badge = getStatusBadge(c.status);

    card.innerHTML =
      '<div class="case-card-top">' +
      '<span class="case-code">' + c.code + '</span>' +
      '<span class="status-dot ' + dotClass + '"></span>' +
      '<span class="case-type">' + c.type + '</span>' +
      '<span class="case-risk">' + c.riskScore + '</span>' +
      '</div>' +
      '<div class="case-card-bottom">' +
      '<span class="case-time">' + c.timeAgo + '</span>' +
      (badge ? badge : '') +
      '</div>';

    card.addEventListener('click', function () {
      if (isInactive) { showToast('此案件已結案', 'warn'); return; }
      renderDetail(c.id);
    });
    card.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && !isInactive) renderDetail(c.id);
    });

    container.appendChild(card);
  });

  updateHeaderStats();
}

function getStatusBadge(status) {
  if (status === '誤報') return '<span class="case-status-badge misreport">誤報</span>';
  if (status === '已轉人工') return '<span class="case-status-badge transferred">已轉人工</span>';
  if (status === '已處理') return '<span class="case-status-badge handled">已處理</span>';
  return '';
}

// ====================================================
// 渲染中欄案件詳細
// ====================================================
function renderDetail(id) {
  selectedCaseId = id;
  const c = cases.find(function (x) { return x.id === id; });
  if (!c) return;

  // 高亮左欄卡片
  document.querySelectorAll('.case-card').forEach(function (el) {
    el.classList.remove('active');
  });
  const activeCard = document.querySelector('.case-card[data-id="' + CSS.escape(String(id)) + '"]');
  if (activeCard) activeCard.classList.add('active');

  const panel = document.getElementById('detailContent');
  if (!panel) return;

  const isInactive = (c.status === '誤報' || c.status === '已處理' || c.status === '已轉人工');
  const rCls = c.riskLevel === 'High' ? 'danger' : c.riskLevel === 'Medium' ? 'warn' : 'safe';

  flyToCase(id);
  updateDispatchButtons(isInactive);

  const mapsLink = (c.lat != null && c.lng != null)
    ? '<a href="https://www.google.com/maps/search/?api=1&query=' + c.lat + ',' + c.lng +
    '" target="_blank" rel="noopener" style="font-size:12px;color:var(--accent);white-space:nowrap;text-decoration:none;">🗺 Google Maps</a>'
    : '';

  const statusBadgeHtml = (c.status !== '處理中')
    ? '<span class="case-status-badge ' +
    (c.status === '誤報' ? 'misreport' : c.status === '已轉人工' ? 'transferred' : 'handled') +
    '">' + c.status + '</span>'
    : '';

  panel.innerHTML =
    // ---- 標題列 ----
    '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">' +
    '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">' +
    '<span class="case-code" style="font-size:16px;">' + c.code + '</span>' +
    '<span class="risk-badge ' + rCls + '">風險 ' + c.riskScore + '</span>' +
    '<span style="font-size:13px;color:var(--text-muted);">' + c.type + '</span>' +
    statusBadgeHtml +
    '</div>' +
    '<div class="detail-actions">' +
    '<button class="btn-detail-action" onclick="openEditModal(\'' + c.id + '\')" aria-label="修改案件">✏️ 修改</button>' +
    '<button class="btn-detail-action danger-btn" onclick="confirmDelete(\'' + c.id + '\')" aria-label="刪除案件">🗑 刪除</button>' +
    '</div>' +
    '</div>' +

    // ---- 地址 ----
    '<div class="address-field">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>' +
    '<span style="flex:1;">' + c.address + '</span>' +
    mapsLink +
    '</div>' +

    // ---- 建立時間 ----
    '<div style="font-size:12px;color:var(--text-dim);padding:0 4px;">建立時間：' +
    c.createdAt.toLocaleString('zh-TW') + '</div>' +

    // ---- 案件分析 ----
    '<div class="info-section">' +
    '<div class="info-section-header">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>' +
    '案件分析' +
    '</div>' +
    '<div class="info-section-body">' +
    '<div class="info-row"><span class="info-label">分級：</span><span class="info-value ' + rCls + '">' + c.level + '</span></div>' +
    '<div class="info-row"><span class="info-label">危險程度：</span><span class="info-value ' + rCls + '">' + c.dangerLevel + '</span></div>' +
    '<div class="info-row"><span class="info-label">風險分數：</span><span class="info-value">' + (c.rawScore.toFixed ? c.rawScore.toFixed(4) : c.rawScore) + '</span></div>' +
    '<div class="info-row"><span class="info-label">AI 建議：</span><span class="info-value">' + c.aiSuggestion + '</span></div>' +
    '</div>' +
    '</div>' +

    // ---- 案件摘要 ----
    '<div class="info-section">' +
    '<div class="info-section-header">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
    '案件摘要' +
    '</div>' +
    '<div class="info-section-body">' +
    '<div class="info-row"><span class="info-label">事件類型：</span><span class="info-value">' + c.eventType + '</span></div>' +
    '<div class="info-row"><span class="info-label">處理狀態：</span><span class="info-value">' + c.status + '</span></div>' +
    '<div class="info-row" style="align-items:flex-start;"><span class="info-label">案件描述：</span>' +
    '<span class="info-value" style="white-space:pre-wrap;word-break:break-all;">' + c.sceneStatus + '</span></div>' +
    '</div>' +
    '</div>' +

    // ---- 統計圖 ----
    '<div class="chart-container" id="chartArea">' +
    '<div class="chart-title">案件分布（' + (statsView === 'month' ? '本月' : '本年') + '）' +
    '<div class="stats-view-toggle">' +
    '<button class="stats-view-btn ' + (statsView === 'month' ? 'active' : '') + '" onclick="switchStats(\'month\')">月</button>' +
    '<button class="stats-view-btn ' + (statsView === 'year' ? 'active' : '') + '" onclick="switchStats(\'year\')">年</button>' +
    '</div>' +
    '</div>' +
    '<div id="chartInner"></div>' +
    '</div>';

  renderChart();
  renderLog();
}

// ====================================================
// 輪詢專用：只更新中欄已存在的文字節點，不重建 DOM
// 避免 Leaflet flyTo 抖動、圖表閃爍、操作日誌跳動
// ====================================================
function patchDetailTexts(id) {
  const c = cases.find(function (x) { return x.id === id; });
  if (!c) return;

  // 只有 detailContent 已渲染（有子元素）才 patch，避免覆蓋空白初始畫面
  const panel = document.getElementById('detailContent');
  if (!panel || !panel.children.length) return;

  // helper：安全設定文字，只在值有變才改（避免不必要的 repaint）
  function setText(selector, value) {
    var el = panel.querySelector(selector);
    if (el && el.textContent !== String(value)) el.textContent = String(value);
  }

  // 找到各個 info-row 的 info-value（依照 info-label 文字辨識）
  panel.querySelectorAll('.info-row').forEach(function (row) {
    var label = row.querySelector('.info-label');
    var value = row.querySelector('.info-value');
    if (!label || !value) return;
    var key = label.textContent.trim();
    if (key === '處理狀態：' && value.textContent !== c.status) {
      value.textContent = c.status;
    }
    if (key === 'AI 建議：' && value.textContent !== c.aiSuggestion) {
      value.textContent = c.aiSuggestion;
    }
    if (key === '案件描述：' && value.textContent !== c.sceneStatus) {
      value.textContent = c.sceneStatus;
    }
  });

  // 更新地圖標記顏色（若狀態改變）但不 flyTo
  setupMapDots();
}
function updateDispatchButtons(disabled) {
  document.querySelectorAll('.dispatch-btn').forEach(function (btn) {
    btn.disabled = !!disabled;
  });
}

// ====================================================
// 操作日誌
// ====================================================
function renderLog() {
  const logList = document.getElementById('logList');
  if (!logList) return;
  const caseLogs = selectedCaseId
    ? logs.filter(function (l) { return l.caseId === selectedCaseId; })
    : [];
  if (caseLogs.length === 0) {
    logList.innerHTML = '<div class="log-empty">尚無操作紀錄</div>';
    return;
  }
  logList.innerHTML = caseLogs.slice().reverse().map(function (l) {
    return '<div class="log-entry">' +
      '<span class="log-time">' + l.time + '</span>' +
      '<span class="log-op">[' + l.operator + ']</span>' +
      l.action + (l.note ? '：' + l.note : '') +
      '</div>';
  }).join('');
}

function addLog(action, note) {
  note = note || '';
  const c = cases.find(function (x) { return x.id === selectedCaseId; });
  if (!c) return;
  const time = new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  logs.push({ caseId: selectedCaseId, time: time, operator: '機台人員', action: action, note: note, caseCode: c.code });
  renderLog();
}

// ====================================================
// 派遣操作
// ====================================================
function handleDispatch(op, label) {
  if (!selectedCaseId) { showToast('請先選擇一個案件', 'warn'); return; }
  const c = cases.find(function (x) { return x.id === selectedCaseId; });
  if (!c) return;
  if (c.status === '誤報' || c.status === '已處理') {
    showToast('此案件已結案，無法執行操作', 'danger'); return;
  }

  if (op === 'misreport') {
    openModal({
      title: '🚫 標記誤報',
      subtitle: '確定將案件 ' + c.code + '（' + c.type + '）標記為誤報？',
      confirmText: '確認誤報', confirmClass: 'danger', showNote: true,
      onConfirm: function (note) {
        applyLocalStatus(c.id, '誤報');
        addLog('標記誤報', note);
        renderList(); renderDetail(c.id);
        showToast('案件 ' + c.code + ' 已標記為誤報', 'safe');
      }
    });
    return;
  }

  if (op === 'manual') {
    openModal({
      title: '👤 轉人工處理',
      subtitle: '將案件 ' + c.code + ' 轉交人工處理',
      confirmText: '確認轉人工', showNote: true,
      onConfirm: function (note) {
        applyLocalStatus(c.id, '已轉人工');
        addLog('轉人工', note);
        renderList(); renderDetail(c.id);
        showToast('案件 ' + c.code + ' 已轉交人工', 'safe');
      }
    });
    return;
  }

  openModal({
    title: label,
    subtitle: '對案件 ' + c.code + '（' + c.address + '）執行操作',
    confirmText: '確認派遣', showNote: true,
    onConfirm: function (note) {
      addLog(label, note);
      showToast('已執行：' + label, 'safe');
    }
  });
}

function applyLocalStatus(id, status) {
  localChanges[id] = Object.assign({}, localChanges[id] || {}, { status: status });
  const c = cases.find(function (x) { return x.id === id; });
  if (c) {
    c.status = status;
    c.statusClass = (status === '誤報' || status === '已處理') ? 'inactive' : c.statusClass;
  }
}

// ====================================================
// Modal 系統
// ====================================================
let modalOnConfirm = null;

function openModal(config) {
  if (leafletMap) { leafletMap.dragging.disable(); leafletMap.scrollWheelZoom.disable(); }

  var backdrop = document.getElementById('modalBackdrop');
  var titleEl = document.getElementById('modalTitle');
  var subtitleEl = document.getElementById('modalSubtitle');
  var noteEl = document.getElementById('modalNote');
  var noteLblEl = document.getElementById('modalNoteLabel');
  var confirmBtn = document.getElementById('modalConfirmBtn');
  var extraEl = document.getElementById('modalExtraFields');

  titleEl.textContent = config.title || '確認操作';
  subtitleEl.textContent = config.subtitle || '';
  noteLblEl.style.display = config.showNote ? 'block' : 'none';
  noteEl.style.display = config.showNote ? 'block' : 'none';
  noteEl.value = '';
  if (extraEl) extraEl.innerHTML = config.extraFields || '';

  confirmBtn.textContent = config.confirmText || '確認';
  confirmBtn.className = 'btn-confirm' + (config.confirmClass ? ' ' + config.confirmClass : '');
  modalOnConfirm = config.onConfirm || null;

  backdrop.classList.remove('hidden');
  setTimeout(function () {
    var first = backdrop.querySelector('input, textarea, select');
    (first || confirmBtn).focus();
  }, 60);
}

function closeModal() {
  document.getElementById('modalBackdrop').classList.add('hidden');
  modalOnConfirm = null;
  if (leafletMap) { leafletMap.dragging.enable(); leafletMap.scrollWheelZoom.enable(); }
}

function confirmModal() {
  var note = (document.getElementById('modalNote').value || '').trim();
  if (modalOnConfirm) modalOnConfirm(note, document.getElementById('modalExtraFields'));
  closeModal();
}

document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeModal(); });

// ====================================================
// 新增案件（本地，不推送 API）
// ====================================================
function setupAddCaseBtn() {
  var btn = document.getElementById('btnAddCase');
  if (btn) btn.addEventListener('click', openAddModal);
}

function openAddModal() {
  openModal({
    title: '➕ 新增案件',
    subtitle: '（本地新增，不推送後端）',
    confirmText: '新增', showNote: false,
    extraFields:
      '<div class="modal-field"><label class="modal-label">地址 / 地點</label>' +
      '<input class="modal-input" id="ef-address" placeholder="請輸入地址或座標"/></div>' +
      '<div class="modal-field"><label class="modal-label">案件類型</label>' +
      '<select class="modal-select" id="ef-type">' +
      '<option>火災</option><option>可疑人士</option><option>噪音</option>' +
      '<option>交通事故</option><option>醫療緊急</option><option>緊急通報</option><option>其他</option>' +
      '</select></div>' +
      '<div class="modal-field"><label class="modal-label">風險等級</label>' +
      '<select class="modal-select" id="ef-risk">' +
      '<option value="High">高風險</option><option value="Medium" selected>中風險</option><option value="Low">低風險</option>' +
      '</select></div>' +
      '<div class="modal-field"><label class="modal-label">案件描述</label>' +
      '<textarea class="modal-textarea" id="ef-scene" rows="2" placeholder="描述現場狀況"></textarea></div>',
    onConfirm: function () {
      var address = (document.getElementById('ef-address') || {}).value || '';
      var type = (document.getElementById('ef-type') || {}).value || '其他';
      var riskLvl = (document.getElementById('ef-risk') || {}).value || 'Medium';
      var scene = (document.getElementById('ef-scene') || {}).value || '';
      address = address.trim();
      if (!address) { showToast('請填寫地址', 'warn'); return; }

      var fakeId = 'LOCAL_' + Date.now();
      var fakeRaw = {
        id: fakeId, title: type, category: type,
        risk_level: riskLvl,
        risk_score: riskLvl === 'High' ? 0.85 : riskLvl === 'Medium' ? 0.55 : 0.25,
        status: '處理中', created_at: new Date().toISOString(),
        location: address, description: scene,
      };
      cases.push(normalizeCase(fakeRaw));
      renderList(); setupMapDots(); renderDetail(fakeId);
      if (typeof renderTodayMapDots === 'function') renderTodayMapDots();
      showToast('案件已本地新增', 'safe');
    }
  });
}

// ====================================================
// 修改案件（本地）
// ====================================================
function openEditModal(id) {
  var c = cases.find(function (x) { return x.id === id; });
  if (!c) return;
  openModal({
    title: '✏️ 修改案件',
    subtitle: '修改案件 ' + c.code + '（不推送後端）',
    confirmText: '儲存', showNote: false,
    extraFields:
      '<div class="modal-field"><label class="modal-label">案件描述</label>' +
      '<textarea class="modal-textarea" id="ef-scene" rows="4">' + c.sceneStatus + '</textarea></div>' +
      '<div class="modal-field"><label class="modal-label">AI 建議</label>' +
      '<input class="modal-input" id="ef-ai" value="' + c.aiSuggestion + '"/></div>',
    onConfirm: function () {
      var scene = (document.getElementById('ef-scene') || {}).value;
      var ai = (document.getElementById('ef-ai') || {}).value;
      if (scene != null) c.sceneStatus = scene.trim();
      if (ai != null) c.aiSuggestion = ai.trim();
      addLog('修改案件資訊');
      renderList(); renderDetail(c.id);
      showToast('案件資訊已更新', 'safe');
    }
  });
}

// ====================================================
// 刪除案件（本地）
// ====================================================
function confirmDelete(id) {
  var c = cases.find(function (x) { return x.id === id; });
  if (!c) return;
  openModal({
    title: '🗑 刪除案件',
    subtitle: '確定刪除案件 ' + c.code + '（' + c.type + '）？（不推送後端）',
    confirmText: '確認刪除', confirmClass: 'danger', showNote: false,
    onConfirm: function () {
      cases = cases.filter(function (x) { return x.id !== id; });
      delete localChanges[id];
      selectedCaseId = null;
      renderList(); setupMapDots();
      if (typeof renderTodayMapDots === 'function') renderTodayMapDots();
      var panel = document.getElementById('detailContent');
      if (panel) panel.innerHTML =
        '<div class="no-case-selected">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">' +
        '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>' +
        '</svg><p>請從左側選擇案件查看詳細資訊</p></div>';
      var logList = document.getElementById('logList');
      if (logList) logList.innerHTML = '<div class="log-empty">尚無操作紀錄</div>';
      updateDispatchButtons(true);
      showToast('案件已刪除', 'safe');
    }
  });
}

// ====================================================
// 音效開關
// ====================================================
function setupSoundToggle() {
  var btn = document.getElementById('soundToggle');
  if (!btn) return;
  btn.addEventListener('click', function () {
    soundEnabled = !soundEnabled;
    btn.querySelector('.sound-label').textContent = soundEnabled ? '音效：開啟' : '音效：關閉';
    btn.querySelector('.sound-icon').textContent = soundEnabled ? '🔔' : '🔕';
    btn.classList.toggle('off', !soundEnabled);
    showToast(soundEnabled ? '音效已開啟' : '音效已關閉', 'safe');
  });
}

// ====================================================
// 統計切換
// ====================================================
function setupStatsToggle() {
  document.querySelectorAll('.stats-view-btn').forEach(function (btn) {
    btn.addEventListener('click', function () { switchStats(btn.dataset.view); });
  });
}

function switchStats(view) {
  statsView = view;
  document.querySelectorAll('.stats-view-btn').forEach(function (btn) {
    btn.classList.toggle('active',
      btn.dataset.view === view || btn.textContent === (view === 'month' ? '月' : '年'));
  });
  renderChart();
  if (selectedCaseId) renderDetail(selectedCaseId);
  updateHeaderStats();
}

// ====================================================
// Header 統計條（使用真實 API 案件數）
// ====================================================
function updateHeaderStats() {
  var high = cases.filter(function (x) { return x.riskLevel === 'High'; }).length;
  var med = cases.filter(function (x) { return x.riskLevel === 'Medium'; }).length;
  var low = cases.filter(function (x) { return x.riskLevel === 'Low'; }).length;
  var totalEl = document.getElementById('statTotal');
  var dangerEl = document.getElementById('statDanger');
  var warnEl = document.getElementById('statWarn');
  var safeEl = document.getElementById('statSafe');
  if (totalEl) totalEl.textContent = cases.length;
  if (dangerEl) dangerEl.textContent = high;
  if (warnEl) warnEl.textContent = med;
  if (safeEl) safeEl.textContent = low;
}

// ====================================================
// 統計圓餅圖
// ====================================================
function renderChart() {
  var chartInner = document.getElementById('chartInner');
  if (!chartInner) return;
  var high = cases.filter(function (x) { return x.riskLevel === 'High'; }).length;
  var med = cases.filter(function (x) { return x.riskLevel === 'Medium'; }).length;
  var low = cases.filter(function (x) { return x.riskLevel === 'Low'; }).length;
  var total = high + med + low;
  if (total === 0) {
    chartInner.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:10px;">尚無案件資料</div>';
    return;
  }
  var pie = buildPieSVG([
    { value: high, color: 'var(--danger)' },
    { value: med, color: 'var(--warn)' },
    { value: low, color: 'var(--safe)' },
  ], 50);
  chartInner.innerHTML =
    '<div class="pie-chart-wrapper">' + pie +
    '<div class="pie-legend">' +
    '<div class="pie-legend-item"><span class="pie-legend-dot" style="background:var(--danger)"></span> 高風險 ' + high + ' 件</div>' +
    '<div class="pie-legend-item"><span class="pie-legend-dot" style="background:var(--warn)"></span> 中風險 ' + med + ' 件</div>' +
    '<div class="pie-legend-item"><span class="pie-legend-dot" style="background:var(--safe)"></span> 低風險 ' + low + ' 件</div>' +
    '<div class="pie-legend-item" style="margin-top:6px;color:var(--text);font-weight:700;">合計 ' + total + ' 件</div>' +
    '</div>' +
    '</div>';
}

function buildPieSVG(segments, r) {
  var cx = r + 8, cy = r + 8;
  var total = segments.reduce(function (s, seg) { return s + seg.value; }, 0);
  if (total === 0) return '';
  var currentAngle = -90, paths = '';
  segments.forEach(function (seg) {
    if (seg.value === 0) return;
    var angle = (seg.value / total) * 360;
    var startRad = currentAngle * Math.PI / 180;
    var endRad = (currentAngle + angle) * Math.PI / 180;
    var x1 = cx + r * Math.cos(startRad), y1 = cy + r * Math.sin(startRad);
    var x2 = cx + r * Math.cos(endRad), y2 = cy + r * Math.sin(endRad);
    var la = angle > 180 ? 1 : 0;
    paths += '<path d="M' + cx + ',' + cy + ' L' + x1 + ',' + y1 +
      ' A' + r + ',' + r + ' 0 ' + la + ',1 ' + x2 + ',' + y2 +
      ' Z" fill="' + seg.color + '" opacity="0.85"/>';
    currentAngle += angle;
  });
  return '<svg width="' + cx * 2 + '" height="' + cy * 2 + '" viewBox="0 0 ' + cx * 2 + ' ' + cy * 2 + '">' + paths + '</svg>';
}

// ====================================================
// Leaflet 地圖
// ====================================================
var leafletMap = null;
var leafletMarkers = {};

var markerColors = { danger: '#ef4444', warn: '#f59e0b', safe: '#10b981', inactive: '#6b7280' };

function makeCircleIcon(color) {
  return L.divIcon({
    className: '',
    html: '<div style="width:14px;height:14px;border-radius:50%;background:' + color +
      ';border:2px solid rgba(255,255,255,0.85);box-shadow:0 0 8px ' + color + ';"></div>',
    iconSize: [14, 14], iconAnchor: [7, 7], popupAnchor: [0, -10],
  });
}

function initLeafletMap() {
  var container = document.getElementById('leafletMap');
  if (!container || leafletMap) return;
  leafletMap = L.map('leafletMap', { center: [23.9, 121.0], zoom: 7 });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd', maxZoom: 19,
  }).addTo(leafletMap);
}

function setupMapDots() {
  if (!leafletMap) initLeafletMap();
  if (!leafletMap) return;

  // 增量更新：只處理新增/消失的案件，不移除全部 marker
  // 避免每 3 秒輪詢時地圖閃爍抖動

  var currentIds = new Set(cases.map(function (c) { return c.id; }));

  // 1. 移除已不存在的案件 marker
  Object.keys(leafletMarkers).forEach(function (id) {
    if (!currentIds.has(id)) {
      leafletMap.removeLayer(leafletMarkers[id]);
      delete leafletMarkers[id];
    }
  });

  // 2. 新增或更新 marker
  cases.forEach(function (c) {
    if (c.lat == null || c.lng == null) return;
    var isInactive = (c.status === '誤報' || c.status === '已處理');
    var dotKey = isInactive ? 'inactive' :
      c.riskLevel === 'High' ? 'danger' : c.riskLevel === 'Medium' ? 'warn' : 'safe';
    var color = markerColors[dotKey];

    var popupHtml =
      '<div style="font-family:\'Noto Sans TC\',sans-serif;min-width:160px;">' +
      '<div style="font-weight:700;font-size:14px;margin-bottom:4px;">' +
      '<span style="color:' + color + '">' + c.code + '</span> ' + c.type + '</div>' +
      '<div style="font-size:12px;color:#aaa;margin-bottom:4px;">' + c.address + '</div>' +
      '<div style="font-size:12px;">風險：<b style="color:' + color + '">' + c.level + '（' + c.riskScore + '）</b></div>' +
      '<div style="font-size:12px;">狀態：' + c.status + '</div>' +
      '</div>';

    if (leafletMarkers[c.id]) {
      // marker 已存在 → 只更新 icon 顏色（狀態改變時）和 popup 文字，不重建
      leafletMarkers[c.id].setIcon(makeCircleIcon(color));
      leafletMarkers[c.id].setPopupContent(popupHtml);
    } else {
      // 新案件 → 建立 marker
      var marker = L.marker([c.lat, c.lng], { icon: makeCircleIcon(color) });
      marker.bindPopup(popupHtml, { className: 'leaflet-ecare-popup' });
      marker.on('click', (function (caseId, inactive) {
        return function () { if (!inactive) renderDetail(caseId); };
      })(c.id, isInactive));
      marker.addTo(leafletMap);
      leafletMarkers[c.id] = marker;
    }
  });
}

function flyToCase(id) {
  var c = cases.find(function (x) { return x.id === id; });
  if (!c || !leafletMap || c.lat == null || c.lng == null) return;
  leafletMap.flyTo([c.lat, c.lng], 14, { duration: 1.2 });
  var marker = leafletMarkers[id];
  if (marker) setTimeout(function () { marker.openPopup(); }, 1300);
}

// ====================================================
// Toast 通知
// ====================================================
function showToast(msg, type) {
  type = type || 'safe';
  var existing = document.querySelector('.toast');
  if (existing) existing.remove();
  var toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  var colors = { safe: 'var(--safe)', warn: 'var(--warn)', danger: 'var(--danger)' };
  toast.style.cssText =
    'position:fixed;bottom:24px;right:24px;z-index:20000;' +
    'background:var(--panel);border:1px solid ' + (colors[type] || colors.safe) + ';' +
    'color:var(--text);padding:10px 18px;border-radius:8px;' +
    'font-size:13px;box-shadow:0 4px 20px rgba(0,0,0,0.4);animation:fadeIn 0.2s ease;';
  document.body.appendChild(toast);
  setTimeout(function () { toast.style.transition = 'opacity 0.5s'; toast.style.opacity = '0'; }, 2500);
  setTimeout(function () { toast.remove(); }, 3200);
}