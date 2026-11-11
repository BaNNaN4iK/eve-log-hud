// Вкладка «Карта»: регион схемой (раскладка 2D-карты игры), где ваши персонажи, разведка из интел-каналов и активность.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var OVERLAYS = [['', 'без активности'], ['jumps', 'прыжки за час'], ['npc', 'убито NPC за час'], ['ships', 'убито кораблей за час'],
    ['pods', 'убито капсул за час'], ['sov', 'суверенитет']];
  var M = { d: null, loading: false, st: null, stAt: 0, region: null, follow: true, overlay: '', sel: null, key: null, view: null, ready: false };
  try {
    var sv = JSON.parse(localStorage.getItem('elw.map') || '{}');
    M.region = sv.region || null; M.follow = sv.follow !== false; M.overlay = sv.overlay || '';
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.map', JSON.stringify({ region: M.region, follow: M.follow, overlay: M.overlay })); } catch (e) { } }

  ELW.addTab({ id: 'map', title: 'Карта',
    css: '.mp-layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:12px;align-items:start}' +
      '.mp-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}.mp-bar input,.mp-bar select{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:5px 9px;font:inherit;font-size:13px}' +
      '.mp-box{position:relative;background:var(--panel2);border:1px solid var(--line);border-radius:10px;overflow:hidden;height:calc(100vh - 230px);min-height:420px;touch-action:none}' +
      '.mp-box svg{width:100%;height:100%;display:block;cursor:grab}.mp-box svg.drag{cursor:grabbing}' +
      '.mp-g{stroke:var(--muted);stroke-opacity:.55;stroke-width:1.3}.mp-g.out{stroke-dasharray:3 3;opacity:.6}' +
      '.mp-n{stroke:#0008;stroke-width:1;cursor:pointer}.mp-n.ext{opacity:.45}.mp-t{font:11px system-ui,Segoe UI,sans-serif;fill:var(--text);pointer-events:none}' +
      '.mp-t.s{font-size:9.5px}.mp-t.ext{fill:var(--muted)}.mp-t.v{font-size:10px;font-weight:700}' +
      '.mp-me{fill:none;stroke:var(--accent);stroke-width:2.5}.mp-sel{fill:none;stroke:#fff;stroke-width:1.5;stroke-dasharray:3 2}' +
      '.mp-int{fill:#e5534b;opacity:.0}.mp-int.a1{opacity:.75}.mp-int.a2{opacity:.5}.mp-int.a3{opacity:.3}.mp-int.a4{opacity:.15}.mp-clr{fill:none;stroke:var(--good);stroke-width:2}' +
      '.mp-inc{fill:none;stroke:#c86ad9;stroke-width:2;stroke-dasharray:2 2}' +
      '.mp-side{display:flex;flex-direction:column;gap:10px}.mp-side .panel{margin:0;padding:10px 12px}.mp-side h3{margin:0 0 6px;font-size:13px}' +
      '.mp-feed{max-height:calc(100vh - 470px);min-height:160px;overflow:auto;font-size:12.5px}.mp-msg{padding:5px 0;border-top:1px solid var(--line)}.mp-msg:first-child{border-top:0}' +
      '.mp-msg .m{color:var(--muted);font-size:11.5px}.mp-msg.near{background:color-mix(in srgb,var(--bad) 14%,transparent);border-radius:6px;padding:5px 6px}' +
      '.mp-sys{color:var(--accent);cursor:pointer;font-weight:600}.mp-j{display:inline-block;font-size:11px;border-radius:5px;padding:0 6px;margin-left:4px;border:1px solid currentColor}' +
      '.mp-chars div{display:flex;gap:6px;align-items:center;font-size:12.5px;padding:2px 0}.mp-legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11.5px;color:var(--muted);margin-top:6px}' +
      '.mp-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}' +
      '.mp-info{position:absolute;left:10px;bottom:10px;max-width:340px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:12.5px;box-shadow:0 6px 20px rgba(0,0,0,.35)}' +
      '.mp-info b{font-size:14px}.mp-chan{display:flex;gap:6px;align-items:center;font-size:12.5px;padding:2px 0}' +
      '@media(max-width:1000px){.mp-layout{grid-template-columns:1fr}.mp-feed{max-height:300px}}',
    html: '<div id="mpBox"></div>',
    render: function () { if (M.ready) draw(); } });

  // ----- данные -----
  function loadData() {
    if (M.loading || M.d) return;
    M.loading = true;
    api('/api/map/data').then(function (j) {
      M.loading = false;
      if (!j.ok) return;
      var d = { regions: j.regions, consts: j.constellations, sys: {}, adj: {}, byName: {}, byRegion: {} };
      Object.keys(j.systems).forEach(function (k) {
        var s = j.systems[k], id = +k, reg = (j.constellations[s[1]] || [])[1];
        d.sys[id] = { id: id, name: s[0], c: s[1], r: reg, sec: s[2], x: s[3], y: -s[4] };
        d.adj[id] = [];
        d.byName[s[0].toLowerCase()] = id;
        (d.byRegion[reg] = d.byRegion[reg] || []).push(id);
      });
      j.gates.forEach(function (g) { if (d.adj[g[0]] && d.adj[g[1]]) { d.adj[g[0]].push(g[1]); d.adj[g[1]].push(g[0]); } });
      M.d = d; M.key = null; draw();
    }, function () { M.loading = false; });
  }
  function loadState(force) {
    if (!force && Date.now() - M.stAt < 4000) return;
    M.stAt = Date.now();
    api('/api/map/state').then(function (j) {
      if (!j.ok) return;
      M.st = j;
      if (M.follow && j.chars.length && M.d) {
        var me = M.d.sys[j.chars[0].system];
        if (me && String(me.r) !== String(M.region)) { M.region = me.r; remember(); M.view = null; }
      }
      draw();
    });
  }
  // ----- отрисовка -----
  function secColor(s) {
    if (s >= 0.95) return '#2c75e1'; if (s >= 0.75) return '#399aeb'; if (s >= 0.65) return '#4ecef8'; if (s >= 0.55) return '#60daa6';
    if (s >= 0.45) return '#71e554'; if (s >= 0.35) return '#eeff83'; if (s >= 0.25) return '#de6a0c'; if (s >= 0.15) return '#ce440f';
    if (s > 0) return '#bc1113'; return '#8f2f69';
  }
  function secText(s) { return (s > 0 && s < 0.05 ? 0.1 : Math.round(s * 10) / 10).toFixed(1); }
  function hue(str) { var h = 0; for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360; return 'hsl(' + h + ',55%,52%)'; }
  function regionName(r) { return (M.d.regions[r] || r); }

  function draw() {
    var box = $('mpBox');
    if (!box) return;
    if (!M.d) { loadData(); if (!box.innerHTML) box.innerHTML = '<section class="panel"><p class="muted">Загружаю карту…</p></section>'; return; }
    loadState();
    var st = M.st;
    if (!M.region) M.region = (st && st.chars.length && M.d.sys[st.chars[0].system]) ? M.d.sys[st.chars[0].system].r : Object.keys(M.d.byRegion)[0];
    var key = JSON.stringify([M.region, M.overlay, M.follow, M.sel, st && st.version, st && st.activity_at, st && st.chars.map(function (c) { return c.name + c.system; }),
      st && st.settings, st && st.channels.length, Math.floor(Date.now() / 30000)]);
    if (key === M.key) return;
    M.key = key;
    var keepView = M.view, focus = document.activeElement && document.activeElement.id === 'mpFind';
    if (!$('mpSvg')) shell();
    drawMap();
    drawSide();
    if (keepView) applyView();
    if (focus) $('mpFind').focus();
  }
  function shell() {
    var regs = Object.keys(M.d.regions).sort(function (a, b) { return M.d.regions[a].localeCompare(M.d.regions[b]); });
    $('mpBox').innerHTML = '<div class="mp-layout"><div><div class="mp-bar">' +
      '<input id="mpFind" list="mpList" placeholder="Система или регион…" aria-label="Найти систему или регион" style="width:200px">' +
      '<datalist id="mpList">' + regs.map(function (r) { return '<option value="' + esc(M.d.regions[r]) + '">'; }).join('') + '</datalist>' +
      '<select id="mpRegion" aria-label="Регион">' + regs.map(function (r) { return '<option value="' + r + '">' + esc(M.d.regions[r]) + '</option>'; }).join('') + '</select>' +
      '<select id="mpOverlay" aria-label="Что показать на карте">' + OVERLAYS.map(function (o) { return '<option value="' + o[0] + '">' + o[1] + '</option>'; }).join('') + '</select>' +
      '<label class="small"><input type="checkbox" id="mpFollow"> за персонажем</label>' +
      '<button type="button" class="btn" id="mpFit" style="padding:4px 10px">Весь регион</button></div>' +
      '<div class="mp-box"><svg id="mpSvg" role="img" aria-label="Карта региона"></svg><div id="mpInfo" class="mp-info" hidden></div></div>' +
      '<div class="mp-legend" id="mpLegend"></div></div><div class="mp-side" id="mpSide"></div></div>';
    bindSvg();
  }
  function regionSystems() {
    var inR = M.d.byRegion[M.region] || [], set = {}, ext = {};
    inR.forEach(function (id) { set[id] = true; });
    inR.forEach(function (id) { M.d.adj[id].forEach(function (n) { if (!set[n]) ext[n] = true; }); });
    return { inR: inR, set: set, ext: Object.keys(ext).map(Number) };
  }
  function intelBySystem() {
    var out = {}, now = Date.now() / 1000;
    ((M.st && M.st.intel) || []).forEach(function (r) {
      r.systems.forEach(function (s) {
        var o = out[s];
        if (!o || r.ts > o.ts) out[s] = { ts: r.ts, clear: r.clear, age: now - r.ts, r: r };
      });
    });
    return out;
  }
  // схема региона: старт — раскладка 2D-карты игры, затем системы расталкиваются (не слипаются), врата держат соседей рядом;
  // системы соседних регионов — у края, в сторону, где они на самом деле
  var LAYOUT = {};
  function layout(R) {
    if (LAYOUT[M.region]) return LAYOUT[M.region];
    var d = M.d, ids = R.inR, pos = {}, home = {};
    var xs = ids.map(function (i) { return d.sys[i].x; }), ys = ids.map(function (i) { return d.sys[i].y; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var size = 70 * Math.sqrt(ids.length) + 200, k = size / Math.max(x1 - x0, y1 - y0, 1e-6);
    ids.forEach(function (i) { var p = [(d.sys[i].x - x0) * k, (d.sys[i].y - y0) * k]; pos[i] = p.slice(); home[i] = p; });
    var cx = (x1 - x0) * k / 2, cy = (y1 - y0) * k / 2;
    R.ext.forEach(function (e) {                                // у края: от соседа по вратам в сторону настоящего положения
      var n = d.adj[e].filter(function (x) { return pos[x] && home[x]; })[0];
      if (n === undefined) { pos[e] = [cx, cy]; return; }
      var hx = (d.sys[e].x - x0) * k, hy = (d.sys[e].y - y0) * k, dx = hx - home[n][0], dy = hy - home[n][1], l = Math.hypot(dx, dy) || 1;
      pos[e] = [home[n][0] + dx / l * 70, home[n][1] + dy / l * 70];
      home[e] = pos[e].slice();
    });
    var all = ids.concat(R.ext), edges = [];
    all.forEach(function (a) { d.adj[a].forEach(function (b) { if (a < b && pos[b]) edges.push([a, b]); }); });
    var MIN = 62, LEN = 70;
    for (var it = 0; it < 260; it++) {
      var f = {}, cool = 1 - it / 300;
      all.forEach(function (i) { f[i] = [(home[i][0] - pos[i][0]) * 0.02, (home[i][1] - pos[i][1]) * 0.02]; });
      for (var a = 0; a < all.length; a++) {
        for (var b = a + 1; b < all.length; b++) {
          var p = pos[all[a]], q = pos[all[b]], dx = p[0] - q[0], dy = p[1] - q[1], dd = Math.hypot(dx, dy) || 0.01;
          if (dd < MIN) { var push = (MIN - dd) / dd * 0.5; f[all[a]][0] += dx * push; f[all[a]][1] += dy * push; f[all[b]][0] -= dx * push; f[all[b]][1] -= dy * push; }
        }
      }
      edges.forEach(function (e) {
        var p = pos[e[0]], q = pos[e[1]], dx = q[0] - p[0], dy = q[1] - p[1], dd = Math.hypot(dx, dy) || 0.01, pull = (dd - LEN) / dd * 0.06;
        f[e[0]][0] += dx * pull; f[e[0]][1] += dy * pull; f[e[1]][0] -= dx * pull; f[e[1]][1] -= dy * pull;
      });
      all.forEach(function (i) {
        var m = Math.hypot(f[i][0], f[i][1]), lim = 12 * cool + 1;
        if (m > lim) { f[i][0] *= lim / m; f[i][1] *= lim / m; }
        pos[i][0] += f[i][0]; pos[i][1] += f[i][1];
      });
    }
    return (LAYOUT[M.region] = pos);
  }
  function drawMap() {
    var R = regionSystems(), all = R.inR.concat(R.ext), d = M.d, st = M.st || {};
    $('mpRegion').value = M.region; $('mpOverlay').value = M.overlay; $('mpFollow').checked = M.follow;
    if (!all.length) { $('mpSvg').innerHTML = ''; return; }
    var pos = layout(R);
    var xs = all.map(function (i) { return pos[i][0]; }), ys = all.map(function (i) { return pos[i][1]; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys), pad = 60;
    var P = function (i) { return [pad + pos[i][0] - x0, pad + pos[i][1] - y0]; };
    M.full = [0, 0, x1 - x0 + pad * 2 + 80, y1 - y0 + pad * 2];
    var intel = intelBySystem(), act = st.activity || {}, sov = st.sov || {}, sovN = st.sov_names || {}, inc = {};
    (st.incursions || []).forEach(function (s) { inc[s] = true; });
    var mine = {};
    (st.chars || []).forEach(function (c) { (mine[c.system] = mine[c.system] || []).push(c.name); });
    var h = '', drawn = {};
    all.forEach(function (a) {
      d.adj[a].forEach(function (b) {
        if (a > b || !(R.set[a] || R.set[b]) || (!R.set[a] && !R.set[b])) return;
        if (!(R.set[b] || R.ext.indexOf(b) >= 0)) return;
        var p = P(a), q = P(b), out = !R.set[a] || !R.set[b] || d.sys[a].c !== d.sys[b].c;
        h += '<line class="mp-g' + (!R.set[a] || !R.set[b] ? ' out' : '') + '" x1="' + p[0].toFixed(1) + '" y1="' + p[1].toFixed(1) + '" x2="' + q[0].toFixed(1) + '" y2="' + q[1].toFixed(1) + '"' +
          (out && R.set[a] && R.set[b] ? ' style="stroke:color-mix(in srgb,var(--line) 50%,var(--muted))"' : '') + '/>';
      });
    });
    var maxV = 1, vals = {};
    if (M.overlay && M.overlay !== 'sov') {
      var ix = { jumps: 0, npc: 1, ships: 2, pods: 3 }[M.overlay];
      all.forEach(function (i) { var v = (act[i] || [])[ix] || 0; vals[i] = v; if (v > maxV) maxV = v; });
    }
    all.forEach(function (i) {
      var s = d.sys[i], p = P(i), ext = !R.set[i], it = intel[i];
      if (it && it.age < 1800 && !it.clear) h += '<circle class="mp-int a' + (it.age < 120 ? 1 : it.age < 300 ? 2 : it.age < 900 ? 3 : 4) + '" cx="' + p[0] + '" cy="' + p[1] + '" r="18"/>';
      if (vals[i]) h += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="' + (6 + 16 * Math.sqrt(vals[i] / maxV)).toFixed(1) + '" fill="var(--warn)" opacity=".28"/>';
      if (M.overlay === 'sov' && sov[i]) h += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="13" fill="' + hue(String(sov[i])) + '" opacity=".35"/>';
      h += '<circle class="mp-n' + (ext ? ' ext' : '') + '" data-sys="' + i + '" cx="' + p[0] + '" cy="' + p[1] + '" r="6" fill="' + secColor(s.sec) + '"/>';
      if (it && it.clear && it.age < 1800) h += '<circle class="mp-clr" cx="' + p[0] + '" cy="' + p[1] + '" r="9"/>';
      if (inc[i]) h += '<circle class="mp-inc" cx="' + p[0] + '" cy="' + p[1] + '" r="11"/>';
      if (mine[i]) h += '<circle class="mp-me" cx="' + p[0] + '" cy="' + p[1] + '" r="12"/><text class="mp-t v" x="' + (p[0] + 14) + '" y="' + (p[1] - 10) + '" fill="var(--accent)" style="fill:var(--accent)">' + esc(mine[i].join(', ')) + '</text>';
      if (M.sel === i) h += '<circle class="mp-sel" cx="' + p[0] + '" cy="' + p[1] + '" r="15"/>';
      h += '<text class="mp-t' + (ext ? ' ext' : '') + '" x="' + (p[0] + 9) + '" y="' + (p[1] + 4) + '">' + esc(s.name) + '</text>' +
        '<text class="mp-t s" x="' + (p[0] + 9) + '" y="' + (p[1] + 15) + '" style="fill:' + secColor(s.sec) + '">' + secText(s.sec) +
        (ext ? ' · ' + esc(regionName(s.r)) : '') + (vals[i] ? ' · ' + vals[i] : '') + (M.overlay === 'sov' && sov[i] ? ' · ' + esc((sovN[sov[i]] || '').slice(0, 22)) : '') + '</text>';
    });
    $('mpSvg').innerHTML = h;
    if (!M.view) { M.view = M.full.slice(); }
    applyView();
    $('mpLegend').innerHTML = '<span><i style="background:#2c75e1"></i>хай-сек</span><span><i style="background:#de6a0c"></i>лоу-сек</span><span><i style="background:#8f2f69"></i>нули</span>' +
      '<span><i style="background:transparent;border:2px solid var(--accent)"></i>ваш персонаж</span><span><i style="background:#e5534b"></i>разведка: враги (ярче — свежее)</span>' +
      '<span><i style="background:transparent;border:2px solid var(--good)"></i>«чисто»</span><span><i style="background:transparent;border:2px dashed #c86ad9"></i>инкурсия</span>' +
      '<span>пунктир — врата в соседний регион</span>' + (M.overlay && M.overlay !== 'sov' ? '<span>жёлтый круг — ' + esc(OVERLAYS.filter(function (o) { return o[0] === M.overlay; })[0][1]) + (st.activity_at ? ', ESI ' + esc(L.fmtDateTime(st.activity_at)) : ', загружаю…') + '</span>' : '');
    drawInfo();
  }
  function applyView() { var v = M.view; $('mpSvg').setAttribute('viewBox', v.map(function (x) { return x.toFixed(1); }).join(' ')); }
  function drawInfo() {
    var box = $('mpInfo'), i = M.sel, d = M.d, st = M.st || {};
    if (!i || !d.sys[i]) { box.hidden = true; return; }
    var s = d.sys[i], a = (st.activity || {})[i] || [0, 0, 0, 0], sov = (st.sov || {})[i], reps = ((st.intel || []).filter(function (r) { return r.systems.indexOf(i) >= 0; })).slice(-4).reverse();
    var me = (st.chars || []).map(function (c) { return c.system; }), dist = jumpsFrom(me)[i];
    box.hidden = false;
    box.innerHTML = '<div style="display:flex;gap:8px;align-items:baseline"><b>' + esc(s.name) + '</b><span style="color:' + secColor(s.sec) + '">' + secText(s.sec) + '</span>' +
      '<span class="muted">' + esc(regionName(s.r)) + ' · ' + esc((d.consts[s.c] || [''])[0]) + '</span><button type="button" class="btn" data-mp-close style="margin-left:auto;padding:0 8px">✕</button></div>' +
      (dist !== undefined ? '<div>' + (dist === 0 ? 'вы здесь' : dist + ' прыжк. от вашего персонажа') + '</div>' : '') +
      '<div class="muted">за час: прыжков ' + a[0] + ' · NPC ' + a[1] + ' · кораблей ' + a[2] + ' · капсул ' + a[3] + '</div>' +
      (sov ? '<div class="muted">суверенитет: ' + esc((st.sov_names || {})[sov] || sov) + '</div>' : '') +
      (reps.length ? '<div style="margin-top:4px">' + reps.map(function (r) { return '<div><span class="muted">' + esc(L.fmtTime ? L.fmtTime(r.ts) : new Date(r.ts * 1000).toLocaleTimeString()) + '</span> ' + esc(r.who) + ': ' + esc(r.text) + '</div>'; }).join('') + '</div>' : '') +
      '<div style="margin-top:4px"><a href="https://evemaps.dotlan.net/system/' + encodeURIComponent(s.name.replace(/ /g, '_')) + '" target="_blank" rel="noopener">Dotlan</a> · ' +
      '<a href="https://zkillboard.com/system/' + i + '/" target="_blank" rel="noopener">zKillboard</a></div>';
  }
  function jumpsFrom(starts) {
    var dist = {}, fr = [];
    starts.forEach(function (s) { if (M.d.adj[s]) { dist[s] = 0; fr.push(s); } });
    for (var k = 1; k <= 40 && fr.length; k++) {
      var nx = [];
      fr.forEach(function (s) { M.d.adj[s].forEach(function (n) { if (dist[n] === undefined) { dist[n] = k; nx.push(n); } }); });
      fr = nx;
    }
    return dist;
  }
  function ago(ts) { var s = Math.max(0, Date.now() / 1000 - ts); return s < 60 ? 'только что' : s < 3600 ? Math.floor(s / 60) + ' мин' : Math.floor(s / 3600) + ' ч'; }
  function drawSide() {
    var st = M.st, d = M.d;
    if (!st) { $('mpSide').innerHTML = '<section class="panel"><p class="muted">Загружаю…</p></section>'; return; }
    var range = st.settings.range;
    var chars = '<section class="panel"><h3>Персонажи</h3><div class="mp-chars">' + (st.chars.length ? st.chars.map(function (c) {
      var s = d.sys[c.system];
      return '<div><b>' + esc(c.name) + '</b><span class="mp-sys" data-mp-go="' + c.system + '">' + esc(s ? s.name : c.system) + '</span>' +
        '<span class="muted">' + esc(s ? regionName(s.r) : '') + (c.at ? ' · ' + ago(c.at) : ' · по боевым логам') + '</span></div>';
    }).join('') : '<div class="muted">Пока неизвестно — войдите в игру: систему видно по локальному чату.</div>') + '</div>' +
      (!st.chat_ok ? '<div class="small" style="color:var(--warn)">Не найдена папка логов чата: ' + esc(st.chat_dir || '—') + '</div>' : '') + '</section>';
    var feed = st.intel.slice().reverse().slice(0, 80);
    var intel = '<section class="panel"><h3>Разведка <span class="muted small">— тревога в пределах ' + range + ' прыжк.</span></h3>' +
      (st.settings.intel.length ? '' : '<p class="small muted" style="margin:0 0 6px">Выберите интел-каналы ниже — сообщения из них появятся здесь и на карте.</p>') +
      '<div class="mp-feed">' + (feed.length ? feed.map(function (r) {
        var near = !r.clear && r.jumps !== null && r.jumps <= range;
        return '<div class="mp-msg' + (near ? ' near' : '') + '"><div class="m">' + ago(r.ts) + ' · ' + esc(r.channel) + ' · ' + esc(r.who) + '</div><div>' +
          esc(r.text).replace(/\*/g, '') + '</div>' + (r.systems.length ? '<div>' + r.systems.map(function (s) {
            return '<span class="mp-sys" data-mp-go="' + s + '">' + esc(d.sys[s] ? d.sys[s].name : s) + '</span>';
          }).join(' ') + (r.jumps !== null ? '<span class="mp-j" style="color:' + (near ? 'var(--bad)' : 'var(--muted)') + '">' + (r.jumps === 0 ? 'у вас' : r.jumps + ' прыжк.') + '</span>' : '') +
          (r.clear ? '<span class="mp-j" style="color:var(--good)">чисто</span>' : '') + '</div>' : '') + '</div>';
      }).join('') : '<div class="muted">Сообщений за 2 часа нет.</div>') + '</div></section>';
    var chans = '<section class="panel"><h3>Интел-каналы</h3><div style="max-height:200px;overflow:auto">' + (st.channels.length ? st.channels.map(function (c) {
      return '<label class="mp-chan"><input type="checkbox" data-mp-chan="' + esc(c.name) + '"' + (c.intel ? ' checked' : '') + '> ' + esc(c.name) + ' <span class="muted small">' + ago(c.at) + '</span></label>';
    }).join('') : '<div class="muted small">Каналы появятся, когда игра запишет логи чата (настройка игры «Вести журнал чата» включена по умолчанию).</div>') + '</div>' +
      '<div class="mp-bar" style="margin:8px 0 0"><label class="small">Тревога в пределах <input type="number" id="mpRange" min="0" max="30" value="' + range + '" style="width:60px"> прыжк.</label>' +
      '<label class="small"><input type="checkbox" id="mpSound"' + (st.settings.sound ? ' checked' : '') + '> звук</label></div>' +
      '<div class="mp-bar" style="margin:6px 0 0"><select id="mpSoundKind" aria-label="Какой звук">' + Object.keys(st.sounds || {}).map(function (k) {
        return '<option value="' + k + '"' + (st.settings.sound_kind === k ? ' selected' : '') + '>' + esc(st.sounds[k]) + '</option>'; }).join('') + '</select>' +
      '<button type="button" class="btn" id="mpSoundTest" style="padding:3px 10px">Проверить</button></div>' +
      (st.settings.sound_kind === 'wav' ? '<div class="mp-bar" style="margin:6px 0 0"><input id="mpSoundFile" placeholder="C:\\путь\\к\\звуку.wav" value="' + esc(st.settings.sound_file) + '" style="flex:1;min-width:0" aria-label="Путь к файлу .wav"></div>' : '') +
      '<div class="small muted" style="margin-top:4px">' + (st.sound_ok ? 'Звучит из самой программы — даже когда окно закрыто (программа в трее). Враг в вашей или соседней системе — сигнал чаще.' :
        'Звук тревоги работает только в Windows.') + ' <span id="mpSoundMsg" role="status"></span></div></section>';
    $('mpSide').innerHTML = chars + intel + chans;
  }

  // ----- перемещение и масштаб -----
  function bindSvg() {
    var svg = $('mpSvg'), drag = null;
    function pt(e) { var r = svg.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; }
    svg.addEventListener('wheel', function (e) {
      e.preventDefault();
      var v = M.view, p = pt(e), k = e.deltaY > 0 ? 1.15 : 1 / 1.15, nw = v[2] * k, nh = v[3] * k;
      if (nw > M.full[2] * 3 || nw < 60) return;
      M.view = [v[0] + (v[2] - nw) * p[0], v[1] + (v[3] - nh) * p[1], nw, nh];
      applyView();
    }, { passive: false });
    svg.addEventListener('pointerdown', function (e) { drag = { x: e.clientX, y: e.clientY, v: M.view.slice(), moved: false }; svg.classList.add('drag'); });
    window.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var r = svg.getBoundingClientRect(), dx = (e.clientX - drag.x) / r.width * drag.v[2], dy = (e.clientY - drag.y) / r.height * drag.v[3];
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) drag.moved = true;
      M.view = [drag.v[0] - dx, drag.v[1] - dy, drag.v[2], drag.v[3]];
      applyView();
    });
    window.addEventListener('pointerup', function (e) {
      if (!drag) return;
      var moved = drag.moved;
      drag = null; svg.classList.remove('drag');
      if (moved) return;
      var n = e.target.closest && e.target.closest('[data-sys]');
      M.sel = n ? +n.getAttribute('data-sys') : null;
      if (n && M.d.sys[M.sel] && String(M.d.sys[M.sel].r) !== String(M.region) && e.detail > 1) goSystem(M.sel);
      M.key = null; draw();
    });
    svg.addEventListener('dblclick', function (e) { var n = e.target.closest('[data-sys]'); if (n) goSystem(+n.getAttribute('data-sys')); });
  }
  function goSystem(id) {
    var s = M.d.sys[id];
    if (!s) return;
    if (String(s.r) !== String(M.region)) { M.region = s.r; M.view = null; M.follow = false; remember(); }
    M.sel = id; M.key = null; draw();
  }
  function saveSettings(body) { api('/api/map/settings', { method: 'POST', headers: POST, body: JSON.stringify(body) }).then(function () { loadState(true); }); }

  document.addEventListener('click', function (e) {
    var box = $('mpBox');
    if (!box || !box.contains(e.target)) return;
    var g = e.target.closest('[data-mp-go]');
    if (g) { goSystem(+g.getAttribute('data-mp-go')); return; }
    if (e.target.closest('[data-mp-close]')) { M.sel = null; M.key = null; draw(); return; }
    if (e.target.id === 'mpFit') { M.view = null; M.key = null; draw(); }
    if (e.target.id === 'mpSoundTest') {
      api('/api/map/sound/test', { method: 'POST', headers: POST, body: '{}' }).then(function (j) { var m = $('mpSoundMsg'); if (m) m.textContent = j.message || (j.ok ? 'играю…' : ''); });
    }
  });
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t || !$('mpBox') || !$('mpBox').contains(t)) return;
    if (t.id === 'mpRegion') { M.region = t.value; M.follow = false; M.view = null; M.sel = null; remember(); M.key = null; draw(); }
    else if (t.id === 'mpOverlay') { M.overlay = t.value; remember(); M.key = null; draw(); }
    else if (t.id === 'mpFollow') { M.follow = t.checked; remember(); M.view = null; loadState(true); }
    else if (t.id === 'mpRange') saveSettings({ range: +t.value });
    else if (t.id === 'mpSound') saveSettings({ sound: t.checked });
    else if (t.id === 'mpSoundKind') saveSettings({ sound_kind: t.value });
    else if (t.id === 'mpSoundFile') saveSettings({ sound_file: t.value });
    else if (t.hasAttribute('data-mp-chan')) {
      var on = [].slice.call(document.querySelectorAll('[data-mp-chan]')).filter(function (x) { return x.checked; }).map(function (x) { return x.getAttribute('data-mp-chan'); });
      saveSettings({ intel: on });
    } else if (t.id === 'mpFind') find(t.value);
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Enter' && e.target && e.target.id === 'mpFind') find(e.target.value); });
  function find(v) {
    v = (v || '').trim().toLowerCase();
    if (!v || !M.d) return;
    var sid = M.d.byName[v];
    if (sid) { goSystem(sid); return; }
    var r = Object.keys(M.d.regions).filter(function (k) { return M.d.regions[k].toLowerCase() === v; })[0] ||
      Object.keys(M.d.regions).filter(function (k) { return M.d.regions[k].toLowerCase().indexOf(v) === 0; })[0];
    if (r) { M.region = r; M.follow = false; M.view = null; M.sel = null; remember(); M.key = null; draw(); }
  }
  setInterval(function () { if (M.d && !document.hidden) loadState(); }, 5000);   // тревога работает и когда вкладка не открыта
  M.ready = true;
  setTimeout(function () { if ($('mpBox') && $('mpBox').offsetParent) draw(); }, 0);
})(window.ELW);
