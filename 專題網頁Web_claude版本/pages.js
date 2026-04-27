/**
 * E-CARE pages.js
 * 頁面切換、頁面一（今日地圖）、頁面三（歷史紀錄）
 */
'use strict';

// ====================================================
// 歷史紀錄儲存（跨日保留）
// key: "YYYY-MM-DD"，value: 當日案件陣列快照
// ====================================================
var caseHistory = {};      // { "2026-03-12": [...cases] }
var currentPage = 'map';

// 今日地圖（全螢幕）
var todayMap = null;
var todayMarkers = {};

var markerColorsPage = {
  danger: '#ef4444', warn: '#f59e0b', safe: '#10b981', inactive: '#6b7280'
};

// ====================================================
// 頁面切換
// ====================================================
function switchPage(page) {
  currentPage = page;

  ['map', 'officer', 'history'].forEach(function (p) {
    var el = document.getElementById('page-' + p);
    if (!el) return;
    el.style.display = (p === page) ? 'block' : 'none';
  });

  document.querySelectorAll('.page-nav-btn').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.page === page);
  });

  if (page === 'map') {
    initTodayMap();
    setTimeout(function () {
      if (todayMap) todayMap.invalidateSize();
    }, 60);
    renderTodayMapDots();
    updateMapStats();
  } else if (page === 'officer') {
    // 頁面二：三欄操作介面，地圖需要 invalidate
    setTimeout(function () {
      if (typeof leafletMap !== 'undefined' && leafletMap) leafletMap.invalidateSize();
    }, 60);
  } else if (page === 'history') {
    // 先儲存今日快照再渲染
    saveTodaySnapshot();
    renderHistory();
  }
}

// ====================================================
// 頁面一：今日事件地圖
// ====================================================
function initTodayMap() {
  if (todayMap) return;
  var container = document.getElementById('todayMap');
  if (!container) return;

  todayMap = L.map('todayMap', {
    center: [23.9, 121.0],
    zoom: 8,
    zoomControl: true,
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(todayMap);
}

function makeTodayIcon(color, isHandled) {
  var size = isHandled ? 14 : 18;
  var pulse = isHandled ? '' :
    '<div style="position:absolute;inset:-4px;border-radius:50%;border:2px solid ' + color +
    ';animation:pulse-marker 2s infinite;opacity:0.5;"></div>';
  return L.divIcon({
    className: '',
    html: '<div style="position:relative;width:' + size + 'px;height:' + size + 'px;">' +
      pulse +
      '<div style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;' +
      'background:' + color + ';border:2.5px solid rgba(255,255,255,0.9);' +
      'box-shadow:0 0 ' + (isHandled ? '4' : '10') + 'px ' + color + ';' +
      'opacity:' + (isHandled ? '0.5' : '1') + ';"></div>' +
      '</div>',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2 - 4],
  });
}

function renderTodayMapDots() {
  if (!todayMap) return;

  var allCases = typeof cases !== 'undefined' ? cases : [];
  var currentIds = new Set(allCases.map(function (c) { return c.id; }));

  // 移除消失的
  Object.keys(todayMarkers).forEach(function (id) {
    if (!currentIds.has(id)) {
      todayMap.removeLayer(todayMarkers[id]);
      delete todayMarkers[id];
    }
  });

  allCases.forEach(function (c) {
    if (c.lat == null || c.lng == null) return;

    var isHandled = (c.status === '誤報' || c.status === '已處理' || c.status === '已轉人工');
    var dotKey = isHandled ? 'inactive' :
      c.riskLevel === 'High' ? 'danger' :
        c.riskLevel === 'Medium' ? 'warn' : 'safe';
    var color = markerColorsPage[dotKey];
    var icon = makeTodayIcon(color, isHandled);

    if (todayMarkers[c.id]) {
      todayMarkers[c.id].setIcon(icon);
    } else {
      var marker = L.marker([c.lat, c.lng], { icon: icon });
      marker.on('click', (function (caseObj) {
        return function () { showMapInfoCard(caseObj); };
      })(c));
      marker.addTo(todayMap);
      todayMarkers[c.id] = marker;
    }
  });

  updateMapStats();
}

// 案件資訊卡（地圖右側）
function showMapInfoCard(c) {
  var card = document.getElementById('mapInfoCard');
  var body = document.getElementById('mapInfoBody');
  if (!card || !body) return;

  var isHandled = (c.status === '誤報' || c.status === '已處理' || c.status === '已轉人工');
  var rCls = c.riskLevel === 'High' ? 'danger' : c.riskLevel === 'Medium' ? 'warn' : 'safe';
  var dotColor = isHandled ? '#6b7280' :
    (c.riskLevel === 'High' ? '#ef4444' : c.riskLevel === 'Medium' ? '#f59e0b' : '#10b981');

  var statusIcon = isHandled ? '✅' : '🔴';
  var statusText = isHandled ? c.status : '未處理';
  var statusStyle = isHandled
    ? 'color:var(--safe);background:rgba(16,185,129,0.12);'
    : 'color:var(--danger);background:rgba(239,68,68,0.12);';

  body.innerHTML =
    // 頂部色條
    '<div style="height:4px;background:' + dotColor + ';border-radius:4px 4px 0 0;margin:-16px -16px 14px;"></div>' +

    // 標題
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">' +
    '<span style="width:10px;height:10px;border-radius:50%;background:' + dotColor + ';flex-shrink:0;box-shadow:0 0 6px ' + dotColor + ';display:inline-block;"></span>' +
    '<span style="font-size:15px;font-weight:700;color:var(--text);">' + c.code + '&nbsp;' + c.type + '</span>' +
    '</div>' +

    // 狀態徽章
    '<div style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;margin-bottom:12px;' + statusStyle + '">' +
    statusIcon + '&nbsp;' + statusText +
    '</div>' +

    // 資訊列
    '<div class="mc-row"><span class="mc-label">類型</span><span>' + c.type + '</span></div>' +
    '<div class="mc-row"><span class="mc-label">風險</span>' +
    '<span class="risk-badge ' + rCls + '" style="font-size:11px;">' + c.level + '（' + c.riskScore + '）</span>' +
    '</div>' +
    '<div class="mc-row" style="align-items:flex-start;"><span class="mc-label">地點</span>' +
    '<span style="flex:1;word-break:break-all;font-size:12px;">' + c.address + '</span>' +
    '</div>' +
    '<div class="mc-row"><span class="mc-label">建立</span><span style="font-size:12px;">' + c.createdAt.toLocaleString('zh-TW') + '</span></div>' +

    // 描述
    (c.sceneStatus
      ? '<div style="margin-top:10px;padding:8px 10px;background:var(--panel-2);border-radius:6px;font-size:12px;color:var(--text-muted);max-height:80px;overflow-y:auto;word-break:break-all;">' + c.sceneStatus + '</div>'
      : '') +

    // 按鈕：跳至警員操作頁處理
    (!isHandled
      ? '<button onclick="switchPage(\'officer\');setTimeout(function(){renderDetail(\'' + c.id + '\');},80);" ' +
      'style="margin-top:12px;width:100%;background:var(--accent);border:none;border-radius:6px;padding:9px;' +
      'color:white;font-size:13px;font-weight:700;cursor:pointer;font-family:var(--font);">⚡ 前往處理</button>'
      : '<div style="margin-top:10px;text-align:center;font-size:12px;color:var(--text-dim);">此案件已結案</div>');

  card.classList.remove('hidden');

  // 地圖飛行
  if (c.lat != null && c.lng != null) {
    todayMap.flyTo([c.lat, c.lng], 14, { duration: 0.8 });
  }
}

function closeMapCard() {
  var card = document.getElementById('mapInfoCard');
  if (card) card.classList.add('hidden');
}

// 右下統計
function updateMapStats() {
  var allCases = typeof cases !== 'undefined' ? cases : [];
  var high = allCases.filter(function (c) { return c.riskLevel === 'High'; }).length;
  var med = allCases.filter(function (c) { return c.riskLevel === 'Medium'; }).length;
  var low = allCases.filter(function (c) { return c.riskLevel === 'Low'; }).length;

  function set(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; }
  set('mtsTotal', allCases.length);
  set('mtsDanger', high);
  set('mtsWarn', med);
  set('mtsSafe', low);

  var dateEl = document.getElementById('mtsDate');
  if (dateEl) {
    var now = new Date();
    dateEl.textContent = now.getFullYear() + '/' +
      String(now.getMonth() + 1).padStart(2, '0') + '/' +
      String(now.getDate()).padStart(2, '0');
  }
}

// ====================================================
// 頁面三：歷史紀錄
// ====================================================

// 取得今日日期字串 YYYY-MM-DD
function todayKey() {
  var d = new Date();
  return d.getFullYear() + '-' +
    String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

// 每天凌晨 12 點將今日案件存入歷史
function saveTodaySnapshot() {
  var key = todayKey();
  var snap = typeof cases !== 'undefined' ? cases : [];
  if (snap.length > 0) {
    // 序列化（避免參考問題）
    caseHistory[key] = snap.map(function (c) { return Object.assign({}, c); });
  }
}

// 自動在凌晨存檔的 timer
function scheduleAutoSnapshot() {
  var now = new Date();
  var next = new Date(now);
  next.setDate(next.getDate() + 1);
  next.setHours(0, 0, 5, 0);  // 凌晨 00:00:05
  var msUntil = next.getTime() - now.getTime();

  setTimeout(function () {
    saveTodaySnapshot();
    // 之後每 24 小時執行一次
    setInterval(saveTodaySnapshot, 24 * 60 * 60 * 1000);
  }, msUntil);
}

function renderHistory() {
  // 先更新今日快照
  saveTodaySnapshot();

  var groups = document.getElementById('historyGroups');
  var countEl = document.getElementById('historyCount');
  if (!groups) return;

  var filterDate = (document.getElementById('filterDate') || {}).value || '';
  var filterRisk = (document.getElementById('filterRisk') || {}).value || '';
  var filterStatus = (document.getElementById('filterStatus') || {}).value || '';
  var filterKeyword = ((document.getElementById('filterKeyword') || {}).value || '').trim().toLowerCase();

  // 設定今日為預設日期
  var dateInput = document.getElementById('filterDate');
  if (dateInput && !dateInput.value) {
    dateInput.value = todayKey();
    filterDate = todayKey();
  }

  // 收集所有日期（從 caseHistory 取）
  var allDates = Object.keys(caseHistory).sort().reverse();  // 新→舊

  // 如果有指定日期就只顯示那天
  if (filterDate) allDates = allDates.filter(function (d) { return d === filterDate; });

  var totalCount = 0;
  var html = '';

  allDates.forEach(function (dateStr) {
    var dayCases = caseHistory[dateStr] || [];

    // 篩選
    var filtered = dayCases.filter(function (c) {
      if (filterRisk && c.riskLevel !== filterRisk) return false;
      if (filterStatus && c.status !== filterStatus) return false;
      if (filterKeyword &&
        !(String(c.address || '').toLowerCase().includes(filterKeyword) ||
          String(c.type || '').toLowerCase().includes(filterKeyword) ||
          String(c.code || '').toLowerCase().includes(filterKeyword))) return false;
      return true;
    });

    if (filtered.length === 0) return;
    totalCount += filtered.length;

    // 日期標題
    var dayHigh = filtered.filter(function (c) { return c.riskLevel === 'High'; }).length;
    var dayMed = filtered.filter(function (c) { return c.riskLevel === 'Medium'; }).length;
    var dayLow = filtered.filter(function (c) { return c.riskLevel === 'Low'; }).length;

    html += '<div class="history-day-group">' +
      '<div class="history-day-header">' +
      '<span class="history-day-date">' + dateStr + '</span>' +
      '<div class="history-day-badges">' +
      (dayHigh ? '<span class="hdb danger">' + dayHigh + ' 高</span>' : '') +
      (dayMed ? '<span class="hdb warn">' + dayMed + ' 中</span>' : '') +
      (dayLow ? '<span class="hdb safe">' + dayLow + ' 低</span>' : '') +
      '<span class="hdb neutral">共 ' + filtered.length + ' 件</span>' +
      '</div>' +
      '</div>' +
      '<div class="history-table-wrap"><table class="history-table">' +
      '<thead><tr>' +
      '<th>編號</th><th>類型</th><th>風險</th><th>地點</th>' +
      '<th>狀態</th><th>建立時間</th><th>操作</th>' +
      '</tr></thead><tbody>';

    // 新→舊排序
    filtered.slice().sort(function (a, b) {
      return new Date(b.createdAt) - new Date(a.createdAt);
    }).forEach(function (c) {
      var rCls = c.riskLevel === 'High' ? 'danger' : c.riskLevel === 'Medium' ? 'warn' : 'safe';
      var rText = c.riskLevel === 'High' ? '高風險' : c.riskLevel === 'Medium' ? '中風險' : '低風險';
      var sBadge = c.status === '誤報' ? '<span class="case-status-badge misreport">誤報</span>' :
        c.status === '已處理' ? '<span class="case-status-badge handled">已處理</span>' :
          c.status === '已轉人工' ? '<span class="case-status-badge transferred">已轉人工</span>' :
            c.status;
      var addr = String(c.address || '');
      var addrShort = addr.length > 22 ? addr.slice(0, 22) + '…' : addr;
      var createdStr = c.createdAt
        ? (typeof c.createdAt === 'string'
          ? new Date(c.createdAt).toLocaleString('zh-TW')
          : c.createdAt.toLocaleString('zh-TW'))
        : '—';

      html += '<tr class="history-row" onclick="jumpToCase(\'' + c.id + '\')" title="點擊跳至警員操作查看">' +
        '<td><span class="case-code" style="font-size:12px;">' + c.code + '</span></td>' +
        '<td>' + c.type + '</td>' +
        '<td><span class="risk-badge ' + rCls + '" style="font-size:11px;">' + rText + '</span></td>' +
        '<td title="' + addr + '">' + addrShort + '</td>' +
        '<td>' + sBadge + '</td>' +
        '<td style="white-space:nowrap;font-size:12px;">' + createdStr + '</td>' +
        '<td><button class="officer-btn safe" style="padding:3px 8px;font-size:11px;" ' +
        'onclick="event.stopPropagation();jumpToCase(\'' + c.id + '\')">查看</button></td>' +
        '</tr>';
    });

    html += '</tbody></table></div></div>';
  });

  if (html === '') {
    html = '<div style="text-align:center;padding:48px;color:var(--text-dim);">' +
      (filterDate ? filterDate + ' 無案件紀錄' : '尚無歷史案件') + '</div>';
  }

  groups.innerHTML = html;
  if (countEl) countEl.textContent = totalCount > 0 ? '共 ' + totalCount + ' 筆' : '';
}

function jumpToCase(id) {
  switchPage('officer');
  setTimeout(function () {
    if (typeof renderDetail === 'function') renderDetail(id);
  }, 80);
}

function clearHistoryFilters() {
  ['filterDate', 'filterRisk', 'filterStatus', 'filterKeyword'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.value = '';
  });
  renderHistory();
}

// ====================================================
// 與 main.js loadCases 整合：每次拉到新資料後同步
// ====================================================
// 攔截 setupMapDots，在頁面一時也更新今日地圖
var _origSetupMapDots = null;
document.addEventListener('DOMContentLoaded', function () {
  // 初始化今日地圖（預設頁面）
  initTodayMap();
  // 等地圖 tile 稍微載入後再渲染點（cases 此時可能還是空的，loadCases 完成後會再呼叫一次）
  setTimeout(function () {
    if (todayMap) todayMap.invalidateSize();
    renderTodayMapDots();
    updateMapStats();
  }, 300);

  // 設定凌晨自動存檔
  scheduleAutoSnapshot();

  // 設定今日篩選預設值
  var dateInput = document.getElementById('filterDate');
  if (dateInput) dateInput.value = todayKey();

  // 每 3.5 秒同步今日地圖點
  setInterval(function () {
    if (currentPage === 'map') {
      renderTodayMapDots();
      updateMapStats();
    }
    // 也順便更新快照（確保資料即時）
    saveTodaySnapshot();
  }, 3500);
});