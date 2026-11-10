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
    // The site-wide Referrer-Policy is same-origin, which OSM's tile servers refuse (no Referer); the tile <img> overrides it.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      referrerPolicy: 'strict-origin-when-cross-origin',
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    }).addTo(map);
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
        li.textContent += ' · ' + T('pos.noneyet');
      }
      list.appendChild(li);
    }
    data.gps.forEach(function (g) {
      var layer = null;
      if (g.lat !== null && g.lon !== null) {
        layer = L.marker([g.lat, g.lon]).bindPopup(popup('gps51', g, [
          T('pop.last', { v: g.update_time || '-' }), T('pop.speed', { v: fmt(g.speed_kmh, ' km/h') }),
          T('pop.odo', { v: fmt(g.total_distance_km, ' km') }),
          T('pop.moving', { v: g.moving === true ? T('yes') : g.moving === false ? T('no') : '-' })]));
        if (g.track.length >= 2) {
          var line = L.polyline(g.track, { color: '#1565c0', weight: 3 }).addTo(map);
          layers.push(line);
        }
      }
      addItem(g, 'GPS', layer);
    });
    data.manholes.forEach(function (m) {
      var layer = L.circleMarker([m.lat, m.lon], { radius: 7 }).bindPopup(popup('dingtek', m, [
        T('pop.last', { v: m.last_ts || '-' }), T('pop.volt', { v: fmt(m.volt, ' V') }),
        T('pop.temp', { v: fmt(m.temperature, '') })]));
      addItem(m, T('pop.manhole'), layer);
    });
    if (layers.length) {
      map.fitBounds(L.featureGroup(layers).getBounds(), { padding: [20, 20], maxZoom: 16 });
    } else {
      map.setView([48.8566, 2.3522], 11);
      say(T('pos.none'));
    }
  }

  getJson('/dashboard/data/map' + (days === '7' ? '?days=7' : '')).then(function (data) {
    if (data) { draw(data); }
  }).catch(function (err) {
    console.error('map page load failed', err);
    say(T('load.failed'));
  });
})();
