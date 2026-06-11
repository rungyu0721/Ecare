'use strict';

var countyLayer    = null;   // 22 縣市邊界（常駐）
var townLayer      = null;   // 選中縣市的鄉鎮邊界（動態）
var selectedCounty = null;   // 目前選中縣市的 properties 物件
var _mapType       = 'emap';

// ====================================================
// 樣式函式
// ====================================================
function _countyDefaultStyle() {
  return {
    fill:        true,
    fillColor:   _mapType === 'satellite' ? '#0d2a4a' : '#1a3d6e',
    fillOpacity: 0.30,
    color:       _mapType === 'satellite' ? '#5090d0' : '#1565c0',  // 深藍邊界
    weight:      1.8,
    opacity:     0.9,
    dashArray:   null
  };
}

function _countySelectedStyle() {
  return {
    fill:        true,
    fillColor:   _mapType === 'satellite' ? '#1565c0' : '#1a5fb0',
    fillOpacity: 0.60,     // 深藍填充，與未選中縣市形成明顯對比
    color:       _mapType === 'satellite' ? '#ffffff' : '#90caf9',
    weight:      2.5,
    opacity:     1,
    dashArray:   null
  };
}

function _townStyle() {
  return {
    fill:        true,
    fillColor:   _mapType === 'satellite' ? '#1565c0' : '#1a5fb0',
    fillOpacity: 0.55,
    color:       '#ffffff',
    weight:      1.5,
    opacity:     0.9,
    dashArray:   null
  };
}

// ====================================================
// 懸浮提示
// ====================================================
function _showMapTooltip(e, text) {
  var tip = document.getElementById('mapHoverTooltip');
  if (!tip || !todayMap) return;
  var pt = todayMap.latLngToContainerPoint(e.latlng);
  tip.style.left  = (pt.x + 14) + 'px';
  tip.style.top   = (pt.y - 10) + 'px';
  tip.textContent = text;
  tip.classList.remove('hidden');
}

function _hideMapTooltip() {
  var tip = document.getElementById('mapHoverTooltip');
  if (tip) tip.classList.add('hidden');
}

// ====================================================
// 移除鄉鎮圖層
// ====================================================
function _clearTownLayer() {
  if (townLayer) {
    todayMap.removeLayer(townLayer);
    townLayer = null;
  }
}

// ====================================================
// 重置縣市選取（點擊空白處）
// ====================================================
function _resetCountySelection() {
  _clearTownLayer();
  selectedCounty = null;
  // 還原縣市圖層（選取期間已移除）
  if (countyLayer && !todayMap.hasLayer(countyLayer)) {
    countyLayer.addTo(todayMap);
    countyLayer.bringToBack();
  }
  if (countyLayer) countyLayer.setStyle(_countyDefaultStyle());
  document.getElementById('countyPanel').classList.add('hidden');
  _hideMapTooltip();

  // 清除警察局所 markers 與左側面板
  if (typeof hidePoliceForCounty === 'function') hidePoliceForCounty();
}

// ====================================================
// 右側縣市面板：渲染鄉鎮列表
// ====================================================
function _renderCountyPanel(countyProps, townFeatures) {
  var countyName  = countyProps.COUNTYNAME;
  var allCases    = typeof cases !== 'undefined' ? cases : [];
  var countyCases = allCases.filter(function (c) {
    return c.address && c.address.includes(countyName);
  });

  document.getElementById('countyPanelTitle').textContent = countyName;
  var body = document.getElementById('countyPanelBody');

  body.innerHTML =
    '<div class="county-town-count">今日案件 ' + countyCases.length +
    ' 件 ／ 共 ' + townFeatures.length + ' 個鄉鎮市區</div>' +
    townFeatures.map(function (f) {
      var tName = f.properties.TOWNNAME;
      var tc = countyCases.filter(function (c) {
        return c.address && c.address.includes(tName);
      }).length;
      return '<div class="town-panel-item" data-town="' + tName + '">' +
        tName +
        (tc > 0
          ? ' <span style="color:var(--danger);font-weight:700;font-size:12px;">(' + tc + ')</span>'
          : '') +
        '</div>';
    }).join('');

  // 點擊鄉鎮項目 → 地圖飛行至該鄉鎮
  body.querySelectorAll('.town-panel-item').forEach(function (item) {
    item.addEventListener('click', function () {
      var tName = item.dataset.town;
      if (!townLayer) return;
      townLayer.eachLayer(function (lyr) {
        if (lyr.feature && lyr.feature.properties.TOWNNAME === tName) {
          todayMap.flyToBounds(lyr.getBounds(), {
            padding: [30, 30], duration: 0.6, maxZoom: 14
          });
        }
      });
    });
  });

  document.getElementById('countyPanel').classList.remove('hidden');
}

// ====================================================
// 選取縣市：高亮 + 鄉鎮圖層 + 面板 + flyTo
// ====================================================
function _selectCounty(countyProps, clickedLayer) {
  // 關閉案件資訊卡，避免右側重疊
  var infoCard = document.getElementById('mapInfoCard');
  if (infoCard) infoCard.classList.add('hidden');

  // 全部縣市回預設，只高亮選中的
  countyLayer.setStyle(_countyDefaultStyle());
  clickedLayer.setStyle(_countySelectedStyle());
  selectedCounty = countyProps;

  // 移除上一個縣市的鄉鎮圖層
  _clearTownLayer();

  // 用 COUNTYID 篩選（town_data.js 無 COUNTYNAME 欄位）
  var townFeatures = TOWN_DATA.features.filter(function (f) {
    return f.properties.COUNTYID === countyProps.COUNTYID;
  });

  if (townFeatures.length > 0) {
    // 隱藏縣市圖層，避免與鄉鎮外圍邊界重疊產生雙線
    todayMap.removeLayer(countyLayer);

    townLayer = L.geoJSON(
      { type: 'FeatureCollection', features: townFeatures },
      {
        style: _townStyle,
        onEachFeature: function (feature, lyr) {
          var tName = feature.properties.TOWNNAME;
          lyr.on('mouseover', function (e) {
            lyr.setStyle({
              fillColor:   '#d8e8f0',
              fillOpacity: 0.75,
              color:       '#ffffff',
              weight:      2.2,
              opacity:     1
            });
          });
          lyr.on('mousemove', function (e) {
            _showMapTooltip(e, countyProps.COUNTYNAME + '　' + tName);
          });
          lyr.on('mouseout', function () {
            lyr.setStyle(_townStyle());
            _hideMapTooltip();
          });
          lyr.on('click', function (e) {
            L.DomEvent.stopPropagation(e);
            todayMap.flyToBounds(lyr.getBounds(), {
              padding: [30, 30], duration: 0.6
            });
          });
        }
      }
    ).addTo(todayMap);

    townLayer.bringToBack();
  }

  // 飛行至縣市範圍（裁切離島，避免高雄市等縣市因東沙島縮太遠）
  var _raw = clickedLayer.getBounds();
  var _sw  = _raw.getSouthWest();
  var _ne  = _raw.getNorthEast();
  var _bounds = L.latLngBounds(
    [Math.max(_sw.lat, 21.5), Math.max(_sw.lng, 119.5)],
    [Math.min(_ne.lat, 26.4), Math.min(_ne.lng, 122.5)]
  );
  todayMap.flyToBounds(_bounds, { padding: [40, 40], duration: 0.8, maxZoom: 11 });

  _renderCountyPanel(countyProps, townFeatures);

  // 顯示該縣市警察局所 markers + 左側面板
  if (typeof showPoliceForCounty === 'function') {
    showPoliceForCounty(countyProps.COUNTYNAME);
  }
}

// ====================================================
// 主要初始化（由 pages.js initTodayMap 末尾呼叫）
// ====================================================
function loadCountyBoundaries() {
  if (!todayMap || countyLayer) return;
  if (typeof COUNTY_DATA === 'undefined' || typeof TOWN_DATA === 'undefined') {
    console.warn('[E-CARE] COUNTY_DATA 或 TOWN_DATA 未載入');
    return;
  }

  countyLayer = L.geoJSON(COUNTY_DATA, {
    style: _countyDefaultStyle,      // 函式型 style，L.geoJSON 建構子支援
    onEachFeature: function (feature, layer) {
      var props = feature.properties;
      var name  = props.COUNTYNAME;

      layer.on('mouseover', function () {
        if (selectedCounty) return;
        layer.setStyle({
          fillColor:   '#d8e8f0',
          fillOpacity: 0.65,
          color:       '#5090d0',
          weight:      2.5,
          opacity:     1
        });
      });

      layer.on('mousemove', function (e) {
        if (selectedCounty) return;
        _showMapTooltip(e, name);
      });

      layer.on('mouseout', function () {
        _hideMapTooltip();
        if (!selectedCounty || selectedCounty.COUNTYID !== props.COUNTYID) {
          layer.setStyle(_countyDefaultStyle());
        }
      });

      layer.on('click', function (e) {
        L.DomEvent.stopPropagation(e);
        _selectCounty(props, layer);
      });
    }
  }).addTo(todayMap);

  countyLayer.bringToBack();

  // 點擊地圖空白處 → 重置縣市選取 + 關閉資訊卡
  todayMap.on('click', function () {
    if (selectedCounty) _resetCountySelection();
    var infoCard = document.getElementById('mapInfoCard');
    if (infoCard) infoCard.classList.add('hidden');
  });

  // 地圖移動時（flyToBounds / 拖曳）強制清除懸浮 tooltip
  // 避免 mouseout 因地圖動畫未觸發而導致 tooltip 卡住
  todayMap.on('movestart', function () {
    _hideMapTooltip();
  });
}

// ====================================================
// 底圖切換（由 pages.js switchMapType 末尾呼叫）
// ====================================================
function updateBoundaryStyle(mapType) {
  _mapType = mapType;
  if (countyLayer) {
    countyLayer.eachLayer(function (lyr) {
      var isSelected = selectedCounty &&
        lyr.feature && lyr.feature.properties.COUNTYID === selectedCounty.COUNTYID;
      lyr.setStyle(isSelected ? _countySelectedStyle() : _countyDefaultStyle());
    });
  }
  if (townLayer) townLayer.setStyle(_townStyle());
}

// ====================================================
// 關閉縣市面板（HTML 關閉按鈕 onclick 呼叫）
// ====================================================
function closeCountyPanel() {
  _resetCountySelection();
}
