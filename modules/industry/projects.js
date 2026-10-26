// Ведение производства модуля «Производство»: закреплённые чертежи, склад (что есть / сколько осталось), этапы, цены и графики.
(function (ELW) {
  'use strict';
  if (!ELW) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var COLORS = ['var(--accent)', 'var(--good)', 'var(--warn)', '#9b59b6', '#e67e22', '#1abc9c', '#e84393', '#7f8c8d'];
  var STEPS = [['collect', 'Сбор материалов'], ['building', 'Строится'], ['done', 'Готово']];
  var Q = { built: false, list: null, open: null, d: null, busy: false, loaded: 0, filter: 'all', paste: false, charts: {} };
  try { Q.open = localStorage.getItem('elw.industry.project') || null; } catch (e) { }

  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function pct(v) { return v === null || v === undefined ? '—' : String(Math.round(v * 10) / 10).replace('.', ',') + '%'; }
  function cls(v) { return v > 0 ? 'in-good' : v < 0 ? 'in-bad' : ''; }
  function ico(t) { return ELW_INDUSTRY.ico(t); }
  function fold(k, t, b, o) { return ELW_INDUSTRY.fold('p_' + k, t, b, o); }
  function num(s) { var v = String(s || '').replace(/[\s  ']/g, '').replace(',', '.'); return v === '' ? null : Number(v); }
  function stepName(s) { return (STEPS.filter(function (x) { return x[0] === s; })[0] || ['', s])[1]; }
  function post(body) { return api('/api/industry/projects', { method: 'POST', headers: POST, body: JSON.stringify(body) }); }

  // ---------- графики (SVG без библиотек) ----------
  function donut(parts, center, sub, size) {
    size = size || 150;
    var r = size / 2 - 10, c = size / 2, total = parts.reduce(function (a, p) { return a + Math.max(0, p.v || 0); }, 0), a0 = -Math.PI / 2, g = '';
    if (!total) return '<svg width="' + size + '" height="' + size + '" role="img" aria-label="Нет данных"><circle cx="' + c + '" cy="' + c + '" r="' + r + '" fill="none" stroke="var(--line)" stroke-width="16"/></svg>';
    parts.forEach(function (p) {
      var v = Math.max(0, p.v || 0);
      if (!v) return;
      var a1 = a0 + v / total * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0;
      var path = v >= total ? 'M' + c + ',' + (c - r) + ' A' + r + ',' + r + ' 0 1 1 ' + (c - 0.01) + ',' + (c - r) :
        'M' + (c + r * Math.cos(a0)) + ',' + (c + r * Math.sin(a0)) + ' A' + r + ',' + r + ' 0 ' + big + ' 1 ' + (c + r * Math.cos(a1)) + ',' + (c + r * Math.sin(a1));
      g += '<path d="' + path + '" fill="none" stroke="' + p.c + '" stroke-width="16"><title>' + esc(p.label + ': ' + (p.text || isk(v)) + ' (' + pct(100 * v / total) + ')') + '</title></path>';
      a0 = a1;
    });
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '" role="img" aria-label="' + esc(center + ' ' + (sub || '')) + '">' + g +
      '<text x="' + c + '" y="' + (c + (sub ? 2 : 6)) + '" text-anchor="middle" font-size="20" font-weight="700" fill="currentColor">' + esc(center) + '</text>' +
      (sub ? '<text x="' + c + '" y="' + (c + 20) + '" text-anchor="middle" font-size="11" fill="var(--muted)">' + esc(sub) + '</text>' : '') + '</svg>';
  }
  function legend(parts, total) {
    return '<div class="pj-leg">' + parts.filter(function (p) { return p.v > 0; }).map(function (p) {
      return '<div><i style="background:' + p.c + '"></i><span>' + esc(p.label) + '</span><b>' + esc(p.text || isk(p.v)) + '</b>' +
        (total ? '<em>' + pct(100 * p.v / total) + '</em>' : '') + '</div>';
    }).join('') + '</div>';
  }
  function stack(parts) {                                          // одна полоса 100% — куда уходит выручка
    var total = parts.reduce(function (a, p) { return a + Math.max(0, p.v || 0); }, 0);
    if (!total) return '';
    return '<div class="pj-stack" role="img" aria-label="Структура выручки">' + parts.filter(function (p) { return p.v > 0; }).map(function (p) {
      return '<div style="width:' + (100 * p.v / total) + '%;background:' + p.c + '" title="' + esc(p.label + ': ' + isk(p.v) + ' ISK (' + pct(100 * p.v / total) + ')') + '"></div>';
    }).join('') + '</div>';
  }
  function rawBars(list) {
    var mins = list.filter(function (m) { return m.mineral; });
    var top = (mins.length ? mins : list).slice().sort(function (a, b) { return (b.qty * (b.price || 0)) - (a.qty * (a.price || 0)); }).slice(0, 12);
    if (!top.length) return '';
    return (mins.length ? '<div class="small muted">Минералы: сколько есть из нужного</div>' : '') + '<div class="pj-hbars" role="img" aria-label="Сколько есть из нужного">' + top.map(function (m) {
      return '<div class="pj-hb"><span class="nm">' + ico(m.type_id) + ELW_INDUSTRY.cp(m.name) + '</span><div class="tr"><div style="width:' + Math.min(100, m.pct) + '%;background:' + (m.left ? 'var(--accent)' : 'var(--good)') + '"></div></div>' +
        '<span class="vl">' + esc(L.fmtCompact(Math.min(m.have, m.qty))) + ' / ' + esc(L.fmtCompact(m.qty)) + '</span></div>';
    }).join('') + '</div>';
  }
  function spark(vals, w, h) {
    vals = (vals || []).filter(function (v) { return v !== null && v !== undefined; });
    if (vals.length < 2) return '';
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), d = hi - lo || 1;
    var pts = vals.map(function (v, i) { return (i / (vals.length - 1) * w).toFixed(1) + ',' + (h - 2 - (v - lo) / d * (h - 4)).toFixed(1); }).join(' ');
    return '<svg width="' + w + '" height="' + h + '" aria-hidden="true"><polyline points="' + pts + '" fill="none" stroke="var(--accent)" stroke-width="1.5"/></svg>';
  }
  // линии по времени + полосы объёма снизу; наведение — подсказка (данные графика хранятся по id)
  function lines(id, o) {
    Q.charts[id] = o;
    return '<div class="pj-chart"><svg id="' + id + '" class="pj-line" width="100%" height="' + (o.h || 220) + '" role="img" aria-label="' + esc(o.label || 'График') + '"></svg>' +
      '<div class="pj-tip" id="' + id + 'Tip" role="status" hidden></div></div>' +
      '<div class="pj-leg pj-leg-row">' + o.series.map(function (s) { return '<div><i style="background:' + s.c + (s.dash ? ';opacity:.7' : '') + '"></i><span>' + esc(s.name) + '</span></div>'; }).join('') +
      (o.bars ? '<div><i style="background:var(--line)"></i><span>' + esc(o.barsName || 'объём') + '</span></div>' : '') + '</div>';
  }
  function drawLines(id) {
    var svg = $(id), o = Q.charts[id];
    if (!svg || !o) return;
    var w = svg.clientWidth || 640, h = o.h || 220, padL = 54, padR = 12, top = 12, bottom = 22, bh = o.bars ? 38 : 0;
    var xs = [], ys = [];
    o.series.forEach(function (s) { s.pts.forEach(function (p) { if (p[1] !== null && p[1] !== undefined) { xs.push(p[0]); ys.push(p[1]); } }); if (s.lo) s.lo.forEach(function (p) { if (p[1] !== null) ys.push(p[1]); }); if (s.hi) s.hi.forEach(function (p) { if (p[1] !== null) ys.push(p[1]); }); });
    if (xs.length < 2) { svg.outerHTML = '<div class="small muted">Пока мало данных для графика.</div>'; return; }
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (x1 === x0) x1 = x0 + 1;
    var pad = (y1 - y0) * 0.08 || y1 * 0.05 || 1; y0 = Math.max(0, y0 - pad); y1 = y1 + pad;
    var X = function (x) { return padL + (x - x0) / (x1 - x0) * (w - padL - padR); };
    var Y = function (y) { return top + (1 - (y - y0) / (y1 - y0)) * (h - top - bottom - bh); };
    var g = '';
    for (var i = 0; i <= 3; i++) {
      var yv = y0 + (y1 - y0) * i / 3, yy = Y(yv);
      g += '<line x1="' + padL + '" x2="' + (w - padR) + '" y1="' + yy + '" y2="' + yy + '" stroke="currentColor" stroke-opacity=".08"/>' +
        '<text x="' + (padL - 6) + '" y="' + (yy + 3) + '" text-anchor="end" font-size="10" fill="var(--muted)">' + esc(isk(yv)) + '</text>';
    }
    if (o.bars) {
      var bmax = Math.max.apply(null, o.bars.map(function (b) { return b[1] || 0; })) || 1, bw = Math.max(1, (w - padL - padR) / o.bars.length - 1);
      o.bars.forEach(function (b) { var bhh = (b[1] || 0) / bmax * (bh - 4); g += '<rect x="' + (X(b[0]) - bw / 2) + '" y="' + (h - bottom - bhh) + '" width="' + bw + '" height="' + bhh + '" fill="var(--line)"/>'; });
    }
    o.series.forEach(function (s) {
      if (s.lo && s.hi) {
        var up = s.hi.filter(function (p) { return p[1] !== null; }).map(function (p) { return X(p[0]) + ',' + Y(p[1]); });
        var dn = s.lo.filter(function (p) { return p[1] !== null; }).map(function (p) { return X(p[0]) + ',' + Y(p[1]); }).reverse();
        if (up.length > 1) g += '<polygon points="' + up.concat(dn).join(' ') + '" fill="' + s.c + '" fill-opacity=".12" stroke="none"/>';
      }
      var pts = s.pts.filter(function (p) { return p[1] !== null && p[1] !== undefined; });
      if (pts.length === 1) g += '<circle cx="' + X(pts[0][0]) + '" cy="' + Y(pts[0][1]) + '" r="3" fill="' + s.c + '"/>';
      if (pts.length > 1) g += '<polyline fill="none" stroke="' + s.c + '" stroke-width="' + (s.dash ? 1.5 : 2) + '"' + (s.dash ? ' stroke-dasharray="5 4"' : '') +
        ' points="' + pts.map(function (p) { return X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1); }).join(' ') + '"/>';
    });
    g += '<text x="' + padL + '" y="' + (h - 6) + '" font-size="10" fill="var(--muted)">' + esc(o.xfmt(x0)) + '</text>' +
      '<text x="' + (w - padR) + '" y="' + (h - 6) + '" font-size="10" text-anchor="end" fill="var(--muted)">' + esc(o.xfmt(x1)) + '</text>' +
      '<line id="' + id + 'G" y1="' + top + '" y2="' + (h - bottom) + '" stroke="currentColor" stroke-opacity=".35" stroke-dasharray="3 3" visibility="hidden"/>';
    svg.innerHTML = g;
    o.geo = { X: X, x0: x0, x1: x1, padL: padL, padR: padR, w: w };
  }
  document.addEventListener('mousemove', function (e) {
    var svg = e.target.closest && e.target.closest('svg.pj-line');
    if (!svg) return;
    var o = Q.charts[svg.id], tip = $(svg.id + 'Tip'), gl = $(svg.id + 'G');
    if (!o || !o.geo || !tip) return;
    var rect = svg.getBoundingClientRect(), mx = e.clientX - rect.left, t = o.geo.x0 + (mx - o.geo.padL) / (o.geo.w - o.geo.padL - o.geo.padR) * (o.geo.x1 - o.geo.x0);
    var base = o.series[0].pts, best = 0;
    base.forEach(function (p, i) { if (Math.abs(p[0] - t) < Math.abs(base[best][0] - t)) best = i; });
    var x = base[best][0], h = '<div class="muted">' + esc(o.xfmt(x, true)) + '</div>';
    o.series.forEach(function (s) {
      var p = s.pts.filter(function (q) { return q[0] === x; })[0] || s.pts.reduce(function (a, q) { return Math.abs(q[0] - x) < Math.abs(a[0] - x) ? q : a; }, s.pts[0]);
      if (p && p[1] !== null && p[1] !== undefined) h += '<div><i style="background:' + s.c + '"></i>' + esc(s.name) + ': <b>' + esc(isk(p[1])) + '</b></div>';
    });
    if (o.bars) { var b = o.bars.filter(function (q) { return q[0] === x; })[0]; if (b) h += '<div class="muted">' + esc(o.barsName || 'объём') + ': ' + esc(L.fmtInt(b[1])) + '</div>'; }
    tip.innerHTML = h; tip.hidden = false;
    var gx = o.geo.X(x); gl.setAttribute('x1', gx); gl.setAttribute('x2', gx); gl.setAttribute('visibility', 'visible');
    var box = tip.parentNode.getBoundingClientRect(), left = gx + 14;
    if (left + tip.offsetWidth > box.width) left = Math.max(0, gx - 14 - tip.offsetWidth);
    tip.style.left = left + 'px'; tip.style.top = Math.max(0, e.clientY - box.top - 10) + 'px';
  });
  document.addEventListener('mouseout', function (e) {
    var svg = e.target.closest && e.target.closest('svg.pj-line');
    if (!svg || (e.relatedTarget && svg.contains(e.relatedTarget))) return;
    var tip = $(svg.id + 'Tip'), gl = $(svg.id + 'G');
    if (tip) tip.hidden = true;
    if (gl) gl.setAttribute('visibility', 'hidden');
  });

  // ---------- каркас ----------
  function shell() {
    var box = $('inProjView');
    if (!box || Q.built) return;
    Q.built = true;
    box.innerHTML = '<div id="pjList"></div><section class="panel" id="pjDefaults" style="margin-top:14px" hidden>' +
      ELW_INDUSTRY.fold('p_defaults', 'Настройки по умолчанию <span class="n">— для новых расчётов, сканера и плана: где строим, навыки, рынок</span>',
        ELW_INDUSTRY.form('dfS', { runs: false }) + '<div class="controls" style="margin-top:8px"><button type="button" class="btn primary" id="dfSave">Сохранить</button>' +
        '<span class="small" id="dfMsg" role="status" aria-live="polite"></span></div>', false) + '</section><div id="pjDetail"></div>';
    ELW_INDUSTRY.defaults(function (st) { ELW_INDUSTRY.fillForm('dfS', st); });
  }
  function loadList() {
    if (Q.busy) return;
    Q.busy = true;
    api('/api/industry/projects').then(function (j) { Q.busy = false; Q.list = j.ok ? j.projects : []; Q.loaded = Date.now(); drawList(); },
      function () { Q.busy = false; $('pjList').innerHTML = '<section class="panel"><p class="muted">Нет связи с трекером.</p></section>'; });
  }
  function loadDetail(series) {
    if (!Q.open) return;
    var id = Q.open;
    api('/api/industry/project?id=' + encodeURIComponent(id) + '&series=' + (series === false ? '0' : '1')).then(function (j) {
      if (Q.open !== id) return;
      if (!j.ok) { Q.open = null; remember(); $('pjDetail').innerHTML = ''; drawList(); flash(j.message); return; }
      if (series === false && Q.d && Q.d.series) j.series = Q.d.series;
      Q.d = j; Q.loaded = Date.now(); drawDetail();
    }, function () { flash('Нет связи с трекером.'); });
  }
  function remember() { try { if (Q.open) localStorage.setItem('elw.industry.project', Q.open); else localStorage.removeItem('elw.industry.project'); } catch (e) { } }
  function flash(t) { var m = $('pjMsg'); if (m) m.textContent = t || ''; }
  function openProject(id) { Q.open = id; Q.d = null; Q.paste = false; Q.dirty = false; remember(); $('pjList').innerHTML = ''; $('pjDefaults').hidden = true; $('pjDetail').innerHTML = '<section class="panel"><p class="muted">Считаю…</p></section>'; loadDetail(); window.scrollTo(0, 0); }
  function closeProject() { Q.open = null; Q.d = null; remember(); $('pjDetail').innerHTML = ''; loadList(); }
  function draft(name, over) {
    shell();
    Q.open = null; remember();
    $('pjList').innerHTML = ''; $('pjDefaults').hidden = true;
    $('pjDetail').innerHTML = '<section class="panel"><p class="muted">Считаю ' + esc(name) + '…</p></section>';
    return post({ action: 'draft', product: name, settings: over || {} }).then(function (j) {
      if (j.ok) openProject(j.id);
      else { $('pjDetail').innerHTML = ''; loadList(); setTimeout(function () { flash(j.message); }, 300); }
      return j;
    }, function () { $('pjDetail').innerHTML = '<section class="panel"><p class="in-bad">Нет связи с трекером.</p></section>'; });
  }

  // ---------- список ----------
  function drawList() {
    if (Q.open) return;
    var rows = Q.list || [];
    $('pjDefaults').hidden = false;
    var h = '<section class="panel"><h2>Ведение производства <span class="muted small">расчёт предмета, закреплённые чертежи и планы: склад, что докупить, этапы, цены</span></h2>' +
      '<div class="in-chips"><input id="pjNew" list="pjNewList" autocomplete="off" spellcheck="false" placeholder="Что строим — например: Vexor, Hobgoblin II" aria-label="Что закрепить" ' +
      'style="flex:1 1 260px;min-width:0;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px"><datalist id="pjNewList"></datalist>' +
      '<button type="button" class="btn primary" id="pjCalc">Рассчитать</button><button type="button" class="btn" id="pjAdd">📌 Закрепить</button></div>' +
      '<div class="small muted" style="margin-top:6px">«Рассчитать» — материалы, работы, себестоимость и прибыль без сохранения; понравилось — «Закрепить». ' +
      'Настройки — «по умолчанию» (ниже), в проекте их можно поменять. План из нескольких продуктов закрепляется на экране «План производства».</div>' +
      '<div class="small" id="pjMsg" role="status" aria-live="polite" style="margin-top:6px"></div></section>';
    if (!rows.length) {
      h += '<section class="panel" style="margin-top:14px"><p class="muted">' + (Q.list ? 'Закреплённых чертежей пока нет. Рассчитайте предмет и закрепите его — и здесь будет видно, сколько материалов уже собрано, сколько осталось докупить и на сколько ISK, когда будет готово и сколько принесёт.' : 'Загружаю…') + '</p></section>';
    } else {
      var sum = { left: 0, profit: 0, building: 0 };
      rows.forEach(function (r) { sum.left += r.status === 'collect' && r.left_cost ? r.left_cost : 0; sum.profit += r.status !== 'done' && r.profit ? r.profit : 0; sum.building += r.status === 'building' ? 1 : 0; });
      h += '<div class="tiles" style="margin:14px 0 4px">' + ELW.tile('Проектов', L.fmtInt(rows.length), sum.building ? 'строится ' + sum.building : '') +
        ELW.tile('Докупить всего', isk(sum.left), 'по проектам на сборе материалов') +
        ELW.tile('Ожидаемая прибыль', isk(sum.profit), 'по незавершённым') + '</div>';
      h += '<div class="pj-cards">' + rows.map(function (r) {
        var eta = r.status === 'building' && r.eta ? (r.eta * 1000 > Date.now() ? 'готово через ' + L.fmtDur(Math.round(r.eta - Date.now() / 1000)) : 'должно быть готово') : '';
        return '<div class="pj-card" tabindex="0" role="button" data-pj-open="' + esc(r.id) + '" aria-label="' + esc(r.name) + ': открыть">' +
          '<div class="pj-hd"><span class="sc-ico">' + ico(r.type_id) + '</span><div><div class="sc-name">' + esc(r.name) + '</div>' +
          '<div class="sc-meta">' + (r.kind === 'plan' ? 'план · ' + r.products + ' прод. · ' + L.fmtInt(r.units || 0) + ' шт.' : (r.units ? L.fmtInt(r.units) + ' шт. · ' : '') + (r.runs || 1) + ' прог.') + (r.batches ? ' · партий ' + r.batches : '') + '</div></div>' +
          '<span class="pj-st pj-' + r.status + '">' + esc(stepName(r.status)) + '</span></div>' +
          (r.error ? '<div class="small in-bad">' + esc(r.error) + '</div>' :
            '<div class="pj-prog"><div style="width:' + Math.min(100, r.progress || 0) + '%"></div></div>' +
            '<div class="pj-row"><span>материалы <b>' + pct(r.progress) + '</b> · ' + (r.ready || 0) + ' из ' + (r.positions || 0) + '</span><span>' +
            (r.status === 'collect' ? 'докупить <b>' + isk(r.left_cost) + '</b>' : eta) + '</span></div>' +
            '<div class="pj-row"><span>прибыль <b class="' + cls(r.profit) + '">' + isk(r.profit) + '</b>' + (r.margin !== null && r.margin !== undefined ? ' · ' + pct(r.margin) : '') + '</span>' +
            '<span title="Себестоимость штуки по снимкам цен">' + spark(r.spark, 90, 22) + '</span></div>') +
          '</div>';
      }).join('') + '</div>';
    }
    $('pjList').innerHTML = h;
  }

  // ---------- проект ----------
  function drawDetail() {
    var d = Q.d, box = $('pjDetail');
    if (!d || !box) return;
    var p = d.project, c = d.calc, t = d.totals, s = c.settings, prod = c.product;
    Q.charts = {};
    var h = '<section class="panel"><button type="button" class="in-back" id="pjBack">← все производства</button>' +
      '<h2>' + ico(prod.type_id) + esc(p.name) + ' <span class="muted small">' + (c.kind === 'plan' ? 'план · ' + (c.products || []).length + ' прод. · ' + L.fmtInt(prod.units) + ' шт. · ' + (c.mode === 'buy' ? 'компоненты покупаю' : 'полный цикл') :
        L.fmtInt(prod.units) + ' шт. · ' + s.runs + ' прог. · ME ' + s.me + ' / TE ' + s.te) + ' · ' + esc(c.market_name) + '</span></h2>' +
      '<div class="small" id="pjMsg" role="status" aria-live="polite"></div>';
    if (c.warning) h += '<p class="small in-bad">' + esc(c.warning) + '</p>';
    if (c.missing_price && c.missing_price.length) h += '<p class="small" style="color:var(--warn)">Нет цены на рынке: ' + esc(c.missing_price.join(', ')) + '</p>';
    if (p.draft) {
      h += '<div class="pj-draft"><div><b>Расчёт, не закреплён.</b> <span class="small muted">Закрепите — и можно вести склад, этапы, историю цен и партий.</span></div>' +
        '<button type="button" class="btn primary" id="pjPin">📌 Закрепить</button></div>';
    }
    // этапы
    var idx = STEPS.map(function (x) { return x[0]; }).indexOf(p.status);
    if (!p.draft) h += '<ol class="pj-steps">' + STEPS.map(function (st, i) { return '<li class="' + (i < idx ? 'done' : i === idx ? 'now' : '') + '">' + st[1] + '</li>'; }).join('') + '</ol>';
    h += '<div class="controls pj-actions"' + (p.draft ? ' style="display:none"' : '') + '>';
    if (p.status === 'collect') {
      h += '<button type="button" class="btn primary" data-pj-status="building">Запустил производство</button>' +
        (t.progress < 100 ? '<span class="small muted">собрано ' + pct(t.progress) + ' — не хватает ' + (t.positions - t.ready) + ' поз. на ' + isk(t.left_cost) + ' ISK</span>' : '<span class="small in-good">Всё собрано — можно запускать.</span>');
    } else if (p.status === 'building') {
      var now = Date.now() / 1000, left = d.eta ? d.eta - now : null, span = d.eta && p.started ? d.eta - p.started : 0;
      h += '<button type="button" class="btn primary" data-pj-status="done">Готово — продукт получен</button>' +
        '<label class="small muted"><input type="checkbox" id="pjConsume" checked> списать материалы со склада</label>' +
        '<button type="button" class="btn" data-pj-status="collect">Назад к сбору</button>' +
        '<div class="pj-eta" style="flex:1 1 100%"><div class="pj-prog"><div id="pjEtaBar" style="width:' + (span ? Math.min(100, 100 * (now - p.started) / span) : 0) + '%"></div></div>' +
        '<div class="small" id="pjEta">' + (left === null ? '' : left > 0 ? 'Запущено ' + L.fmtDateTime(p.started) + ' · готово через <b>' + L.fmtDur(Math.round(left)) + '</b> (' + L.fmtDateTime(d.eta) + ')' : '<b class="in-good">Должно быть готово</b> — заберите продукт из работ.') + '</div></div>';
    } else {
      h += '<button type="button" class="btn primary" data-pj-status="collect">Ещё партию</button><span class="small muted">Готово ' + (p.finished ? L.fmtDateTime(p.finished) : '') + '. Остатки материалов на складе сохранены.</span>';
    }
    h += '</div>';
    // плитки
    var tile = ELW.tile;
    h += '<div class="tiles">' +
      tile('Материалы собраны', pct(t.progress), t.ready + ' из ' + t.positions + ' позиций', t.progress >= 100 ? 'in-good' : '') +
      tile('Докупить', isk(t.left_cost), L.fmtInt(t.left_volume) + ' м³', t.left_cost > 0 ? '' : 'in-good') +
      (d.raw && d.raw.totals.minerals ? tile('Минералы собраны', pct(d.raw.totals.minerals.progress), 'базовые руды · докупить ' + isk(d.raw.totals.minerals.left_cost), d.raw.totals.minerals.progress >= 100 ? 'in-good' : '') : '') +
      (d.raw ? tile('Сырьё собрано', pct(d.raw.totals.progress), 'если строить всё · докупить ' + isk(d.raw.totals.left_cost), d.raw.totals.progress >= 100 ? 'in-good' : '') : '') +
      tile('Себестоимость', isk(t.cost), 'за штуку ' + isk(t.per_unit)) +
      tile('Прибыль', isk(t.profit), t.margin !== null && t.margin !== undefined ? 'маржа ' + pct(t.margin) : '', cls(t.profit)) +
      (c.kind === 'plan' ? tile('Выручка', isk(t.revenue), 'ROI ' + pct(t.roi)) : tile('Цена продукта', isk(prod.price), 'за штуку · ' + c.market_name)) +
      tile('Время', L.fmtDur(Math.round(t.top_time || 0)), t.jobs_total > 1 ? 'работ готово ' + t.jobs_done + ' из ' + t.jobs_total : '') + '</div>';

    // диаграммы
    var mats = d.materials.slice().sort(function (a, b) { return (b.qty * (b.price || 0)) - (a.qty * (a.price || 0)); });
    var got = [{ v: t.have_cost, c: 'var(--good)', label: 'есть на складе' }, { v: t.left_cost, c: 'var(--bad)', label: 'докупить' }];
    var struct = mats.slice(0, 6).map(function (m, i) { return { v: (m.price || 0) * m.qty, c: COLORS[i], label: m.name }; });
    var rest = mats.slice(6).reduce(function (a, m) { return a + (m.price || 0) * m.qty; }, 0);
    if (rest) struct.push({ v: rest, c: COLORS[6], label: 'прочие материалы (' + (mats.length - 6) + ')' });
    if (t.jobs) struct.push({ v: t.jobs, c: COLORS[7], label: 'стоимость работ' });
    var structTotal = struct.reduce(function (a, x) { return a + x.v; }, 0);
    var money = [{ v: t.materials, c: 'var(--accent)', label: 'материалы' }, { v: t.jobs, c: '#7f8c8d', label: 'работы' },
      { v: t.fees, c: 'var(--warn)', label: 'налоги и брокер' }, { v: t.profit > 0 ? t.profit : 0, c: 'var(--good)', label: 'прибыль' }];
    if (d.prices) {
      h += fold('charts', 'Диаграммы', '<div class="pj-charts">' +
        '<div class="pj-box"><h3>Собрано материалов</h3><div class="pj-dn">' + donut(got, pct(t.progress), 'по стоимости') + legend(got, t.need_cost) + '</div></div>' +
        (d.raw ? '<div class="pj-box"><h3>Сырьё собрано</h3><div class="pj-dn">' + donut([{ v: d.raw.totals.have_cost, c: 'var(--good)', label: 'есть на складе' }, { v: d.raw.totals.left_cost, c: 'var(--bad)', label: 'докупить' }],
          pct(d.raw.totals.progress), 'сырьё') + legend([{ v: d.raw.totals.have_cost, c: 'var(--good)', label: 'есть на складе' }, { v: d.raw.totals.left_cost, c: 'var(--bad)', label: 'докупить' }], d.raw.totals.need_cost) + '</div></div>' : '') +
        '<div class="pj-box"><h3>Из чего себестоимость</h3><div class="pj-dn">' + donut(struct, isk(structTotal), 'ISK') + legend(struct, structTotal) + '</div></div>' +
        '<div class="pj-box"><h3>Куда уходит выручка</h3>' + (t.revenue ? '<div class="pj-rev">' + isk(t.revenue) + ' <span class="muted small">ISK выручка</span></div>' + stack(money) + legend(money, t.revenue) +
          (t.profit < 0 ? '<div class="small in-bad" style="margin-top:6px">Убыток ' + isk(-t.profit) + ' ISK: себестоимость выше выручки.</div>' : '') : '<p class="small muted">Нет цены продукта.</p>') + '</div>' +
        '</div>');
    }

    // план: продукты по отдельности
    if (c.kind === 'plan' && c.products) {
      h += fold('products', 'Продукты <span class="n">(' + c.products.length + ') · ROI ' + pct(t.roi) + '</span>', '<div class="tw"><table><thead><tr><th class="l">Продукт</th><th>Нужно</th><th>Выйдет</th><th>Время</th>' +
        '<th>Себест./шт.</th><th>Выручка/шт.</th><th>Прибыль</th><th>Маржа</th><th>ROI</th></tr></thead><tbody>' + c.products.map(function (x) {
          return '<tr class="' + (x.profit > 0 ? 'in-rgood' : x.profit < 0 ? 'in-rbad' : '') + '"><td class="l">' + ico(x.type_id) + ELW_INDUSTRY.cp(x.name) + '</td><td>' + esc(L.fmtInt(x.qty)) + '</td><td>' + esc(L.fmtInt(x.made)) + '</td>' +
            '<td>' + esc(L.fmtDur(Math.round(x.time || 0))) + '</td><td>' + esc(isk(x.unit_cost)) + '</td><td>' + esc(isk(x.unit_net)) + '</td>' +
            '<td class="' + cls(x.profit) + '">' + esc(isk(x.profit)) + '</td><td>' + esc(pct(x.margin)) + '</td><td>' + esc(pct(x.roi)) + '</td></tr>';
        }).join('') + '</tbody></table></div>');
    }
    // продукт: продажа своим ордером и мгновенно
    if (c.kind !== 'plan' && c.compare) {
      var col = function (title, x, color) {
        var row = function (k, v, cl) { return '<dt' + (cl ? ' class="' + cl + '"' : '') + '>' + k + '</dt><dd' + (cl ? ' class="' + cl + '"' : '') + '>' + v + '</dd>'; };
        return '<div style="--c:' + color + '"><h3>' + title + '</h3><dl>' + row('Цена продукта', isk(x.price)) + row('Выручка', isk(x.revenue)) +
          row('Налоги и брокер', x.fees === null || x.fees === undefined ? '—' : '−' + isk(x.fees)) + row('Себестоимость', t.cost === null ? '—' : '−' + isk(t.cost)) +
          row('Прибыль', '<span class="' + cls(x.profit) + '">' + isk(x.profit) + '</span>', 'tot') + row('ISK в час', isk(x.isk_hour)) + row('Маржа', pct(x.margin)) + '</dl></div>';
      };
      h += fold('cmp', 'Продажа: своим ордером и мгновенно', '<div class="in-cmp" style="margin-top:4px">' + col('Своим ордером', c.compare.sell || {}, 'var(--good)') + col('Мгновенно', c.compare.buy || {}, 'var(--accent)') + '</div>');
    }
    // продукт: дерево материалов — что строю сам
    if (c.kind !== 'plan' && c.tree && c.tree.some(function (m) { return m.buildable; })) {
      var nb = c.tree.filter(function (m) { return m.built; }).length;
      h += fold('tree', 'Что строю сам <span class="n">— отмечено ' + nb + '; остальное покупается</span>', '<div class="tw"><table><thead><tr><th class="l">Материал</th><th>Нужно</th><th>Строю сам</th></tr></thead><tbody>' +
        c.tree.map(function (m) {
          return '<tr class="' + (m.built ? 'in-built' : '') + '"><td class="l"><span style="padding-left:' + (m.depth * 22) + 'px">' + ico(m.type_id) + ELW_INDUSTRY.cp(m.name) + '</span>' +
            (m.built ? '<div class="in-sub" style="padding-left:' + (m.depth * 22 + 25) + 'px">' + L.fmtInt(m.runs) + ' прог. → ' + L.fmtInt(m.out) + ' шт.' + (m.out > m.qty ? ', останется ' + L.fmtInt(m.out - m.qty) : '') + '</div>' : '') + '</td>' +
            '<td>' + esc(L.fmtInt(m.qty)) + '</td><td>' + (m.buildable ? '<input type="checkbox" data-pj-build="' + m.type_id + '"' + (m.built ? ' checked' : '') + ' aria-label="Строить ' + esc(m.name) + ' самому">' + (m.kind === 'r' ? ' <span class="in-sub">реакция</span>' : '') :
              '<span class="in-sub" title="Для этого материала нет чертежа: его добывают, получают переработкой, на планетах или с NPC">не строится</span>') + '</td></tr>';
        }).join('') + '</tbody></table></div>');
    }
    // дерево строительства: схема и список (tree.js)
    if (ELW_INDUSTRY.tree) h += fold('treebox', 'Дерево строительства <span class="n">— что из чего строится и что уже собрано</span>', '<div id="pjTree"></div>');
    // материалы (что покупаем по плану) и сырьё (если строить всё самому)
    function matTable(list, fkey) {
      var f = Q[fkey] || 'all';
      var pass = function (m, x) { return x === 'all' || (x === 'min' ? m.mineral : x === 'left' ? m.left > 0 : m.left === 0); };
      var shown = list.filter(function (m) { return pass(m, f); });
      shown.sort(function (a, b) { return (b.left > 0) - (a.left > 0) || (b.left_cost || 0) - (a.left_cost || 0) || a.name.localeCompare(b.name); });
      return '<div class="controls" style="margin:4px 0 8px">' +
        ['all', 'min', 'left', 'ready'].filter(function (x) { return x !== 'min' || list.some(function (m) { return m.mineral; }); }).map(function (x) {
          var n = list.filter(function (m) { return pass(m, x); }).length;
          return '<button type="button" class="in-chip' + (f === x ? ' on' : '') + '" data-pj-filter="' + fkey + ':' + x + '">' + { all: 'Все', min: 'Минералы', left: 'Не хватает', ready: 'Собрано' }[x] + '<span class="n">' + n + '</span></button>'; }).join('') +
        '<span style="flex:1"></span><button type="button" class="btn" data-pj-copyleft="' + fkey + '"' + (list.some(function (m) { return m.left; }) ? '' : ' disabled') + '>Скопировать, что докупить</button>' +
        '<button type="button" class="btn" data-pj-copynames="' + fkey + '" title="Только названия, по одному в строке">Скопировать названия</button></div>' +
        '<div class="tw"><table class="pj-mats"><thead><tr><th class="l">Материал <span class="in-sub">(нажмите — скопировать)</span></th><th>Нужно</th><th>Есть</th><th>Осталось</th><th class="l" style="min-width:120px">Собрано</th><th>Цена</th><th>Докупить за</th></tr></thead><tbody>' +
        shown.map(function (m) {
          return '<tr class="' + (m.left ? '' : 'in-rgood') + '"><td class="l">' + ico(m.type_id) + ELW_INDUSTRY.cp(m.name) + '</td><td>' + esc(L.fmtInt(m.qty)) + '</td>' +
            '<td><input class="pj-have" data-pj-have="' + m.type_id + '" value="' + (m.have ? esc(L.fmtInt(m.have)) : '') + '" placeholder="0" inputmode="numeric" aria-label="Есть: ' + esc(m.name) + '"></td>' +
            '<td>' + (m.left ? '<b class="in-bad">' + esc(L.fmtInt(m.left)) + '</b>' : '<span class="in-good">✓</span>') + (m.extra ? '<div class="in-sub">лишних ' + esc(L.fmtInt(m.extra)) + '</div>' : '') + '</td>' +
            '<td class="l"><div class="pj-prog sm"><div style="width:' + Math.min(100, m.pct) + '%"></div></div><span class="in-sub">' + pct(m.pct) + '</span></td>' +
            '<td>' + esc(isk(m.price)) + '</td><td>' + (m.left ? esc(isk(m.left_cost)) : '—') + '</td></tr>';
        }).join('') + (shown.length ? '' : '<tr><td colspan="7" class="muted l">Ничего.</td></tr>') + '</tbody></table></div>';
    }
    var tools = '<div class="controls" style="margin:4px 0 8px"><button type="button" class="btn" id="pjPasteBtn">Вставить склад из игры</button>' +
      '<button type="button" class="btn" id="pjClear" title="Обнулить «Есть» у всех материалов и сырья">Обнулить склад</button>' +
      '<span class="small muted">Склад общий для материалов и сырья: вставка из игры узнаёт и то и другое.</span></div>' +
      '<div id="pjPaste"' + (Q.paste ? '' : ' hidden') + ' class="pj-paste"><div class="small muted">В игре откройте ангар или контейнер, выделите предметы (Ctrl+A), скопируйте (Ctrl+C) и вставьте сюда. Подойдёт и список «Название количество» построчно; названия — на английском или русском.</div>' +
      '<textarea id="pjPasteText" rows="6" placeholder="Tritanium&#9;1 200 000&#10;Pyerite&#9;300 000" aria-label="Склад из игры"></textarea>' +
      '<div class="controls"><label class="small"><input type="radio" name="pjPm" value="set" checked> заменить «Есть»</label><label class="small"><input type="radio" name="pjPm" value="add"> прибавить к «Есть»</label>' +
      '<button type="button" class="btn primary" id="pjPasteGo">Применить</button></div></div>';
    h += tools;
    h += fold('mats', 'Материалы <span class="n">— что покупаете по плану: собрано ' + pct(t.progress) + ', докупить ' + isk(t.left_cost) + ' ISK</span>', matTable(d.materials, 'filter'));
    if (d.raw) {
      var rt = d.raw.totals;
      h += fold('raw', 'Сырьё <span class="n">— если строить все компоненты самому: собрано ' + pct(rt.progress) + ', докупить ' + isk(rt.left_cost) + ' ISK</span>',
        '<div class="pj-rawbar">' + (rt.minerals ? '<div class="small muted">Минералы — базовые руды</div><div class="pj-prog big min"><div style="width:' + Math.min(100, rt.minerals.progress) + '%"></div><span>' + pct(rt.minerals.progress) + ' · ' +
          rt.minerals.ready + ' из ' + rt.minerals.positions + ' · докупить ' + isk(rt.minerals.left_cost) + ' ISK</span></div>' : '') +
        '<div class="small muted">Всё сырьё</div><div class="pj-prog big"><div style="width:' + Math.min(100, rt.progress) + '%"></div><span>' + pct(rt.progress) + '</span></div>' +
        '<div class="pj-row"><span>собрано позиций <b>' + rt.ready + ' из ' + rt.positions + '</b> · по количеству <b>' + pct(rt.progress_qty) + '</b></span>' +
        '<span>докупить <b>' + isk(rt.left_cost) + '</b> ISK · ' + L.fmtInt(rt.left_volume) + ' м³</span></div>' +
        '<div class="pj-row"><span>себестоимость при постройке всего <b>' + isk(rt.cost) + '</b> (работы ' + isk(rt.jobs) + ', ' + d.raw.jobs + ' работ)</span>' +
        '<span>против покупки компонентов <b class="' + cls((t.cost || 0) - (rt.cost || 0)) + '">' + (rt.cost !== null && t.cost !== null ? ((t.cost - rt.cost) >= 0 ? 'дешевле на ' : 'дороже на ') + isk(Math.abs(t.cost - rt.cost)) : '—') + '</b></span></div></div>' +
        rawBars(d.raw.materials) + matTable(d.raw.materials, 'rfilter'));
    }

    // работы
    if (d.jobs.length) {
      h += fold('jobs', 'Работы <span class="n">— готово ' + t.jobs_done + ' из ' + t.jobs_total + '</span>',
        '<div class="tw"><table><thead><tr><th>Готово</th><th class="l">Что</th><th>Прогонов</th><th>Выйдет</th><th>Время</th><th>Стоимость работы</th></tr></thead><tbody>' +
        d.jobs.map(function (j) {
          return '<tr class="' + (j.done ? 'in-rgood' : '') + '"><td><input type="checkbox" data-pj-job="' + esc(j.key) + '"' + (j.done ? ' checked' : '') + ' aria-label="Готово: ' + esc(j.name) + '"></td>' +
            '<td class="l"><span style="padding-left:' + (j.depth * 22) + 'px">' + ico(j.type_id) + ELW_INDUSTRY.cp(j.name) + '</span>' + (j.kind === 'r' ? ' <span class="in-sub">реакция</span>' : '') + '</td>' +
            '<td>' + esc(L.fmtInt(j.runs)) + '</td><td>' + esc(L.fmtInt(j.out)) + '</td><td>' + esc(L.fmtDur(Math.round(j.time))) + '</td><td>' + esc(isk(j.cost)) + '</td></tr>';
        }).join('') + '</tbody></table></div>');
    }

    // цена продукта за 90 дней (в плане — выбранного продукта)
    var ser = d.series || [];
    var pick = c.kind === 'plan' && c.products && c.products.length > 1 ? '<div class="in-chips" style="margin:2px 0 6px">' + c.products.map(function (x) {
      return '<button type="button" class="in-chip' + (x.type_id === d.series_tid ? ' on' : '') + '" data-pj-tid="' + x.type_id + '">' + esc(x.name) + '</button>'; }).join('') + '</div>' : '';
    if (ser.length > 1) {
      var ts = function (dt) { return Date.parse(dt + 'T00:00:00Z') / 1000; };
      var avg = ser.map(function (r) { return [ts(r[0]), r[1]]; });
      var last30 = ser.slice(-30), prev = ser.length > 30 ? ser[ser.length - 31][1] : ser[0][1], lastP = ser[ser.length - 1][1];
      var vol30 = last30.reduce(function (a, r) { return a + r[4]; }, 0) / last30.length;
      var stats = '<div class="pj-stats"><span>средняя за 90 дн. <b>' + isk(ser.reduce(function (a, r) { return a + r[1]; }, 0) / ser.length) + '</b></span>' +
        '<span>за 30 дн. <b class="' + cls(lastP - prev) + '">' + (prev ? (lastP >= prev ? '+' : '') + pct(100 * (lastP - prev) / prev) : '—') + '</b></span>' +
        '<span>продаётся в день <b>≈ ' + L.fmtInt(Math.round(vol30)) + '</b></span>' +
        (unitCost(c, t, d.series_tid) ? '<span>ваша себестоимость <b>' + isk(unitCost(c, t, d.series_tid)) + '</b></span>' : '') + '</div>';
      h += fold('price', 'Цена ' + (c.kind === 'plan' ? 'продукта' : 'продукта') + ' — ' + ser.length + ' дн. с торгами <span class="n">— ' + esc(c.market_name.replace(' 4-4', '')) + ', регион</span>', pick + stats +
        lines('pjPrice', { label: 'Цена продукта по дням', h: 230, series: [
          { name: 'средняя цена', c: 'var(--accent)', pts: avg, lo: ser.map(function (r) { return [ts(r[0]), r[2]]; }), hi: ser.map(function (r) { return [ts(r[0]), r[3]]; }) },
          { name: 'себестоимость штуки', c: 'var(--warn)', dash: true, pts: unitCost(c, t, d.series_tid) ? [[avg[0][0], unitCost(c, t, d.series_tid)], [avg[avg.length - 1][0], unitCost(c, t, d.series_tid)]] : [] }
        ], bars: ser.map(function (r) { return [ts(r[0]), r[4]]; }), barsName: 'продано за день',
          xfmt: function (x, full) { var dd = new Date(x * 1000); return ('0' + dd.getUTCDate()).slice(-2) + '.' + ('0' + (dd.getUTCMonth() + 1)).slice(-2) + (full ? '.' + dd.getUTCFullYear() : ''); } }) +
        '<div class="small muted">Полоса — разброс цен за день (мин–макс), столбики — сколько продано. Пунктир — ваша себестоимость: всё, что выше, — прибыль.</div>');
    }
    // снимки проекта
    var sn = d.snaps || [];
    if (sn.length > 1) {
      h += fold('snaps', 'Себестоимость и цена со дня закрепления <span class="n">— ' + sn.length + ' снимков, раз в час, пока открыт трекер</span>',
        lines('pjSnaps', { label: 'Себестоимость штуки и цена продукта', h: 200, series: [
          { name: 'цена продукта', c: 'var(--accent)', pts: sn.map(function (x) { return [x[0], x[3]]; }) },
          { name: 'себестоимость штуки', c: 'var(--warn)', pts: sn.map(function (x) { return [x[0], x[2]]; }) },
          { name: 'докупить', c: 'var(--bad)', dash: true, pts: sn.map(function (x) { return [x[0], x[4]]; }) }
        ], xfmt: function (x, full) { return full ? L.fmtDateTime(x) : L.fmtDate(x); } }), false);
    }
    // партии
    var bt = p.batches || [];
    if (bt.length) {
      var tp = bt.reduce(function (a, b) { return a + (b.profit || 0); }, 0), tu = bt.reduce(function (a, b) { return a + (b.units || 0); }, 0);
      var maxAbs = Math.max.apply(null, bt.map(function (b) { return Math.abs(b.profit || 0); })) || 1;
      h += fold('batches', 'Готовые партии <span class="n">— ' + bt.length + ', ' + L.fmtInt(tu) + ' шт., прибыль ' + isk(tp) + ' ISK</span>',
        (bt.length > 1 ? '<div class="pj-bars" role="img" aria-label="Прибыль по партиям">' + bt.slice(-30).map(function (b) {
          return '<div title="' + esc(L.fmtDateTime(b.t) + ': ' + isk(b.profit) + ' ISK') + '"><span style="height:' + Math.max(2, 100 * Math.abs(b.profit || 0) / maxAbs) + '%;background:' + ((b.profit || 0) >= 0 ? 'var(--good)' : 'var(--bad)') + '"></span></div>';
        }).join('') + '</div>' : '') +
        '<div class="tw"><table><thead><tr><th class="l">Когда</th><th>Штук</th><th>Себестоимость</th><th>За штуку</th><th>Цена тогда</th><th>Прибыль</th><th>Строилось</th></tr></thead><tbody>' +
        bt.slice().reverse().map(function (b) {
          return '<tr><td class="l">' + esc(L.fmtDateTime(b.t)) + '</td><td>' + esc(L.fmtInt(b.units)) + '</td><td>' + esc(isk(b.cost)) + '</td><td>' + esc(isk(b.per_unit)) + '</td><td>' + esc(isk(b.price)) +
            '</td><td class="' + cls(b.profit) + '">' + esc(isk(b.profit)) + '</td><td>' + (b.time ? esc(L.fmtDur(Math.round(b.time))) : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>');
    }
    // настройки и журнал
    h += fold('set', 'Настройки расчёта <span class="n">— прогоны, ME/TE, где строим, навыки, рынок</span>', '<div id="pjSetBox">' +
      '<div class="in-grid"><label class="small muted">Название<input id="pjName" maxlength="80" value="' + esc(p.name) + '"></label>' +
      (c.kind === 'plan' ? '<label class="small muted">Как строим' + ELW_INDUSTRY.help('pl_mode') + '<select id="pjMode"><option value="full"' + (c.mode !== 'buy' ? ' selected' : '') + '>полный цикл</option>' +
        '<option value="buy"' + (c.mode === 'buy' ? ' selected' : '') + '>покупаю компоненты</option></select></label>' : '') + '</div>' +
      ELW_INDUSTRY.form('pjS', c.kind === 'plan' ? { runs: false, me: false } : {}) +
      '<div class="controls" style="margin-top:8px"><button type="button" class="btn primary" id="pjSaveSet">Пересчитать</button>' +
      '<label class="small muted"><input type="checkbox" id="pjAsDef"> и сделать настройками по умолчанию (кроме прогонов и ME/TE)</label><span style="flex:1"></span>' +
      '<button type="button" class="btn" id="pjDel" style="color:var(--bad)">' + (p.draft ? 'Закрыть расчёт' : 'Открепить') + '</button></div></div>', !p.draft ? false : true);
    h += fold('log', 'Журнал <span class="n">(' + (p.log || []).length + ')</span>', '<ul class="pj-log">' + (p.log || []).slice().reverse().map(function (x) {
      return '<li><span class="muted">' + esc(L.fmtDateTime(x[0])) + '</span> ' + esc(x[1]) + '</li>'; }).join('') + '</ul>', false);
    box.innerHTML = h + '</section>';
    if ($('pjSetBox')) ELW_INDUSTRY.fillForm('pjS', s);
    if (ELW_INDUSTRY.tree && $('pjTree')) ELW_INDUSTRY.tree.mount(d);
    Q.dirty = false;
    Object.keys(Q.charts).forEach(drawLines);
  }
  function unitCost(c, t, tid) {
    if (c.kind !== 'plan') return t.per_unit;
    var x = (c.products || []).filter(function (q) { return q.type_id === tid; })[0];
    return x ? x.unit_cost : null;
  }
  function tickEta() {                                         // обратный отсчёт без полной перерисовки
    var d = Q.d, el = $('pjEta');
    if (!d || !el || d.project.status !== 'building' || !d.eta) return;
    var now = Date.now() / 1000, left = d.eta - now, span = d.eta - d.project.started;
    el.innerHTML = left > 0 ? 'Запущено ' + esc(L.fmtDateTime(d.project.started)) + ' · готово через <b>' + esc(L.fmtDur(Math.round(left))) + '</b> (' + esc(L.fmtDateTime(d.eta)) + ')' : '<b class="in-good">Должно быть готово</b> — заберите продукт из работ.';
    if ($('pjEtaBar') && span > 0) $('pjEtaBar').style.width = Math.min(100, 100 * (now - d.project.started) / span) + '%';
  }

  // ---------- действия ----------
  function act(body, okText, reloadSeries) {
    flash('Сохраняю…');
    return post(body).then(function (j) {
      if (!j.ok) { flash(j.message || 'Не получилось.'); return j; }
      flash(okText || '');
      if (body.action === 'delete') { closeProject(); return j; }
      loadDetail(reloadSeries === true ? true : false);
      return j;
    }, function () { flash('Нет связи с трекером.'); });
  }
  function pin(product, settings) {
    return post({ action: 'create', product: product, settings: settings || {} }).then(function (j) {
      if (j.ok) { ELW_INDUSTRY.show('proj'); openProject(j.id); }
      return j;
    });
  }
  document.addEventListener('click', function (e) {
    var view = $('inProjView');
    if (!view || !view.contains(e.target)) return;
    var el = e.target.closest('[data-pj-open]');
    if (el) { openProject(el.getAttribute('data-pj-open')); return; }
    if (e.target.id === 'pjBack') { closeProject(); return; }
    if (e.target.id === 'pjAdd' || e.target.id === 'pjCalc') {
      var name = $('pjNew').value.trim();
      if (!name) { flash('Впишите, что строим.'); return; }
      if (e.target.id === 'pjCalc') { draft(name); return; }
      flash('Закрепляю…');
      pin(name, {}).then(function (j) { if (!j.ok) flash(j.message); }, function () { flash('Нет связи с трекером.'); });
      return;
    }
    if (e.target.id === 'dfSave') {
      $('dfMsg').textContent = 'Сохраняю…';
      ELW_INDUSTRY.saveDefaults(ELW_INDUSTRY.readForm('dfS')).then(function (j) {
        $('dfMsg').textContent = j.ok ? 'Сохранено. Новые расчёты, сканер и план считают с этими настройками.' : (j.message || 'Не получилось.');
        if (j.ok) ELW_INDUSTRY.fillForm('dfS', j.settings);
      }, function () { $('dfMsg').textContent = 'Нет связи с трекером.'; });
      return;
    }
    var tidb = e.target.closest('[data-pj-tid]');
    if (tidb && Q.d) {
      var want = +tidb.getAttribute('data-pj-tid');
      api('/api/industry/project?id=' + encodeURIComponent(Q.d.project.id) + '&tid=' + want).then(function (j) { if (j.ok && Q.d) { Q.d = j; drawDetail(); } });
      return;
    }
    var f = e.target.closest('[data-pj-filter]');
    if (f) { var fv = f.getAttribute('data-pj-filter').split(':'); Q[fv[0]] = fv[1]; drawDetail(); return; }
    var st = e.target.closest('[data-pj-status]');
    if (st && Q.d) {
      var to = st.getAttribute('data-pj-status');
      if (to === 'done' && !confirm('Отметить партию готовой?' + ($('pjConsume') && $('pjConsume').checked ? ' Материалы будут списаны со склада.' : ''))) return;
      act({ action: 'status', id: Q.d.project.id, status: to, consume: !$('pjConsume') || $('pjConsume').checked },
        { building: 'Производство запущено.', done: 'Готово! Партия записана.', collect: 'Сбор материалов.' }[to]);
      return;
    }
    if (!Q.d) return;
    var id = Q.d.project.id;
    if (e.target.id === 'pjPasteBtn') { Q.paste = !Q.paste; $('pjPaste').hidden = !Q.paste; if (Q.paste) $('pjPasteText').focus(); return; }
    if (e.target.id === 'pjPasteGo') {
      var mode = (document.querySelector('input[name=pjPm]:checked') || {}).value || 'set';
      flash('Разбираю…');
      post({ action: 'paste', id: id, text: $('pjPasteText').value, mode: mode }).then(function (j) {
        if (!j.ok) { flash(j.message); return; }
        Q.paste = false;
        flash('Найдено материалов проекта: ' + j.matched + ' из ' + j.lines + ' строк.' + (j.skipped.length ? ' Не из этого проекта: ' + j.skipped.slice(0, 8).join(', ') + (j.skipped.length > 8 ? '…' : '') : ''));
        var msg = $('pjMsg').textContent;
        loadDetail(false);
        setTimeout(function () { flash(msg); }, 400);
      }, function () { flash('Нет связи с трекером.'); });
      return;
    }
    if (e.target.id === 'pjClear') { if (confirm('Обнулить «Есть» у всех материалов?')) act({ action: 'clear', id: id }, 'Склад обнулён.'); return; }
    var cl = e.target.closest('[data-pj-copyleft],[data-pj-copynames]');
    if (cl) {
      var raw = (cl.getAttribute('data-pj-copyleft') || cl.getAttribute('data-pj-copynames')) === 'rfilter', list = raw && Q.d.raw ? Q.d.raw.materials : Q.d.materials;
      var text = cl.hasAttribute('data-pj-copyleft') ? list.filter(function (m) { return m.left > 0; }).map(function (m) { return m.name + ' ' + m.left; }).join('\n') :
        list.map(function (m) { return m.name; }).join('\n');
      ELW_INDUSTRY.copyText(text).then(function () {
        flash(cl.hasAttribute('data-pj-copyleft') ? 'Скопировано — вставляется в «Купить несколько» на рынке игры.' : 'Названия скопированы.'); }, function () { flash('Не удалось скопировать.'); });
      return;
    }
    if (e.target.id === 'pjSaveSet') {
      var st = ELW_INDUSTRY.readForm('pjS');
      st.build = Q.d.calc.settings.build || [];
      act({ action: 'settings', id: id, name: $('pjName').value, settings: st, mode: $('pjMode') ? $('pjMode').value : undefined,
        as_default: $('pjAsDef').checked }, 'Пересчитано.', true);
      return;
    }
    if (e.target.id === 'pjPin') { act({ action: 'pin', id: id }, 'Закреплено — теперь можно вести склад и этапы.'); return; }
    if (e.target.id === 'pjDel') {
      if (Q.d.project.draft) { act({ action: 'delete', id: id }); return; }
      if (confirm('Открепить «' + Q.d.project.name + '»? Склад и история проекта будут удалены.')) act({ action: 'delete', id: id });
    }
  });
  document.addEventListener('keydown', function (e) {
    var view = $('inProjView');
    if (!view || !view.contains(e.target)) return;
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-pj-open]')) { e.preventDefault(); openProject(e.target.getAttribute('data-pj-open')); }
    if (e.key === 'Enter' && e.target.id === 'pjNew') $('pjAdd').click();
    if (e.key === 'Enter' && e.target.matches('.pj-have')) e.target.blur();
  });
  document.addEventListener('change', function (e) {
    var view = $('inProjView');
    if (!view || !view.contains(e.target) || !Q.d) return;
    var inp = e.target.closest('[data-pj-have]');
    if (inp) {
      var v = num(inp.value), have = {};
      if (v !== null && (isNaN(v) || v < 0)) { flash('Количество — целое число.'); return; }
      have[inp.getAttribute('data-pj-have')] = v === null ? 0 : Math.floor(v);
      act({ action: 'have', id: Q.d.project.id, have: have }, 'Сохранено.');
      return;
    }
    var bld = e.target.closest('[data-pj-build]');
    if (bld) { act({ action: 'build', id: Q.d.project.id, type_id: +bld.getAttribute('data-pj-build'), on: bld.checked }, bld.checked ? 'Строю сам — пересчитано.' : 'Покупаю — пересчитано.', true); return; }
    if (e.target.closest('#pjSetBox')) { Q.dirty = true; return; }
    var job = e.target.closest('[data-pj-job]');
    if (job) act({ action: 'job', id: Q.d.project.id, key: job.getAttribute('data-pj-job'), done: job.checked });
  });
  var sugT = null;
  document.addEventListener('input', function (e) {
    if (!e.target || e.target.id !== 'pjNew') return;
    clearTimeout(sugT);
    var q = e.target.value.trim();
    if (q.length < 2) return;
    sugT = setTimeout(function () {
      api('/api/industry/search?q=' + encodeURIComponent(q)).then(function (j) {
        var dl = $('pjNewList'); if (dl) dl.innerHTML = (j.items || []).map(function (i) { return '<option value="' + esc(i.name) + '"></option>'; }).join('');
      }, function () { });
    }, 250);
  });
  window.addEventListener('resize', function () { Object.keys(Q.charts).forEach(drawLines); });

  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.projects = {
    pin: pin,
    draft: draft,
    build: function (tid, on) {                               // «строю сам / покупаю» из дерева
      if (Q.d) act({ action: 'build', id: Q.d.project.id, type_id: tid, on: on }, on ? 'Строю сам — пересчитано.' : 'Покупаю — пересчитано.', true);
    },
    defaults: function () {                                   // открыть «Настройки по умолчанию» (из сканера и плана)
      shell();
      if (Q.open) closeProject();
      var d = document.querySelector('[data-fold="p_defaults"]');
      if (d) { d.open = true; setTimeout(function () { d.scrollIntoView({ block: 'start' }); }, 50); }
    },
    plan: function (items, mode, name) {                     // «План производства» → закрепить весь план
      return post({ action: 'create', items: items, mode: mode, name: name }).then(function (j) {
        if (j.ok) { ELW_INDUSTRY.show('proj'); openProject(j.id); }
        return j;
      });
    },
    render: function (force) {                               // ядро зовёт каждые 4 с: перерисовка только по делу
      shell();
      var busyInput = document.activeElement && $('inProjView').contains(document.activeElement) && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
      if (Q.open) {
        if (!Q.d || force) { if (!Q.d) loadDetail(); else loadDetail(false); return; }
        tickEta();
        if (!busyInput && !Q.paste && !Q.dirty && Date.now() - Q.loaded > 120000) loadDetail(false);      // цены обновляются раз в пару минут
        return;
      }
      if (!Q.list || force || (!busyInput && Date.now() - Q.loaded > 120000)) loadList();
    }
  };
})(window.ELW);
