(function () {
  'use strict';
  var REFRESH_MS = 60000;
  var DEVICE_LABELS = ['source', 'device_id', '名字', '类型', '应在线', '最后入库', '距今', '状态'];
  var SENSOR_LABELS = ['名字', 'device_id', 'volt (V)', 'temperature', 'rsrp (dBm)', '时间'];

  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function fmtTs(iso) {
    if (!iso) { return '-'; }
    var d = new Date(iso);
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' +
      pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds()) + ' UTC';
  }
  function fmtAgo(iso, now) {
    if (!iso) { return '-'; }
    var min = Math.max(0, Math.floor((now - new Date(iso)) / 60000));
    if (min < 60) { return min + ' 分钟'; }
    if (min < 1440) { return Math.floor(min / 60) + ' 小时'; }
    return Math.floor(min / 1440) + ' 天';
  }
  function fmtSecs(sec) { return fmtAgo(new Date(Date.now() - sec * 1000).toISOString(), Date.now()); }
  function cell(v) { return v === null || v === undefined ? '' : String(v); }

  function deviceHref(source, id) {
    return '/dashboard/device/' + encodeURIComponent(source) + '/' + encodeURIComponent(id);
  }

  // hrefs: optional { columnIndex: function(rowIndex) -> url } rendering that cell as a link
  function fill(id, rows, classes, labels, hrefs) {
    var tbody = document.getElementById(id);
    if (!tbody) { return; }
    while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }
    rows.forEach(function (cells, i) {
      var tr = document.createElement('tr');
      if (classes && classes[i]) { tr.className = classes[i]; }
      cells.forEach(function (c, j) {
        var td = document.createElement('td');
        if (labels) { td.dataset.label = labels[j] || ''; }
        if (hrefs && hrefs[j]) {
          var a = document.createElement('a');
          a.href = hrefs[j](i);
          a.textContent = cell(c);
          td.appendChild(a);
        } else {
          td.textContent = cell(c);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  var KIND_LABELS = { collector: '采集', stale: '失联', low_volt: '低电压', alarm: '报警', push: '推送通道', backup: '备份', quota: '配额', login: '登录次数' };

  function renderAnomalies(data) {
    var box = document.getElementById('anomalies');
    if (!box) { return; }
    while (box.firstChild) { box.removeChild(box.firstChild); }
    var h = document.createElement('h2');
    h.textContent = '异常总览 · ' + data.anomaly_summary;
    box.appendChild(h);
    if (!data.anomalies.length) {
      var p = document.createElement('p');
      p.className = 'ok';
      p.textContent = '全部正常';
      box.appendChild(p);
      return;
    }
    var ul = document.createElement('ul');
    data.anomalies.forEach(function (a) {
      var li = document.createElement('li');
      li.className = a.level;
      li.textContent = '[' + (KIND_LABELS[a.kind] || a.kind) + '] ' + (a.name || '') + ' · ' + a.detail;
      ul.appendChild(li);
    });
    box.appendChild(ul);
  }

  function fmtParis(iso) {
    var parts = {};
    new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(iso)).forEach(function (p) { parts[p.type] = p.value; });
    return parts.year + '-' + parts.month + '-' + parts.day + ' ' + parts.hour + ':' + parts.minute + ' 巴黎时间';
  }

  function fmtBackup(b) {
    if (!b || !b.at) { return '上次备份：无'; }
    var size = b.bytes === null || b.bytes === undefined ? '-' : (b.bytes / 1048576).toFixed(1) + ' MB';
    return '上次备份：' + fmtParis(b.at) + ' · ' + size;
  }

  var RECEIVER_STALE_NOTE = '以下接收端计数为最后已知值（采集心跳已过期）';

  function fmtCollector(c) {
    if (!c || !c.updated_at) { return '采集从未上报心跳'; }
    var ws = c.ws_connected === null || c.ws_connected === undefined ? 'WS 未启用' : (c.ws_connected ? 'WS 已连' : 'WS 未连');
    var state = ws + ' · ' + (c.polling ? '轮询中' : '推送') + ' · v' + (c.version || '?');
    if (c.stale) { return '采集心跳已过期，最后已知（' + fmtParis(c.updated_at) + '）：' + state; }
    return '采集心跳：' + fmtParis(c.updated_at) + '（' + Math.floor(c.age_sec) + ' 秒前）· ' + state;
  }

  function render(data) {
    renderAnomalies(data);
    var lb = document.getElementById('last-backup');
    if (lb) { lb.textContent = fmtBackup(data.last_backup); }
    var now = new Date(data.generated_at).getTime();
    var online = { true: '是', false: '否' };
    fill('tbl-devices', data.devices.map(function (r) {
      return [r.source, r.device_id, r.name, r.device_type, online[r.expected_online] || '?',
        fmtTs(r.last_ts), fmtAgo(r.last_ts, now), r.stale ? 'STALE' : ''];
    }), data.devices.map(function (r) { return r.stale ? 'stale' : ''; }), DEVICE_LABELS,
      { 2: function (i) { return deviceHref(data.devices[i].source, data.devices[i].device_id); } });

    var byDev = {}, order = [];
    data.latest_sensor.forEach(function (r) {
      var d = byDev[r.device_id];
      if (!d) { d = byDev[r.device_id] = { name: r.name, id: r.device_id, ts: r.ts }; order.push(d); }
      d[r.key] = r.value_si !== null ? r.value_si : (r.value_num !== null ? r.value_num : r.value_str);
      if (r.ts > d.ts) { d.ts = r.ts; }
    });
    order.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
    fill('tbl-sensor', order.map(function (d) {
      return [d.name, d.id, d.volt, d.temperature, d.rsrp, fmtTs(d.ts)];
    }), null, SENSOR_LABELS, { 0: function (i) { return deviceHref('dingtek', order[i].id); } });

    fill('tbl-gps', data.latest_gps.map(function (r) {
      return [r.name, r.device_id, fmtTs(r.update_time), r.lat, r.lon, r.speed_kmh, r.origin];
    }), null, null, { 0: function (i) { return deviceHref('gps51', data.latest_gps[i].device_id); } });

    var cl = document.getElementById('collector-line');
    if (cl) { cl.textContent = fmtCollector(data.collector); }
    var rn = document.getElementById('receiver-note');
    if (rn) { rn.textContent = data.collector && data.collector.stale && data.receiver ? RECEIVER_STALE_NOTE : ''; }
    var rc = data.receiver;
    fill('tbl-receiver', rc ? [[rc.received, rc.stored, rc.rejected, rc.unrecognised, rc.alarms, rc.failed,
      rc.queued, fmtSecs(rc.silent_sec), fmtSecs(rc.message_silent_sec)]] : []);

    fill('tbl-calls', data.api_calls_24h.map(function (c) { return [c.source, c.action, c.n]; }));

    var stamp = document.getElementById('last-refresh');
    if (stamp) { stamp.textContent = '生成于 ' + fmtTs(data.generated_at); }
  }

  function failed() {
    var stamp = document.getElementById('last-refresh');
    if (stamp) {
      var d = new Date();
      stamp.textContent = '刷新失败 ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }
  }

  function refresh() {
    fetch('/dashboard/data/overview', { credentials: 'same-origin' }).then(function (resp) {
      if (resp.status === 401) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname);
        return null;
      }
      if (!resp.ok) { throw new Error('http ' + resp.status); }
      return resp.json();
    }).then(function (data) {
      if (data) { render(data); }
    }).catch(function (err) {
      console.error('dashboard refresh failed', err);
      failed();
    });
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
})();
