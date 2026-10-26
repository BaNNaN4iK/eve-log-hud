// Дерево строительства в «Ведении производства»: раскрывающийся список «что из чего строится» с готовностью веток.
(function (ELW) {
  'use strict';
  if (!ELW) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$;
  var T = { full: false, missing: false, fam: '', closed: {}, cache: {}, d: null };
  try {
    var saved = JSON.parse(localStorage.getItem('elw.industry.tree') || '{}');
    T.full = !!saved.full; T.missing = !!saved.missing;
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.industry.tree', JSON.stringify({ full: T.full, missing: T.missing })); } catch (e) { } }
  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function pct(v) { return String(Math.round(v * 1000) / 10).replace('.', ',') + '%'; }
  function ico(t) { return ELW_INDUSTRY.ico(t); }

  // ----- готовность: склад общий, позиция одного типа в разных ветках делит его поровну по нужде -----
  function prepare(roots, d) {
    var need = {}, price = {}, have = (d.project && d.project.have) || {};
    (d.materials || []).concat((d.raw && d.raw.materials) || []).forEach(function (m) { if (m.price !== null && m.price !== undefined) price[m.type_id] = m.price; });
    function count(n) { need[n.t] = (need[n.t] || 0) + n.q; n.c.forEach(count); }
    roots.forEach(function (r) { r.c.forEach(count); });
    function roll(n, path, depth) {
      n.path = path; n.depth = depth;
      var own = n.top ? 0 : Math.min(1, (+have[n.t] || 0) / (need[n.t] || 1));
      n.have = +have[n.t] || 0; n.need = need[n.t] || n.q;
      if (!n.c.length) {
        n.price = price[n.t];
        n.val = n.price !== undefined ? n.price * n.q : 0;
        n.pct = own;
      } else {
        var v = 0, w = 0, cnt = 0, sum = 0;
        n.c.forEach(function (c, i) { roll(c, path + '.' + i, depth + 1); v += c.val; w += c.val * c.pct; sum += c.pct; cnt++; });
        n.val = v;
        var child = v ? w / v : (cnt ? sum / cnt : 0);
        n.pct = own + (1 - own) * child;
      }
    }
    roots.forEach(function (r, i) { roll(r, String(i), 0); });
  }
  function closed(n) {
    if (Object.prototype.hasOwnProperty.call(T.closed, n.path)) return T.closed[n.path];
    return T.full && n.depth >= 1 && n.c.length > 0;            // до минералов дерево большое — компоненты свёрнуты
  }
  function state(n) { return n.pct >= 0.9999 ? 'ok' : n.pct > 0 ? 'part' : 'none'; }
  function famIn(n) { return !T.fam || n.f === T.fam || n.c.some(famIn); }      // ветка, где есть материал этого вида
  function shown(n) { return (!T.missing || n.pct < 0.9999) && famIn(n); }

  function list(roots, d) {
    var h = '';
    function row(n) {
      if (!shown(n)) return;
      var kids = n.c.filter(shown), st = state(n), canBuild = !n.top && n.b && n.k === 'm' && !T.full && d.calc.kind !== 'plan';
      h += '<div class="tr-row tr-' + st + '" style="padding-left:' + (6 + n.depth * 20) + 'px">' +
        (kids.length ? '<button type="button" class="tr-tg" data-tr-tg="' + n.path + '" aria-expanded="' + !closed(n) + '" aria-label="' + (closed(n) ? 'Раскрыть' : 'Свернуть') + '">' + (closed(n) ? '▸' : '▾') + '</button>' : '<span class="tr-tg-sp"></span>') +
        '<span class="tr-ln-nm">' + ico(n.t) + ELW_INDUSTRY.cp(n.n) + ' <span class="muted">×' + L.fmtInt(n.q) + '</span>' +
        (n.built && !n.top ? ' <span class="sc-badge t2">строю</span>' : '') + (kids.length && closed(n) ? ' <span class="in-sub">' + kids.length + ' мат.</span>' : '') + '</span>' +
        '<span>' + (n.top ? '' : ELW_INDUSTRY.fam(n.f, n.fl)) + '</span>' +
        '<span class="tr-ln-bar"><span style="width:' + Math.min(100, n.pct * 100) + '%"></span></span><span class="tr-ln-p">' + pct(n.pct) + '</span>' +
        '<span class="tr-ln-h">' + (n.top ? '' : (n.have ? L.fmtInt(n.have) : '0') + ' / ' + L.fmtInt(n.need)) + '</span>' +
        '<span class="tr-ln-v">' + (n.val ? isk(n.val) : '') + '</span>' +
        (canBuild ? '<button type="button" class="tr-bt" data-tr-build="' + n.t + '" data-on="' + (n.built ? 0 : 1) + '">' + (n.built ? 'покупать' : '⚒ строить') + '</button>' : '<span></span>') + '</div>';
      if (!closed(n)) kids.forEach(row);
    }
    roots.forEach(row);
    return '<div class="tr-list"><div class="tr-row tr-head"><span class="tr-tg-sp"></span><span>Что</span><span>Вид</span><span>Собрано</span><span></span><span>Есть / нужно</span><span>Стоимость</span><span></span></div>' +
      (h || '<div class="tr-row"><span></span><span class="muted">Ничего — всё собрано или нет материалов этого вида.</span></div>') + '</div>';
  }

  function chip(attr, val, label, on) { return '<button type="button" class="in-chip' + (on ? ' on' : '') + '" ' + attr + '="' + esc(val) + '">' + label + '</button>'; }
  function draw() {
    var box = $('pjTree'), d = T.d;
    if (!box || !d) return;
    var key = d.project.id + ':' + (T.full ? 1 : 0) + ':' + JSON.stringify([d.project.settings, d.project.items, d.project.mode]);
    var roots = T.cache[key];
    var bar = function (fams) {
      return '<div class="in-chips" style="margin:2px 0 8px"><span class="small muted">Раскрыть</span>' + chip('data-tr-full', '0', 'до компонентов', !T.full) + chip('data-tr-full', '1', 'до минералов', T.full) +
        '<label class="small" style="margin-left:8px"><input type="checkbox" id="trMiss"' + (T.missing ? ' checked' : '') + '> только чего не хватает</label><span style="flex:1"></span>' +
        '<button type="button" class="btn" data-tr-all="1">Раскрыть всё</button><button type="button" class="btn" data-tr-all="0">Свернуть всё</button></div>' +
        (fams && fams.length > 1 ? '<div class="in-chips" style="margin-bottom:8px"><span class="small muted">Вид</span>' + chip('data-tr-fam', '', 'все', !T.fam) +
          fams.map(function (f) { return chip('data-tr-fam', f[0], f[1], T.fam === f[0]); }).join('') + '</div>' : '') +
        '<div class="small muted" style="margin-bottom:6px">Зелёный край — собрано, жёлтый — частично, красный — нет. Готовность ветки считается по стоимости её материалов.</div>';
    };
    if (!roots) {
      box.innerHTML = bar() + '<p class="muted small">Строю дерево…</p>';
      api('/api/industry/project/tree?id=' + encodeURIComponent(d.project.id) + '&full=' + (T.full ? 1 : 0)).then(function (j) {
        if (!j.ok) { box.innerHTML = bar() + '<p class="in-bad small">' + esc(j.message || 'Не получилось.') + '</p>'; return; }
        T.cache = {}; T.cache[key] = j.tree; draw();
        setTimeout(function () { if (T.cache[key] === j.tree) draw(); }, 5000);      // иконки догружаются
      }, function () { box.innerHTML = bar() + '<p class="in-bad small">Нет связи с трекером.</p>'; });
      return;
    }
    prepare(roots, d);
    var fams = {}, order = [];
    (function walk(ns) { ns.forEach(function (n) { if (!n.top && n.f && !fams[n.f]) { fams[n.f] = ELW_INDUSTRY.famName(n.f, n.fl); order.push(n.f); } walk(n.c); }); })(roots);
    if (T.fam && !fams[T.fam]) T.fam = '';
    box.innerHTML = bar(order.map(function (f) { return [f, fams[f]]; })) + list(roots, d);
  }
  function allNodes(fn) { var key = Object.keys(T.cache)[0], roots = key && T.cache[key]; (function walk(ns) { (ns || []).forEach(function (n) { fn(n); walk(n.c); }); })(roots); }

  document.addEventListener('click', function (e) {
    var box = $('pjTree');
    if (!box || !box.contains(e.target)) return;
    var b = e.target.closest('[data-tr-tg],[data-tr-full],[data-tr-all],[data-tr-build],[data-tr-fam]');
    if (!b) return;
    if (b.hasAttribute('data-tr-tg')) { var path = b.getAttribute('data-tr-tg'), n = null; allNodes(function (x) { if (x.path === path) n = x; }); if (n) T.closed[path] = !closed(n); }
    else if (b.hasAttribute('data-tr-full')) { T.full = b.getAttribute('data-tr-full') === '1'; T.closed = {}; }
    else if (b.hasAttribute('data-tr-fam')) { T.fam = b.getAttribute('data-tr-fam'); if (T.fam) { T.closed = {}; allNodes(function (x) { if (x.c.length) T.closed[x.path] = false; }); } }
    else if (b.hasAttribute('data-tr-all')) { var open = b.getAttribute('data-tr-all') === '1'; T.closed = {}; allNodes(function (x) { if (x.c.length) T.closed[x.path] = !open; }); }
    else if (b.hasAttribute('data-tr-build')) { if (ELW_INDUSTRY.projects) ELW_INDUSTRY.projects.build(+b.getAttribute('data-tr-build'), b.getAttribute('data-on') === '1'); return; }
    remember(); draw();
  });
  document.addEventListener('change', function (e) { if (e.target && e.target.id === 'trMiss') { T.missing = e.target.checked; remember(); draw(); } });

  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.tree = {
    mount: function (d) { if (!T.d || T.d.project.id !== d.project.id) { T.closed = {}; T.cache = {}; T.fam = ''; } T.d = d; draw(); }
  };
  var st = document.createElement('style');                  // стили списка — свои, вкладка подключает только tab.js
  st.textContent = '.tr-list{border:1px solid var(--line);border-radius:10px;overflow:hidden}' +
    '.tr-row{display:grid;grid-template-columns:22px minmax(220px,2.4fr) minmax(110px,1fr) minmax(80px,1fr) 52px 130px 90px 82px;gap:8px;align-items:center;padding:4px 8px;border-top:1px solid var(--line);font-size:12.5px;border-left:3px solid var(--bad)}' +
    '.tr-row.tr-ok{border-left-color:var(--good)}.tr-row.tr-part{border-left-color:var(--warn)}.tr-row.tr-head{border-top:0;border-left-color:transparent;color:var(--muted);font-size:11.5px;background:var(--panel2)}' +
    '.tr-tg{background:none;border:1px solid var(--line);color:var(--muted);border-radius:5px;font:inherit;font-size:11px;padding:0 5px;cursor:pointer}.tr-tg:hover{color:var(--text);border-color:var(--accent)}' +
    '.tr-bt{background:none;border:1px solid var(--line);color:var(--accent);border-radius:5px;font:inherit;font-size:10.5px;padding:0 5px;cursor:pointer}.tr-bt:hover{border-color:var(--accent)}' +
    '.tr-tg-sp{width:22px}.tr-ln-nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tr-ln-bar{height:6px;background:var(--panel2);border-radius:3px;overflow:hidden}' +
    '.tr-ln-bar>span{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--good))}' +
    '.tr-ln-p,.tr-ln-h,.tr-ln-v{font-variant-numeric:tabular-nums;text-align:right;color:var(--muted)}.tr-ln-v{color:var(--text)}' +
    '@media(max-width:760px){.tr-row{grid-template-columns:22px 1fr 60px 48px}.tr-row>span:nth-child(3),.tr-ln-h,.tr-ln-v,.tr-row>.tr-bt,.tr-row>span:last-child{display:none}}';
  document.head.appendChild(st);
})(window.ELW);
