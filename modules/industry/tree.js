// Дерево строительства в «Ведении производства»: схема слева направо (сырьё → компоненты → продукт) и раскрывающийся список.
(function (ELW) {
  'use strict';
  if (!ELW) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$;
  var W = 220, H = 78, GX = 54, GY = 12, PAD = 16;
  var T = { view: 'schema', full: false, missing: false, zoom: 1, closed: {}, cache: {}, d: null };
  try {
    var saved = JSON.parse(localStorage.getItem('elw.industry.tree') || '{}');
    if (saved.view === 'list') T.view = 'list';
    T.full = !!saved.full; T.missing = !!saved.missing;
    if (saved.zoom > 0.2 && saved.zoom <= 2) T.zoom = saved.zoom;
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.industry.tree', JSON.stringify({ view: T.view, full: T.full, missing: T.missing, zoom: T.zoom })); } catch (e) { } }
  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function pct(v) { return String(Math.round(v * 1000) / 10).replace('.', ',') + '%'; }
  function ico(t) { return ELW_INDUSTRY.ico(t); }

  // ----- расчёт готовности: склад общий, позиция одного типа в разных ветках делит его поровну по нужде -----
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
    return T.full && n.depth >= 1 && n.c.length > 0;            // до минералов дерево большое — компоненты свёрнуты, раскрываются по клику
  }
  function state(n) { return n.pct >= 0.9999 ? 'ok' : n.pct > 0 ? 'part' : 'none'; }
  function shown(n) { return !T.missing || n.pct < 0.9999; }

  // ----- схема -----
  function layout(roots) {
    var nodes = [], edges = [], row = 0, maxDepth = 0;
    function depthOf(n) { maxDepth = Math.max(maxDepth, n.depth); if (!closed(n)) n.c.filter(shown).forEach(depthOf); }
    roots.forEach(depthOf);
    function place(n) {
      var kids = closed(n) ? [] : n.c.filter(shown);
      kids.forEach(place);
      n.y = kids.length ? (kids[0].y + kids[kids.length - 1].y) / 2 : row++;
      n.x = maxDepth - n.depth;
      nodes.push(n);
      kids.forEach(function (c) { edges.push([c, n]); });
    }
    roots.filter(shown).forEach(function (r) { place(r); row += 0.5; });
    return { nodes: nodes, edges: edges, w: (maxDepth + 1) * (W + GX) - GX + PAD * 2, h: Math.max(1, row) * (H + GY) + PAD * 2 };
  }
  function card(n, d) {
    var st = state(n), kids = n.c.length, canBuild = !n.top && n.b && n.k === 'm' && !T.full && d.calc.kind !== 'plan';
    return '<div class="tr-node tr-' + st + (n.built && !n.top ? ' tr-built' : '') + (n.top ? ' tr-top' : '') + '" style="left:' + (PAD + n.x * (W + GX)) + 'px;top:' + (PAD + n.y * (H + GY)) + 'px">' +
      '<div class="tr-hd">' + ico(n.t) + '<span class="tr-nm">' + ELW_INDUSTRY.cp(n.n) + '</span>' +
      (kids ? '<button type="button" class="tr-tg" data-tr-tg="' + n.path + '" aria-label="' + (closed(n) ? 'Раскрыть' : 'Свернуть') + ' ветку">' + (closed(n) ? '▸ ' + kids : '◂') + '</button>' : '') + '</div>' +
      '<div class="tr-sub">' + (n.top ? L.fmtInt(n.q) + ' шт.' : 'нужно ' + L.fmtInt(n.q) + (n.have ? ' · есть ' + L.fmtInt(n.have) : '')) +
      (n.built && !n.top ? ' · <b>строю</b>' : kids ? '' : n.price !== undefined ? ' · ' + isk(n.val) : '') + '</div>' +
      '<div class="tr-bar"><div style="width:' + Math.min(100, n.pct * 100) + '%"></div></div>' +
      '<div class="tr-ft"><span>' + pct(n.pct) + '</span>' + (canBuild ? '<button type="button" class="tr-bt" data-tr-build="' + n.t + '" data-on="' + (n.built ? 0 : 1) + '">' + (n.built ? 'покупать' : '⚒ строить') + '</button>' : '') + '</div></div>';
  }
  function schema(roots, d) {
    var g = layout(roots), lines = '';
    g.edges.forEach(function (e) {
      var c = e[0], p = e[1], x1 = PAD + c.x * (W + GX) + W, y1 = PAD + c.y * (H + GY) + H / 2, x2 = PAD + p.x * (W + GX), y2 = PAD + p.y * (H + GY) + H / 2, mx = x2 - GX / 2;
      lines += '<path d="M' + x1 + ',' + y1 + ' H' + mx + ' V' + y2 + ' H' + x2 + '" class="tr-ln tr-ln-' + state(c) + '"/>';
    });
    T.size = [g.w, g.h];                                         // область прокрутки = размер схемы × масштаб
    return '<div class="tr-wrap" id="trWrap"><div class="tr-sizer" id="trSizer" style="width:' + g.w * T.zoom + 'px;height:' + g.h * T.zoom + 'px">' +
      '<div class="tr-canvas" id="trCanvas" style="width:' + g.w + 'px;height:' + g.h + 'px;transform:scale(' + T.zoom + ')">' +
      '<svg width="' + g.w + '" height="' + g.h + '" aria-hidden="true">' + lines + '</svg>' + g.nodes.map(function (n) { return card(n, d); }).join('') + '</div></div></div>';
  }

  // ----- список -----
  function list(roots, d) {
    var h = '';
    function row(n) {
      if (!shown(n)) return;
      var kids = n.c.filter(shown), st = state(n), canBuild = !n.top && n.b && n.k === 'm' && !T.full && d.calc.kind !== 'plan';
      h += '<div class="tr-row tr-' + st + '" style="padding-left:' + (6 + n.depth * 20) + 'px">' +
        (kids.length ? '<button type="button" class="tr-tg" data-tr-tg="' + n.path + '" aria-expanded="' + !closed(n) + '">' + (closed(n) ? '▸' : '▾') + '</button>' : '<span class="tr-tg-sp"></span>') +
        '<span class="tr-ln-nm">' + ico(n.t) + ELW_INDUSTRY.cp(n.n) + ' <span class="muted">×' + L.fmtInt(n.q) + '</span>' + (n.built && !n.top ? ' <span class="sc-badge t2">строю</span>' : '') + '</span>' +
        '<span class="tr-ln-bar"><span style="width:' + Math.min(100, n.pct * 100) + '%"></span></span><span class="tr-ln-p">' + pct(n.pct) + '</span>' +
        '<span class="tr-ln-h">' + (n.top ? '' : (n.have ? L.fmtInt(n.have) : '0') + ' / ' + L.fmtInt(n.need)) + '</span>' +
        '<span class="tr-ln-v">' + (n.val ? isk(n.val) : '') + '</span>' +
        (canBuild ? '<button type="button" class="tr-bt" data-tr-build="' + n.t + '" data-on="' + (n.built ? 0 : 1) + '">' + (n.built ? 'покупать' : '⚒ строить') + '</button>' : '<span></span>') + '</div>';
      if (!closed(n)) kids.forEach(row);
    }
    roots.forEach(row);
    return '<div class="tr-list"><div class="tr-row tr-head"><span class="tr-tg-sp"></span><span>Что</span><span>Собрано</span><span></span><span>Есть / нужно</span><span>Стоимость</span><span></span></div>' + h + '</div>';
  }

  // ----- раздел целиком -----
  function chip(attr, val, label, on) { return '<button type="button" class="in-chip' + (on ? ' on' : '') + '" ' + attr + '="' + val + '">' + label + '</button>'; }
  function draw() {
    var box = $('pjTree'), d = T.d;
    if (!box || !d) return;
    var key = d.project.id + ':' + (T.full ? 1 : 0) + ':' + JSON.stringify([d.project.settings, d.project.items, d.project.mode]);
    var roots = T.cache[key];
    var bar = '<div class="in-chips" style="margin:2px 0 8px">' + chip('data-tr-view', 'schema', 'Схема', T.view === 'schema') + chip('data-tr-view', 'list', 'Список', T.view === 'list') +
      '<span class="small muted" style="margin-left:8px">Раскрыть</span>' + chip('data-tr-full', '0', 'до компонентов', !T.full) + chip('data-tr-full', '1', 'до минералов', T.full) +
      '<label class="small" style="margin-left:8px"><input type="checkbox" id="trMiss"' + (T.missing ? ' checked' : '') + '> только чего не хватает</label>' +
      (T.view === 'schema' ? '<span style="flex:1"></span><button type="button" class="btn" data-tr-zoom="-1" aria-label="Мельче">−</button><span class="small muted" id="trZ">' + Math.round(T.zoom * 100) + '%</span>' +
        '<button type="button" class="btn" data-tr-zoom="1" aria-label="Крупнее">+</button><button type="button" class="btn" data-tr-zoom="fit">Вписать</button>' : '') +
      '<button type="button" class="btn" data-tr-all="1">Раскрыть всё</button><button type="button" class="btn" data-tr-all="0">Свернуть всё</button></div>' +
      '<div class="small muted" style="margin-bottom:6px">Зелёный — собрано, жёлтый — частично, красный — нет; синяя метка — строите сами. Готовность ветки считается по стоимости её материалов. ' +
      (T.view === 'schema' ? 'Схему можно таскать мышью, Ctrl+колесо — масштаб.' : '') + '</div>';
    if (!roots) {
      box.innerHTML = bar + '<p class="muted small">Строю дерево…</p>';
      api('/api/industry/project/tree?id=' + encodeURIComponent(d.project.id) + '&full=' + (T.full ? 1 : 0)).then(function (j) {
        if (!j.ok) { box.innerHTML = bar + '<p class="in-bad small">' + esc(j.message || 'Не получилось.') + '</p>'; return; }
        T.cache = {}; T.cache[key] = j.tree; draw();
      }, function () { box.innerHTML = bar + '<p class="in-bad small">Нет связи с трекером.</p>'; });
      return;
    }
    prepare(roots, d);
    var keepX = $('trWrap') ? $('trWrap').scrollLeft : null, keepY = $('trWrap') ? $('trWrap').scrollTop : null;
    box.innerHTML = bar + (T.view === 'schema' ? schema(roots, d) : list(roots, d));
    var w = $('trWrap');
    if (w && keepX !== null) { w.scrollLeft = keepX; w.scrollTop = keepY; }
    else if (w && roots[0]) {                                   // впервые — к продукту: он справа, посередине своей ветки
      w.scrollLeft = w.scrollWidth;
      w.scrollTop = Math.max(0, (PAD + roots[0].y * (H + GY) + H / 2) * T.zoom - w.clientHeight / 2);
    }
  }
  function setZoom(z) {
    T.zoom = Math.max(0.1, Math.min(2, Math.round(z * 100) / 100));
    var c = $('trCanvas'), sz = $('trSizer'), w = $('trWrap');
    var cx = w ? (w.scrollLeft + w.clientWidth / 2) / (sz ? sz.offsetWidth : 1) : 0, cy = w ? (w.scrollTop + w.clientHeight / 2) / (sz ? sz.offsetHeight : 1) : 0;
    if (c) c.style.transform = 'scale(' + T.zoom + ')';
    if (sz && T.size) { sz.style.width = T.size[0] * T.zoom + 'px'; sz.style.height = T.size[1] * T.zoom + 'px'; }
    if (w && sz) { w.scrollLeft = cx * sz.offsetWidth - w.clientWidth / 2; w.scrollTop = cy * sz.offsetHeight - w.clientHeight / 2; }   // середина остаётся на месте
    var zl = $('trZ'); if (zl) zl.textContent = Math.round(T.zoom * 100) + '%';
    remember();
  }
  function allNodes(fn) { var key = Object.keys(T.cache)[0], roots = key && T.cache[key]; (function walk(ns) { (ns || []).forEach(function (n) { fn(n); walk(n.c); }); })(roots); }

  document.addEventListener('click', function (e) {
    var box = $('pjTree');
    if (!box || !box.contains(e.target)) return;
    var b = e.target.closest('[data-tr-tg],[data-tr-view],[data-tr-full],[data-tr-zoom],[data-tr-all],[data-tr-build]');
    if (!b) return;
    if (b.hasAttribute('data-tr-tg')) { var path = b.getAttribute('data-tr-tg'), n = null; allNodes(function (x) { if (x.path === path) n = x; }); if (n) T.closed[path] = !closed(n); }
    else if (b.hasAttribute('data-tr-view')) { T.view = b.getAttribute('data-tr-view'); }
    else if (b.hasAttribute('data-tr-full')) { T.full = b.getAttribute('data-tr-full') === '1'; T.closed = {}; }
    else if (b.hasAttribute('data-tr-all')) { var open = b.getAttribute('data-tr-all') === '1'; T.closed = {}; allNodes(function (x) { if (x.c.length) T.closed[x.path] = !open; }); }
    else if (b.hasAttribute('data-tr-zoom')) {
      var z = b.getAttribute('data-tr-zoom'), w = $('trWrap'), c = $('trCanvas');
      // «Вписать»: по ширине целиком, по высоте — не мельче 50% (дальше прокрутка)
      if (z === 'fit' && w && c) { setZoom(Math.min(1, (w.clientWidth - 4) / c.offsetWidth, Math.max(0.5, (w.clientHeight - 4) / c.offsetHeight))); w.scrollLeft = w.scrollWidth; w.scrollTop = 0; }
      else setZoom(T.zoom + (+z) * 0.1);
      return;
    } else if (b.hasAttribute('data-tr-build')) { if (ELW_INDUSTRY.projects) ELW_INDUSTRY.projects.build(+b.getAttribute('data-tr-build'), b.getAttribute('data-on') === '1'); return; }
    remember(); draw();
  });
  document.addEventListener('change', function (e) { if (e.target && e.target.id === 'trMiss') { T.missing = e.target.checked; remember(); draw(); } });
  // перетаскивание схемы мышью и масштаб Ctrl+колесом
  var drag = null;
  document.addEventListener('mousedown', function (e) {
    var w = e.target.closest && e.target.closest('#trWrap');
    if (!w || e.button !== 0 || e.target.closest('.tr-node button, .in-cp')) return;
    drag = { x: e.clientX, y: e.clientY, l: w.scrollLeft, t: w.scrollTop, w: w };
    w.classList.add('tr-drag'); e.preventDefault();
  });
  document.addEventListener('mousemove', function (e) { if (drag) { drag.w.scrollLeft = drag.l - (e.clientX - drag.x); drag.w.scrollTop = drag.t - (e.clientY - drag.y); } });
  document.addEventListener('mouseup', function () { if (drag) { drag.w.classList.remove('tr-drag'); drag = null; } });
  document.addEventListener('wheel', function (e) {
    if (!e.ctrlKey || !(e.target.closest && e.target.closest('#trWrap'))) return;
    e.preventDefault(); setZoom(T.zoom * (e.deltaY < 0 ? 1.1 : 0.9));
  }, { passive: false });

  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.tree = {
    mount: function (d) { if (!T.d || T.d.project.id !== d.project.id) { T.closed = {}; T.cache = {}; } T.d = d; draw(); },
    css: '.tr-wrap{position:relative;overflow:auto;height:560px;border:1px solid var(--line);border-radius:10px;background:var(--panel);cursor:grab}.tr-wrap.tr-drag{cursor:grabbing;user-select:none}' +
      '.tr-sizer{position:relative;overflow:hidden}.tr-canvas{position:absolute;left:0;top:0;transform-origin:0 0}.tr-canvas svg{position:absolute;left:0;top:0;pointer-events:none}' +
      '.tr-ln{fill:none;stroke:var(--line);stroke-width:1.6}.tr-ln-ok{stroke:var(--good);stroke-opacity:.7}.tr-ln-part{stroke:var(--warn);stroke-opacity:.6}' +
      '.tr-node{position:absolute;width:' + W + 'px;height:' + H + 'px;box-sizing:border-box;background:var(--panel2);border:1px solid var(--line);border-left:4px solid var(--bad);border-radius:7px;padding:5px 8px;font-size:11.5px;line-height:1.3;display:flex;flex-direction:column;justify-content:space-between;cursor:default;box-shadow:0 2px 8px rgba(0,0,0,.25)}' +
      '.tr-node.tr-ok{border-left-color:var(--good)}.tr-node.tr-part{border-left-color:var(--warn)}.tr-node.tr-built{box-shadow:inset 0 0 0 1px var(--accent),0 2px 8px rgba(0,0,0,.25)}' +
      '.tr-node.tr-top{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,var(--panel2))}' +
      '.tr-hd{display:flex;align-items:center;gap:3px;min-width:0;font-weight:650;font-size:12px}.tr-hd .in-ico{width:18px;height:18px;margin-right:2px}.tr-nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.tr-sub{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tr-sub b{color:var(--accent);font-weight:600}' +
      '.tr-bar{height:4px;background:var(--panel);border-radius:2px;overflow:hidden}.tr-bar>div{height:100%;background:linear-gradient(90deg,var(--accent),var(--good))}' +
      '.tr-ft{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-variant-numeric:tabular-nums}' +
      '.tr-tg{background:none;border:1px solid var(--line);color:var(--muted);border-radius:5px;font:inherit;font-size:11px;padding:0 5px;cursor:pointer;flex:none}.tr-tg:hover{color:var(--text);border-color:var(--accent)}' +
      '.tr-bt{background:none;border:1px solid var(--line);color:var(--accent);border-radius:5px;font:inherit;font-size:10.5px;padding:0 5px;cursor:pointer}.tr-bt:hover{border-color:var(--accent)}' +
      '.tr-list{border:1px solid var(--line);border-radius:10px;overflow:hidden}.tr-row{display:grid;grid-template-columns:22px minmax(220px,2.5fr) minmax(80px,1fr) 52px 130px 90px 82px;gap:8px;align-items:center;padding:4px 8px;border-top:1px solid var(--line);font-size:12.5px;border-left:3px solid var(--bad)}' +
      '.tr-row.tr-ok{border-left-color:var(--good)}.tr-row.tr-part{border-left-color:var(--warn)}.tr-row.tr-head{border-top:0;border-left-color:transparent;color:var(--muted);font-size:11.5px;background:var(--panel2)}' +
      '.tr-tg-sp{width:22px}.tr-ln-nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tr-ln-bar{height:6px;background:var(--panel2);border-radius:3px;overflow:hidden}.tr-ln-bar>span{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--good))}' +
      '.tr-ln-p,.tr-ln-h,.tr-ln-v{font-variant-numeric:tabular-nums;text-align:right;color:var(--muted)}.tr-ln-v{color:var(--text)}' +
      '@media(max-width:760px){.tr-row{grid-template-columns:22px 1fr 60px 48px}.tr-ln-h,.tr-ln-v,.tr-row>.tr-bt,.tr-row>span:last-child{display:none}}'
  };
  var st = document.createElement('style');                  // стили схемы — свои, вкладка подключает только tab.js
  st.textContent = ELW_INDUSTRY.tree.css;
  document.head.appendChild(st);
})(window.ELW);
