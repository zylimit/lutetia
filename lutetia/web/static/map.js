(function () {
  'use strict';
  var mapEl = document.getElementById('map');
  if (!mapEl) { return; }
  var days = mapEl.dataset.days;
  var note = document.getElementById('map-note');
  var list = document.getElementById('device-list');

  function say(text) { if (note) { note.textContent = text; } }

  function el(tag, text) {
    var e = document.createElement(tag);
    if (text !== undefined) { e.textContent = text; }
    return e;
  }

  function fmt(v, unit) { return v === null || v === undefined ? '-' : v + unit; }

  function popup(source, item, lines) {
    var box = el('div');
    var link = el('a', item.name);
    link.href = '/dashboard/device/' + source + '/' + encodeURIComponent(item.device_id);
    box.appendChild(el('strong')).appendChild(link);
    lines.forEach(function (t) { box.appendChild(el('div', t)); });
    return box;
  }

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (resp) {
      if (resp.status === 401) { location.href = '/login'; return null; }
      if (!resp.ok) { throw new Error('http ' + resp.status); }
      return resp.json();
    });
  }

  function draw(data) {
    var map = L.map('map');
    L.Icon.Default.imagePath = '/static/vendor/images/';
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { attribution: '© OpenStreetMap contributors', maxZoom: 19 }).addTo(map);
    var layers = [];
    function addItem(item, kindName, layer) {
      var li = el('li', item.name + ' · ' + kindName + ' · ' + (item.update_time || item.last_ts || '-'));
      if (layer) {
        layer.addTo(map);
        layers.push(layer);
        li.addEventListener('click', function () {
          map.setView([item.lat, item.lon], 16);
          layer.openPopup();
        });
      } else {
        li.className = 'nopos';
        li.textContent += ' · 暂无位置';
      }
      list.appendChild(li);
    }
    data.gps.forEach(function (g) {
      var layer = null;
      if (g.lat !== null && g.lon !== null) {
        layer = L.marker([g.lat, g.lon]).bindPopup(popup('gps51', g, [
          '最后时间 ' + (g.update_time || '-'), '速度 ' + fmt(g.speed_kmh, ' km/h'),
          '里程 ' + fmt(g.total_distance_km, ' km'), '运动 ' + (g.moving === true ? '是' : g.moving === false ? '否' : '-')]));
        if (g.track.length >= 2) {
          var line = L.polyline(g.track, { color: '#1565c0', weight: 3 }).addTo(map);
          layers.push(line);
        }
      }
      addItem(g, 'GPS', layer);
    });
    data.manholes.forEach(function (m) {
      var layer = L.circleMarker([m.lat, m.lon], { radius: 7 }).bindPopup(popup('dingtek', m, [
        '最后时间 ' + (m.last_ts || '-'), '电压 ' + fmt(m.volt, ' V'), '温度 ' + fmt(m.temperature, '')]));
      addItem(m, '井盖', layer);
    });
    if (layers.length) {
      map.fitBounds(L.featureGroup(layers).getBounds(), { padding: [20, 20], maxZoom: 16 });
    } else {
      map.setView([48.8566, 2.3522], 11);
      say('暂无位置');
    }
  }

  getJson('/dashboard/data/map' + (days === '7' ? '?days=7' : '')).then(function (data) {
    if (data) { draw(data); }
  }).catch(function (err) {
    console.error('map page load failed', err);
    say('加载失败');
  });
})();
