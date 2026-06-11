'use strict';

// ============================================================
// police_map.js — 警察局所地圖整合
// 依賴：POLICE_STATIONS, BUREAU_JURISDICTION（police_data.js）
//        TOWN_DATA（town_data.js）、todayMap（pages.js）
// ============================================================

var _policeMarkers      = {};
var _jurisdictionLyr    = null;
var _jurisdictionLabels = [];   // 管轄鄉鎮標籤 markers
var _currentPoliceCty   = null;

// 以數字索引存儲分局資料（避免中文 ID 問題）
var _bureauIndex = [];  // [ { name, bureau, stations, districts }, ... ]

// ── 地名標準化 ────────────────────────────────────────────
function _pNorm(s) {
  return String(s || '').replace(/台(北|南|中|東|灣)/g, '臺$1');
}
// 鄉鎮名稱正規化：統一 洲↔州 字元不一致
function _normTown(s) {
  return String(s || '').replace(/洲/g, '州');
}

// ============================================================
// Marker 圖示
// ============================================================
function _policeIcon(type) {
  if (type === '局') {
    return L.divIcon({
      className: '',
      html: '<div style="width:24px;height:24px;border-radius:5px;background:#7c3aed;' +
        'border:2.5px solid rgba(255,255,255,0.9);box-shadow:0 0 10px #7c3aed;' +
        'display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;font-weight:700;">局</div>',
      iconSize: [24, 24], iconAnchor: [12, 12], popupAnchor: [0, -16]
    });
  }
  if (type === '分局') {
    return L.divIcon({
      className: '',
      html: '<div style="width:22px;height:22px;border-radius:5px;background:#1e40af;' +
        'border:2.5px solid rgba(255,255,255,0.9);box-shadow:0 0 10px #1e40af;' +
        'display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;font-weight:700;">分</div>',
      iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -14]
    });
  }
  return L.divIcon({
    className: '',
    html: '<div style="width:13px;height:13px;border-radius:3px;background:#3b82f6;' +
      'border:2px solid rgba(255,255,255,0.9);box-shadow:0 0 5px rgba(59,130,246,0.7);"></div>',
    iconSize: [13, 13], iconAnchor: [6, 6], popupAnchor: [0, -10]
  });
}

// ============================================================
// Markers
// ============================================================
function _showPoliceMarkers(county) {
  _removePoliceMarkers();
  if (!todayMap || typeof POLICE_STATIONS === 'undefined') return;

  POLICE_STATIONS.filter(function (s) {
    return _pNorm(s.county) === _pNorm(county) && s.lat && s.lng;
  }).forEach(function (s, i) {
    var zOff = s.type === '局' ? -100 : s.type === '分局' ? -200 : -400;
    var m = L.marker([s.lat, s.lng], { icon: _policeIcon(s.type), zIndexOffset: zOff });
    m.on('click', function (e) {
      L.DomEvent.stopPropagation(e);
      _showPoliceCard(s);
      if (s.type === '分局') {
        _drawJurisdiction(county, s.name);
        _highlightBureau(s.name);
      }
    });
    m.addTo(todayMap);
    _policeMarkers[i] = m;
  });
}

function _removePoliceMarkers() {
  Object.keys(_policeMarkers).forEach(function (k) {
    if (todayMap) todayMap.removeLayer(_policeMarkers[k]);
  });
  _policeMarkers = {};
}

// ============================================================
// 管轄鄉鎮高亮
// ============================================================
function _drawJurisdiction(county, bureauNameOrDistricts) {
  _clearJurisdiction();
  if (typeof BUREAU_JURISDICTION === 'undefined' || typeof TOWN_DATA === 'undefined') return;

  var districts = Array.isArray(bureauNameOrDistricts)
    ? bureauNameOrDistricts
    : (((BUREAU_JURISDICTION[county] || {})[bureauNameOrDistricts]) || []);
  if (!districts.length) return;

  var feats = TOWN_DATA.features.filter(function (f) {
    if (_pNorm(f.properties.COUNTYNAME) !== _pNorm(county)) return false;
    // _normTown：統一 洲↔州、有無行政字尾（區/鎮/鄉/市）的不一致
    var t = _normTown(f.properties.TOWNNAME || '');
    return districts.some(function (d) {
      var dd = _normTown(d);
      return t === dd || t.includes(dd) || dd.includes(t);
    });
  });
  if (!feats.length) return;

  _jurisdictionLyr = L.geoJSON(
    { type: 'FeatureCollection', features: feats },
    {
      style: function () {
        return { fill: true, fillColor: '#fbbf24', fillOpacity: 0.28,
          color: '#f59e0b', weight: 2.5, opacity: 1, dashArray: '6,4' };
      }
    }
  ).addTo(todayMap);

  // 標籤：取每個鄉鎮最大多邊形的中心，避免 MultiPolygon 離島偏移
  feats.forEach(function (f) {
    var pos = _mainPolyCenter(f.geometry);
    if (!pos || !todayMap) return;
    var m = L.marker([pos.lat, pos.lng], {
      icon: L.divIcon({
        className: 'jurisdiction-label',
        html: f.properties.TOWNNAME,
        iconSize: null
      }),
      interactive: false,
      zIndexOffset: 500
    }).addTo(todayMap);
    _jurisdictionLabels.push(m);
  });

  var b = _jurisdictionLyr.getBounds();
  if (b.isValid()) todayMap.flyToBounds(b, { padding: [60, 60], duration: 0.7, maxZoom: 12 });
}

function _clearJurisdiction() {
  if (_jurisdictionLyr && todayMap) { todayMap.removeLayer(_jurisdictionLyr); _jurisdictionLyr = null; }
  _jurisdictionLabels.forEach(function (m) { if (todayMap) todayMap.removeLayer(m); });
  _jurisdictionLabels = [];
}

// 取多邊形最大 ring 的 bbox 中心（避免 MultiPolygon 離島偏移標籤）
function _mainPolyCenter(geom) {
  var rings = [];
  if (geom.type === 'Polygon') {
    rings = [geom.coordinates[0]];
  } else if (geom.type === 'MultiPolygon') {
    rings = geom.coordinates.map(function (poly) { return poly[0]; });
    rings.sort(function (a, b) { return b.length - a.length; }); // 最大 ring 優先
  }
  if (!rings.length) return null;
  var r = rings[0];
  var lats = r.map(function (p) { return p[1]; });
  var lngs = r.map(function (p) { return p[0]; });
  return {
    lat: (Math.min.apply(null, lats) + Math.max.apply(null, lats)) / 2,
    lng: (Math.min.apply(null, lngs) + Math.max.apply(null, lngs)) / 2
  };
}

// ============================================================
// 右側資訊卡
// ============================================================
function _showPoliceCard(s) {
  var card = document.getElementById('mapInfoCard');
  var body = document.getElementById('mapInfoBody');
  if (!card || !body) return;

  var typeColor = s.type === '局' ? '#7c3aed' : s.type === '分局' ? '#1e40af' : '#3b82f6';
  body.innerHTML =
    '<div style="height:4px;background:' + typeColor + ';border-radius:4px 4px 0 0;margin:-16px -16px 14px;"></div>' +
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">' +
      '<span style="padding:3px 10px;border-radius:20px;background:' + typeColor + ';color:#fff;font-size:11px;font-weight:700;">' + s.type + '</span>' +
      '<span style="font-size:15px;font-weight:700;color:var(--text);">' + s.name + '</span>' +
    '</div>' +
    '<div class="mc-row" style="align-items:flex-start;">' +
      '<span class="mc-label">地址</span>' +
      '<span style="flex:1;font-size:12px;word-break:break-all;">' + (s.address || '—') + '</span>' +
    '</div>' +
    '<div class="mc-row"><span class="mc-label">電話</span>' +
      '<span style="font-size:12px;">' + (s.phone || '—') + '</span>' +
    '</div>' +
    (s.type === '分局'
      ? '<div style="margin-top:10px;padding:6px 10px;background:rgba(251,191,36,0.12);border-radius:6px;font-size:11px;color:#fbbf24;">▣ 已標示管轄鄉鎮範圍</div>'
      : '');
  card.classList.remove('hidden');
}

// ============================================================
// 分局高亮（左側面板）
// ============================================================
function _highlightBureau(bureauName) {
  document.querySelectorAll('.pp-bureau-hd').forEach(function (el) {
    el.classList.remove('pp-active');
  });
  document.querySelectorAll('.pp-bureau-hd[data-bname]').forEach(function (el) {
    if (el.dataset.bname === bureauName) el.classList.add('pp-active');
  });
}

// ============================================================
// 建構分局分組（bureau index）
// ============================================================
function _buildBureauIndex(county) {
  _bureauIndex = [];
  if (typeof POLICE_STATIONS === 'undefined') return;

  var all    = POLICE_STATIONS.filter(function (s) { return _pNorm(s.county) === _pNorm(county); });
  var jurMap = typeof BUREAU_JURISDICTION !== 'undefined' ? (BUREAU_JURISDICTION[county] || {}) : {};

  var bureauSt = all.filter(function (s) { return s.type === '分局'; });

  // groups: 依 jurMap 順序建立
  var groups = {};
  Object.keys(jurMap).forEach(function (bn) {
    groups[bn] = {
      name:      bn,
      bureau:    bureauSt.find(function (b) { return b.name === bn; }) || null,
      stations:  [],
      districts: jurMap[bn] || []
    };
  });
  // jurMap 以外的分局
  bureauSt.forEach(function (b) {
    if (!groups[b.name]) {
      groups[b.name] = { name: b.name, bureau: b, stations: [], districts: [] };
    }
  });

  // 指派派出所到分局
  // 優先順序：① STATION_BUREAU_MAP 明確映射 → ② 地址-鄉鎮匹配（唯一）→ ③ 最近分局（多局共用）
  var explicitMap = (typeof STATION_BUREAU_MAP !== 'undefined')
    ? (STATION_BUREAU_MAP[county] || {}) : {};

  all.forEach(function (s) {
    if (s.type === '局' || s.type === '分局') return;

    // ① 明確映射
    var explicit = explicitMap[s.name];
    if (explicit && groups[explicit]) {
      groups[explicit].stations.push(s);
      return;
    }

    // ② 地址-鄉鎮匹配
    var normAddr = _normTown(s.address || '');
    var matchBureaus = Object.keys(jurMap).filter(function (bn) {
      if (!groups[bn]) return false;
      return (jurMap[bn] || []).some(function (d) {
        return normAddr.includes(_normTown(d));
      });
    });

    if (!matchBureaus.length) {
      if (!groups['_other']) groups['_other'] = { name: '_other', bureau: null, stations: [], districts: [] };
      groups['_other'].stations.push(s);
      return;
    }

    var targetBureau = matchBureaus[0];
    // ③ 多局共用 → 取最近分局
    if (matchBureaus.length > 1 && s.lat && s.lng) {
      var bestDist = Infinity;
      matchBureaus.forEach(function (bn) {
        var b = groups[bn].bureau;
        if (b && b.lat && b.lng) {
          var d = (s.lat - b.lat) * (s.lat - b.lat) + (s.lng - b.lng) * (s.lng - b.lng);
          if (d < bestDist) { bestDist = d; targetBureau = bn; }
        }
      });
    }
    groups[targetBureau].stations.push(s);
  });

  // ── 合併共用管轄鄉鎮的分局 ──────────────────────────────
  // Step 1: 找出哪些 district 被多個分局管轄
  var distToBureaus = {};
  Object.keys(jurMap).forEach(function (bn) {
    (jurMap[bn] || []).forEach(function (d) {
      var nd = _normTown(d);
      if (!distToBureaus[nd]) distToBureaus[nd] = [];
      if (distToBureaus[nd].indexOf(bn) < 0) distToBureaus[nd].push(bn);
    });
  });

  // Step 2: union-find 建立合併群組
  var mergeGroupsArr = [];
  Object.keys(distToBureaus).forEach(function (nd) {
    var bns = distToBureaus[nd];
    if (bns.length <= 1) return;
    var found = null;
    for (var i = 0; i < mergeGroupsArr.length; i++) {
      if (bns.some(function (b) { return mergeGroupsArr[i].indexOf(b) >= 0; })) {
        found = mergeGroupsArr[i]; break;
      }
    }
    if (found) {
      bns.forEach(function (b) { if (found.indexOf(b) < 0) found.push(b); });
    } else {
      mergeGroupsArr.push(bns.slice());
    }
  });

  // Step 3: 依 groups 原始順序建立 _bureauIndex，合併組放在最先出現位置
  var allGroupKeys = Object.keys(groups).filter(function (k) { return k !== '_other'; });
  var processed = {};

  allGroupKeys.forEach(function (bn) {
    if (processed[bn]) return;

    var mg = null;
    for (var i = 0; i < mergeGroupsArr.length; i++) {
      if (mergeGroupsArr[i].indexOf(bn) >= 0) { mg = mergeGroupsArr[i]; break; }
    }

    if (!mg) {
      _bureauIndex.push(groups[bn]);
      processed[bn] = true;
    } else {
      var orderedMg = mg.filter(function (b) { return groups[b]; })
                        .sort(function (a, b) { return allGroupKeys.indexOf(a) - allGroupKeys.indexOf(b); });
      var mergedName       = orderedMg.join('與');
      var mergedDistricts  = [];
      var mergedBureauList = [];
      var mergedStations   = [];

      orderedMg.forEach(function (b) {
        var g = groups[b];
        mergedBureauList.push({ name: b, bureau: g.bureau });
        g.districts.forEach(function (d) {
          if (mergedDistricts.indexOf(d) < 0) mergedDistricts.push(d);
        });
        g.stations.forEach(function (s) {
          mergedStations.push(Object.assign({}, s, { _bureau: b }));
        });
        processed[b] = true;
      });

      _bureauIndex.push({
        name:        mergedName,
        bureau:      mergedBureauList[0].bureau,
        bureauList:  mergedBureauList,
        stations:    mergedStations,
        districts:   mergedDistricts,
        merged:      true
      });
    }
  });

  if (groups['_other']) _bureauIndex.push(groups['_other']);
}

// ============================================================
// 建構面板 HTML（分局預設收合）
// ============================================================
function _buildPanelHTML(county) {
  if (typeof POLICE_STATIONS === 'undefined') {
    return '<div class="pp-empty">資料未載入</div>';
  }

  var all  = POLICE_STATIONS.filter(function (s) { return _pNorm(s.county) === _pNorm(county); });
  var hqs  = all.filter(function (s) { return s.type === '局'; });
  var html = '';

  // 1. 警察局（總局）
  hqs.forEach(function (s) {
    html += '<div class="pp-hq-item" data-stype="hq" data-sname="' + _esc(s.name) + '">' +
      '<span class="pp-badge pp-hq">局</span>' +
      '<span class="pp-name">' + s.name + '</span>' +
      '</div>';
  });

  // 2. 分局群組（以 _bureauIndex 的數字索引為 id）
  _bureauIndex.forEach(function (g, idx) {
    if (g.name === '_other') return;
    var gid   = 'ppg_' + idx;
    var hint  = g.districts.join('、');
    var hasSub = g.stations.length > 0;

    // 合併組：各分局名稱分行顯示；單一組：直接顯示名稱
    var nameHtml = (g.merged && g.bureauList)
      ? g.bureauList.map(function (bl) {
          return '<span class="pp-name">' + bl.name + '</span>';
        }).join('')
      : '<span class="pp-name">' + g.name + '</span>';

    html +=
      '<div class="pp-bureau-group">' +
        '<div class="pp-bureau-hd" data-stype="bureau" data-bidx="' + idx + '" data-bname="' + _esc(g.name) + '">' +
          '<span class="pp-badge pp-bureau">分</span>' +
          '<div class="pp-bureau-info">' +
            nameHtml +
            (hint ? '<span class="pp-hint">' + hint + '</span>' : '') +
          '</div>' +
          (hasSub
            ? '<span class="pp-chev" id="' + gid + '_c">›</span>'
            : '<span style="width:16px;flex-shrink:0;"></span>') +
        '</div>' +
        (hasSub
          ? '<div class="pp-collapse hidden" id="' + gid + '">' +
              g.stations.map(function (s) {
                var badge      = s.type === '分駐所' ? '駐' : (s.type || '?').charAt(0);
                var bureauHint = (g.merged && s._bureau)
                  ? '<span class="pp-hint">屬' + s._bureau + '</span>' : '';
                return '<div class="pp-station-item" data-stype="station" data-sname="' + _esc(s.name) + '">' +
                  '<span class="pp-badge pp-station">' + badge + '</span>' +
                  '<div class="pp-bureau-info" style="min-width:0;">' +
                    '<span class="pp-name">' + s.name + '</span>' +
                    bureauHint +
                  '</div>' +
                  '</div>';
              }).join('') +
            '</div>'
          : '') +
      '</div>';
  });

  // 3. 其他群組
  var other = _bureauIndex.find(function (g) { return g.name === '_other'; });
  if (other && other.stations.length) {
    var gid = 'ppg_other';
    html +=
      '<div class="pp-bureau-group">' +
        '<div class="pp-bureau-hd" data-stype="other-hd">' +
          '<span class="pp-badge pp-station">他</span>' +
          '<div class="pp-bureau-info"><span class="pp-name">其他單位</span></div>' +
          '<span class="pp-chev" id="' + gid + '_c">›</span>' +
        '</div>' +
        '<div class="pp-collapse hidden" id="' + gid + '">' +
          other.stations.map(function (s) {
            return '<div class="pp-station-item" data-stype="station" data-sname="' + _esc(s.name) + '">' +
              '<span class="pp-badge pp-station">' + (s.type || '?').charAt(0) + '</span>' +
              '<span class="pp-name">' + s.name + '</span>' +
              '</div>';
          }).join('') +
        '</div>' +
      '</div>';
  }

  return html || '<div class="pp-empty">無警察局所資料</div>';
}

function _esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

// ============================================================
// 展開 / 收合
// ============================================================
function _toggleCollapse(gid) {
  var el   = document.getElementById(gid);
  var chev = document.getElementById(gid + '_c');
  if (!el) return;
  var isHidden = el.classList.contains('hidden');
  el.classList.toggle('hidden', !isHidden);   // 切換
  if (chev) chev.classList.toggle('open', isHidden);  // 箭頭旋轉
}

// ============================================================
// 面板事件（DOMContentLoaded 掛載一次）
// ============================================================
function _initPolicePanelEvents() {
  var body = document.getElementById('policePanelBody');
  if (!body) return;

  body.addEventListener('click', function (e) {
    var county = _currentPoliceCty;
    if (!county) return;

    var bureauHd = e.target.closest('[data-stype="bureau"]');
    var otherHd  = e.target.closest('[data-stype="other-hd"]');
    var hqItem   = e.target.closest('[data-stype="hq"]');
    var stItem   = e.target.closest('[data-stype="station"]');

    if (bureauHd) {
      var idx = parseInt(bureauHd.dataset.bidx, 10);
      var g   = _bureauIndex[idx];
      if (!g) return;
      _toggleCollapse('ppg_' + idx);
      // 合併分局傳入 districts 陣列，單一分局傳入名稱讓 _drawJurisdiction 查找
      _drawJurisdiction(county, g.merged ? g.districts : g.name);
      _highlightBureau(g.name);
      if (g.merged) {
        if (g.bureauList && g.bureauList[0] && g.bureauList[0].bureau) {
          _showPoliceCard(g.bureauList[0].bureau);
        }
      } else {
        if (g.bureau) _showPoliceCard(g.bureau);
      }
      return;
    }

    if (otherHd) { _toggleCollapse('ppg_other'); return; }

    if (hqItem) {
      var s = _findStation(county, hqItem.dataset.sname);
      if (s) {
        _showPoliceCard(s);
        if (s.lat && s.lng && todayMap) todayMap.flyTo([s.lat, s.lng], 14, { duration: 0.8 });
      }
      return;
    }

    if (stItem) {
      var s = _findStation(county, stItem.dataset.sname);
      if (s) {
        _showPoliceCard(s);
        if (s.lat && s.lng && todayMap) todayMap.flyTo([s.lat, s.lng], 16, { duration: 0.8 });
      }
    }
  });
}

function _findStation(county, name) {
  if (typeof POLICE_STATIONS === 'undefined') return null;
  return POLICE_STATIONS.find(function (s) {
    return _pNorm(s.county) === _pNorm(county) && s.name === name;
  }) || null;
}

// ============================================================
// 公開 API（由 taiwan_map.js 呼叫）
// ============================================================
function showPoliceForCounty(county) {
  _currentPoliceCty = county;
  _buildBureauIndex(county);
  _showPoliceMarkers(county);
  _showPolicePanelList(county);
}

function hidePoliceForCounty() {
  _removePoliceMarkers();
  _clearJurisdiction();
  var panel = document.getElementById('policePanel');
  if (panel) panel.classList.add('hidden');
  _currentPoliceCty = null;
  _bureauIndex = [];
}

function hidePolicePanel() { hidePoliceForCounty(); }

function _showPolicePanelList(county) {
  var panel   = document.getElementById('policePanel');
  var titleEl = document.getElementById('policePanelTitle');
  var body    = document.getElementById('policePanelBody');
  if (!panel) return;
  if (titleEl) titleEl.textContent = county + '　警察局所';
  if (body)    body.innerHTML = _buildPanelHTML(county);
  panel.classList.remove('hidden');
}

// ============================================================
// 初始化
// ============================================================
document.addEventListener('DOMContentLoaded', function () {
  _initPolicePanelEvents();
});
