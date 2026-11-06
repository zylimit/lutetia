(function () {
  'use strict';
  var root = document.getElementById('device');
  if (!root) { return; }
  var kind = root.dataset.kind, devId = root.dataset.deviceId, days = root.dataset.days;
  var note = document.getElementById('chart-note');

  function say(text) { if (note) { note.textContent = text; } }

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (resp) {
      if (resp.status === 401) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        return null;
      }
      if (!resp.ok) { throw new Error('http ' + resp.status); }
      return resp.json();
    });
  }

  function label(iso) { return iso.slice(5, 10) + ' ' + iso.slice(11, 16); }

  function drawCharts(data) {
    var colors = { volt: '#1565c0', temperature: '#c62828', rsrp: '#2e7d32' };
    Object.keys(colors).forEach(function (key) {
      var canvas = document.getElementById('chart-' + key);
      if (!canvas) { return; }
      var pts = data.series[key] || [];
      new Chart(canvas, {
        type: 'line',
        data: {
          labels: pts.map(function (p) { return label(p[0]); }),
          datasets: [{ label: key, data: pts.map(function (p) { return p[1]; }), borderColor: colors[key],
            borderWidth: 1.5, pointRadius: 0, spanGaps: true }]
        },
        options: { animation: false, maintainAspectRatio: false, plugins: { legend: { display: false } },
          scales: { x: { ticks: { maxTicksLimit: 8 } } } }
      });
    });
    var msg = data.hourly ? '30 天按小时平均' : '';
    if (data.truncated) { msg += (msg ? '；' : '') + '仅显示最新 1500 点'; }
    say(msg);
  }

  function drawMap(data) {
    var map = L.map('map');
    L.Icon.Default.imagePath = '/static/vendor/images/';
    L.tileLayer('https://mt{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
      { subdomains: '0123', attribution: '© Google', maxZoom: 20 }).addTo(map);
    var pos = data.positions;
    if (!pos.length) {
      say('暂无位置');
      map.setView([48.8566, 2.3522], 11);
      return;
    }
    var latest = pos[0];
    var tip = document.createElement('div');  // bindPopup(string) would parse HTML; pass a node
    tip.textContent = latest.update_time + ' · ' + latest.speed_kmh + ' km/h';
    L.marker([latest.lat, latest.lon]).addTo(map).bindPopup(tip);
    if (pos.length >= 2) {
      var line = L.polyline(pos.map(function (p) { return [p.lat, p.lon]; }), { color: '#1565c0', weight: 3 }).addTo(map);
      map.fitBounds(line.getBounds());
    } else {
      map.setView([latest.lat, latest.lon], 15);
    }
  }

  var url;
  if (kind === 'dingtek') {
    url = '/dashboard/data/telemetry?device_id=' + encodeURIComponent(devId) + '&keys=volt,temperature,rsrp&days=' + encodeURIComponent(days);
  } else {
    url = '/dashboard/data/positions?device_id=' + encodeURIComponent(devId) + '&days=30';
  }
  getJson(url).then(function (data) {
    if (!data) { return; }
    if (kind === 'dingtek') { drawCharts(data); } else { drawMap(data); }
  }).catch(function (err) {
    console.error('device page load failed', err);
    say('加载失败');
  });
})();
