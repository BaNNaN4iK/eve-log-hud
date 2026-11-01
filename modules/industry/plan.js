// План производства модуля «Производство»: несколько продуктов, общие компоненты, закупка, изобретение, остатки, итог.
(function (ELW) {
  'use strict';
  if (!ELW) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, $ = ELW.$;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var TECH = [['', 'любой'], ['bpo', 'T1 / чертёж с рынка'], ['inv', 'T2 / T3 — изобретение'], ['bpc', 'редкие копии']];
  var P = { built: false, catalog: null, groups: {}, tech: '', q: '', items: [], mode: 'full', name: '', res: null, plans: [], week: {}, busy: false, open: {} };
  try { P.open = JSON.parse(localStorage.getItem('elw.industry.tree.open') || '{}') || {}; } catch (e) { P.open = {}; }
  try {
    var draft = JSON.parse(localStorage.getItem('elw.industry.plan') || '{}');
    if (Array.isArray(draft.items)) P.items = draft.items;
    if (draft.mode === 'buy') P.mode = 'buy';
    if (draft.name) P.name = draft.name;
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.industry.plan', JSON.stringify({ items: P.items, mode: P.mode, name: P.name })); } catch (e) { } }
  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function pct(v) { return v === null || v === undefined ? '—' : String(v).replace('.', ',') + '%'; }
  function cls(v) { return v > 0 ? 'in-good' : v < 0 ? 'in-bad' : ''; }
  function chip(group, value, label, on) { return '<button type="button" class="in-chip' + (on ? ' on' : '') + '" data-' + group + '="' + esc(value) + '">' + label + '</button>'; }
  function ico(t) { return ELW_INDUSTRY.ico(t); }
  function srcBadge(src) {
    return src === 'inv' ? '<span class="sc-badge t2">изобретение</span>' : src === 'bpc' ? '<span class="sc-badge lp">редкая копия</span>' : '';
  }

  function shell() {
    var box = $('inPlanView');
    if (!box || P.built) return;
    P.built = true;
    box.innerHTML = '<div class="pl-layout"><aside class="pl-side panel" aria-label="Чертежи игры">' +
      '<div class="pl-side-hd"><b>Чертежи</b> <span class="small muted" id="plCnt"></span></div>' +
      '<input id="plQ" type="search" placeholder="Поиск чертежа: Caracal, Hobgoblin II…" aria-label="Поиск чертежа" spellcheck="false" class="pl-q">' +
      '<div class="in-chips" id="plTech" style="margin:6px 0"></div><div id="plTree" class="pl-tree" role="tree"></div></aside><div class="pl-main">' +
      '<section class="panel"><h2>План производства <span class="muted small">несколько продуктов сразу: общие компоненты, закупка, изобретение, остатки</span></h2>' +
      '<div class="in-chips"><input id="plName" placeholder="Название плана" aria-label="Название плана" maxlength="80" ' +
      'style="flex:1 1 220px;min-width:0;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px">' +
      '<select id="plSaved" aria-label="Сохранённые планы" style="background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 8px"><option value="">Сохранённые планы…</option></select>' +
      '<button type="button" class="btn" id="plSave">Сохранить</button><button type="button" class="btn" id="plDel" title="Удалить сохранённый план с этим названием">Удалить</button>' +
      '<button type="button" class="btn primary" id="plPin" title="Весь план — в «Ведение производства»: склад, что докупить, этапы, графики">📌 В ведение производства</button></div>' +
      '<div class="in-chips" style="margin-top:10px"><span class="small muted">Как строим' + ELW_INDUSTRY.help('pl_mode') + '</span>' +
      '<span id="plModes" class="in-chips"></span><span id="plMarket" class="small muted" style="margin-left:8px"></span>' +
      '<button type="button" class="btn primary" id="plGo" style="margin-left:auto">Посчитать план</button></div>' +
      '<div class="small" id="plMsg" role="status" aria-live="polite" style="margin-top:6px"></div></section>' +
      '<section class="panel"><h2>Что строим <span class="muted small" id="plCount"></span></h2><div id="plItems"></div>' +
      '<details class="in-sec" id="plFitBox" data-fold="pl_fit"' + (ELW_INDUSTRY.fold('pl_fit', 'x', 'x', false).indexOf(' open') > 0 ? ' open' : '') + '><summary>Вставить фит</summary>' +
      '<div class="small muted" style="margin-top:6px">В игре: окно фитинга → «Копировать в буфер обмена» (формат EFT; подойдёт и Pyfa → Export). Корабль, модули, дроны и груз из фита добавятся в план — всё, что строится по чертежу.</div>' +
      '<textarea id="plFit" rows="7" spellcheck="false" placeholder="[Vexor, PvE]&#10;Drone Damage Amplifier II&#10;…&#10;Hammerhead II x5" aria-label="Фит" ' +
      'style="width:100%;box-sizing:border-box;margin:6px 0;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:12.5px ui-monospace,Consolas,monospace"></textarea>' +
      '<div class="in-chips"><label class="small muted">Сколько фитов <input id="plFitN" value="1" inputmode="numeric" style="width:5em;text-align:right;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:4px 6px"></label>' +
      '<label class="small"><input type="checkbox" id="plFitShip" checked> с кораблём</label>' +
      '<button type="button" class="btn primary" id="plFitGo">Добавить в план</button></div><div class="small" id="plFitMsg" role="status" aria-live="polite" style="margin-top:6px"></div></details>' +
      '</section><div id="plResult"></div></div></div>';
    $('plName').value = P.name;
    var t = null;
    $('plQ').addEventListener('input', function () { var v = this.value; clearTimeout(t); t = setTimeout(function () { P.q = v; drawFound(); }, 150); });
    $('plName').addEventListener('input', function () { P.name = this.value; remember(); });
    $('plGo').addEventListener('click', calc);
    $('plSave').addEventListener('click', function () { savePlan(false); });
    $('plPin').addEventListener('click', function () {
      if (!P.items.length) { $('plMsg').textContent = 'Добавьте в план хотя бы один продукт.'; return; }
      $('plMsg').textContent = 'Закрепляю план…';
      ELW_INDUSTRY.projects.plan(P.items, P.mode, $('plName').value.trim()).then(function (j) { if (!j.ok) $('plMsg').textContent = j.message || 'Не получилось.'; },
        function () { $('plMsg').textContent = 'Нет связи с трекером.'; });
    });
    $('plFitGo').addEventListener('click', addFit);
    $('plDel').addEventListener('click', function () { savePlan(true); });
    $('plSaved').addEventListener('change', function () {
      var p = P.plans.filter(function (x) { return x.name === this.value; }, this)[0];
      if (!p) return;
      P.items = p.items.map(function (i) { return { id: i.id, qty: i.qty }; }); P.mode = p.mode; P.name = p.name; $('plName').value = p.name;
      remember(); drawItems(); drawModes(); calc();
    });
    box.addEventListener('click', onClick);
    box.addEventListener('change', function (e) {
      var q = e.target.closest && e.target.closest('input[data-qty]');
      if (!q) return;
      var id = +q.getAttribute('data-qty'), v = Math.max(1, Math.round(+String(q.value).replace(/\s/g, '').replace(',', '.') || 1));
      P.items.forEach(function (i) { if (i.id === id) i.qty = v; });
      remember(); calc();
    });
    api('/api/industry/catalog').then(function (j) { if (j.ok) { P.catalog = j.items; P.groups = j.groups || {}; buildTree(); drawItems(); drawFound(); } });
    loadPlans();
  }

  // фит EFT → продукты плана (что строится по чертежу)
  function addFit() {
    var msg = $('plFitMsg'), text = $('plFit').value;
    if (!text.trim()) { msg.textContent = 'Вставьте фит.'; return; }
    msg.textContent = 'Разбираю фит…';
    api('/api/industry/fit', { method: 'POST', headers: POST, body: JSON.stringify({ text: text, count: +String($('plFitN').value).replace(/\D/g, '') || 1 }) }).then(function (j) {
      if (!j.ok) { msg.innerHTML = '<span class="in-bad">' + esc(j.message || 'Не получилось.') + '</span>'; return; }
      var added = 0, withShip = $('plFitShip').checked;
      j.items.forEach(function (it) {
        if (!withShip && it.name === j.ship) return;
        var cur = P.items.filter(function (i) { return i.id === it.id; })[0];
        if (cur) cur.qty += it.qty; else P.items.push({ id: it.id, qty: it.qty });
        added++;
      });
      if (!P.name && j.ship) { P.name = j.ship + (j.count > 1 ? ' ×' + j.count : '') + ' — фит'; $('plName').value = P.name; }
      remember(); drawItems(); drawFound();
      var h = '<span class="in-good">' + esc(j.ship || 'Фит') + (j.count > 1 ? ' ×' + j.count : '') + ': добавлено в план ' + added + ' поз.</span>';
      if (j.buy.length) h += '<div class="muted">Без чертежа — только купить: ' + esc(j.buy.map(function (b) { return b.name + ' ×' + b.qty; }).join(', ')) + '</div>';
      if (j.skipped.length) h += '<div style="color:var(--warn)">Не узнал: ' + esc(j.skipped.map(function (b) { return b.name; }).join(', ')) + '</div>';
      msg.innerHTML = h;
      if (P.items.length) calc();
    }, function () { msg.textContent = 'Нет связи с трекером.'; });
  }

  function loadPlans(sel) {
    api('/api/industry/plans').then(function (j) {
      P.plans = j.plans || [];
      $('plSaved').innerHTML = '<option value="">Сохранённые планы…</option>' + P.plans.map(function (p) {
        return '<option value="' + esc(p.name) + '">' + esc(p.name + ' · ' + p.items.length + ' прод.') + '</option>';
      }).join('');
      if (sel) $('plSaved').value = sel;
    });
  }
  function savePlan(del) {
    var name = $('plName').value.trim(), msg = $('plMsg');
    if (!name) { msg.textContent = 'Впишите название плана.'; return; }
    if (del && !confirm('Удалить план «' + name + '»?')) return;
    api('/api/industry/plans', { method: 'POST', headers: POST, body: JSON.stringify({ action: del ? 'delete' : 'save', name: name, items: P.items, mode: P.mode }) })
      .then(function (j) { msg.textContent = j.ok ? (del ? 'План удалён.' : 'План сохранён.') : (j.message || 'Не получилось.'); if (j.ok) loadPlans(del ? '' : name); });
  }

  function onClick(e) {
    if (e.target.id === 'plDefaults') { ELW_INDUSTRY.show('proj'); if (ELW_INDUSTRY.projects) ELW_INDUSTRY.projects.defaults(); return; }
    var g = e.target.closest && e.target.closest('[data-grp]');
    if (g) {
      var gid = g.getAttribute('data-grp');
      P.open[gid] = !isOpen(gid);
      try { localStorage.setItem('elw.industry.tree.open', JSON.stringify(P.open)); } catch (er) { }
      drawFound();
      var ids = (TREE && TREE.items[gid] || []).map(function (r) { return r[0]; });
      if (P.open[gid] && ids.length) {                          // иконки чертежей группы — подкачать и показать
        api('/api/industry/icons', { method: 'POST', headers: POST, body: JSON.stringify({ ids: ids }) }).then(function () { setTimeout(drawFound, 2500); }, function () { });
      }
      return;
    }
    var b = e.target.closest && e.target.closest('[data-tech],[data-mode],[data-add],[data-del]');
    if (!b) return;
    if (b.hasAttribute('data-tech')) { P.tech = b.getAttribute('data-tech'); drawFound(); }
    else if (b.hasAttribute('data-mode')) { P.mode = b.getAttribute('data-mode'); remember(); drawModes(); if (P.items.length) calc(); }
    else if (b.hasAttribute('data-add')) {
      var id = +b.getAttribute('data-add');
      if (!P.items.some(function (i) { return i.id === id; })) P.items.push({ id: id, qty: 1 });
      remember(); drawItems(); drawFound(); calc();
    } else if (b.hasAttribute('data-del')) {
      var d = +b.getAttribute('data-del');
      P.items = P.items.filter(function (i) { return i.id !== d; });
      remember(); drawItems(); drawFound(); if (P.items.length) calc(); else { P.res = null; drawResult(); }
    }
  }

  function info(id) { var c = (P.catalog || []).filter(function (r) { return r[0] === id; })[0]; return c ? { name: c[1], cat: c[2], src: c[3], kind: c[4] } : { name: String(id) }; }
  function drawModes() {
    $('plModes').innerHTML = chip('mode', 'full', 'Полный цикл', P.mode === 'full') + chip('mode', 'buy', 'Покупаю компоненты', P.mode === 'buy');
    var se = (ELW_INDUSTRY.settings && ELW_INDUSTRY.settings()) || {};
    $('plMarket').innerHTML = 'цены: ' + esc({ jita: 'Jita 4-4', amarr: 'Amarr', dodixie: 'Dodixie', rens: 'Rens', hek: 'Hek' }[se.market] || 'Jita 4-4') +
      ' · сооружение, налоги, навыки — <button type="button" class="in-back" id="plDefaults" style="margin:0">настройки по умолчанию</button>';
  }
  function drawItems() {
    $('plCount').textContent = P.items.length ? '(' + P.items.length + ')' : '';
    if (!P.items.length) { $('plItems').innerHTML = '<p class="small muted">Пока пусто. Выберите чертёж в панели слева и нажмите «+» — или вставьте фит.</p>'; return; }
    var res = {};
    ((P.res && P.res.products) || []).forEach(function (p) { res[p.type_id] = p; });
    $('plItems').innerHTML = sec('items', 'Продукты <span class="n">(' + P.items.length + ')</span>', table('plProd', P.items.map(function (i) {
      var p = res[i.id] || {}, inf = info(i.id), w = P.week[i.id];
      return { id: i.id, qty: i.qty, name: inf.name, src: inf.src, kind: inf.kind, p: p, w: w,
               profit: p.profit, margin: p.margin, roi: p.roi };
    }), [
      { k: 'name', t: 'Продукт', l: 1, f: function (r) { return ico(r.id) + esc(r.name) + srcBadge(r.src) + (r.kind === 'r' ? '<span class="sc-badge">реакция</span>' : ''); } },
      { k: '', t: 'Нужно, шт.', f: function (r) { return '<input data-qty="' + r.id + '" value="' + r.qty + '" inputmode="numeric" aria-label="Сколько нужно: ' + esc(r.name) + '" style="width:7em;text-align:right;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:3px 6px">'; } },
      { k: '', t: 'Выйдет', title: 'С округлением до целых прогонов', f: function (r) { return r.p.made !== undefined ? esc(L.fmtInt(r.p.made)) : '…'; } },
      { k: '', t: 'Время', title: 'Сама работа · вся цепочка подряд', f: function (r) { return r.p.time !== undefined ? esc(L.fmtDur(Math.round(r.p.time))) + '<div class="in-sub">цепочка ' + esc(L.fmtDur(Math.round(r.p.chain_time || 0))) + '</div>' : '…'; } },
      { k: '', t: 'Себест./шт.', f: function (r) { return esc(isk(r.p.unit_cost)); } },
      { k: '', t: 'Выручка/шт.', title: 'После налога и брокера', f: function (r) { return esc(isk(r.p.unit_net)); } },
      { k: 'profit', t: 'Прибыль', f: function (r) { return '<span class="' + cls(r.profit) + '">' + esc(isk(r.profit)) + '</span>'; } },
      { k: 'margin', t: 'Маржа', f: function (r) { return esc(pct(r.margin)); } },
      { k: 'roi', t: 'ROI', title: 'Прибыль к вложенному', f: function (r) { return esc(pct(r.roi)); } },
      { k: '', t: 'Спрос, неделя', f: function (r) { return r.w ? esc(L.fmtInt(r.w.week)) + '<div class="in-sub">вчера ' + esc(L.fmtInt(r.w.last)) + '</div>' : '<span class="muted">…</span>'; } },
      { k: '', t: '', f: function (r) { return '<button type="button" class="btn" data-del="' + r.id + '" aria-label="Убрать ' + esc(r.name) + '">×</button>'; } }
    ], { rowAttrs: function (r) { return r.profit > 0 ? ' class="in-rgood"' : r.profit < 0 ? ' class="in-rbad"' : ''; } }), true);
  }
  // ----- дерево чертежей: группы рынка игры, как в окне рынка -----
  var TREE = null;
  function buildTree() {
    var kids = {}, items = {};
    Object.keys(P.groups).forEach(function (g) { var par = P.groups[g][0] ? String(P.groups[g][0]) : ''; (kids[par] = kids[par] || []).push(g); });
    (P.catalog || []).forEach(function (r) { var g = r[5] && P.groups[r[5]] ? String(r[5]) : 'none'; (items[g] = items[g] || []).push(r); });
    if (items.none) (kids[''] = kids[''] || []).push('none');
    Object.keys(kids).forEach(function (k) { kids[k].sort(function (a, b) { return gname(a).localeCompare(gname(b), 'ru'); }); });
    TREE = { kids: kids, items: items };
  }
  function gname(g) { return g === 'none' ? 'Нет на рынке' : (P.groups[g] || [0, g])[1]; }
  function isOpen(g) { return !!P.open[g]; }
  function pass(r, q) {
    if (P.tech && !(r[3] === P.tech || (P.tech === 'bpc' && r[3] === 'lp'))) return false;
    return !q || r[1].toLowerCase().indexOf(q) >= 0 || (r[6] && r[6].toLowerCase().indexOf(q) >= 0);
  }
  function drawFound() {
    $('plTech').innerHTML = TECH.map(function (c) { return chip('tech', c[0], c[1], c[0] === P.tech); }).join('');
    var box = $('plTree');
    if (!P.catalog || !TREE) { box.innerHTML = '<p class="small muted">Загружаю чертежи…</p>'; return; }
    var q = P.q.trim().toLowerCase(), have = {}, count = {}, total = 0, shown = 0;
    P.items.forEach(function (i) { have[i.id] = 1; });
    function cnt(g) {                                          // сколько чертежей в ветке (с учётом поиска и фильтра)
      if (count[g] !== undefined) return count[g];
      var n = (TREE.items[g] || []).filter(function (r) { return pass(r, q); }).length;
      (TREE.kids[g] || []).forEach(function (k) { n += cnt(k); });
      return (count[g] = n);
    }
    (TREE.kids[''] || []).forEach(function (g) { total += cnt(g); });
    var h = '';
    function node(g, depth) {
      var n = cnt(g);
      if (!n) return;
      var open = q ? true : isOpen(g);                           // при поиске ветки с находками раскрыты
      h += '<div class="pl-g" style="padding-left:' + (depth * 14) + 'px"><button type="button" class="pl-gb" data-grp="' + esc(g) + '" role="treeitem" aria-expanded="' + open + '">' +
        '<span class="pl-arr">' + (open ? '▾' : '▸') + '</span>' + esc(gname(g)) + ' <span class="pl-n">' + n + '</span></button></div>';
      if (!open) return;
      (TREE.kids[g] || []).forEach(function (k) { node(k, depth + 1); });
      (TREE.items[g] || []).filter(function (r) { return pass(r, q); }).forEach(function (r) {
        if (shown++ > 600) return;
        h += '<div class="pl-i" style="padding-left:' + ((depth + 1) * 14 + 16) + 'px" title="' + esc(r[1] + (r[6] && r[6] !== r[1] ? ' — ' + r[6] : '')) + '">' +
          ico(r[0]) + '<span class="pl-in">' + esc(r[1]) + '</span>' + srcBadge(r[3]) +
          (have[r[0]] ? '<span class="in-sub">в плане</span>' : '<button type="button" class="btn pl-add" data-add="' + r[0] + '" aria-label="Добавить ' + esc(r[1]) + '">+</button>') + '</div>';
      });
    }
    (TREE.kids[''] || []).forEach(function (g) { node(g, 0); });
    $('plCnt').textContent = q || P.tech ? 'найдено ' + L.fmtInt(total) : L.fmtInt(total);
    box.innerHTML = h || '<p class="small muted">Ничего не нашлось.</p>';
  }

  function calc() {
    if (!P.items.length) return;
    if (P.busy) { P.again = true; return; }
    P.busy = true;
    $('plMsg').textContent = 'Считаю…';
    var settings = ELW_INDUSTRY.settings ? ELW_INDUSTRY.settings() : {};
    delete settings.build;
    api('/api/industry/plan', { method: 'POST', headers: POST, body: JSON.stringify({ items: P.items, mode: P.mode, settings: settings }) }).then(function (j) {
      P.busy = false;
      if (P.again) { P.again = false; calc(); return; }
      if (!j.ok) { $('plMsg').innerHTML = '<span class="in-bad">' + esc(j.message || 'Не получилось.') + '</span>'; return; }
      $('plMsg').textContent = j.prices ? '' : 'Онлайн-функции выключены: показаны количества без цен.';
      P.res = j; drawItems(); drawResult();
      var ids = j.products.map(function (p) { return p.type_id; }).filter(function (id) { return !P.week[id]; });
      if (ids.length) api('/api/industry/history?market=' + encodeURIComponent(j.settings.market) + '&ids=' + ids.join(',')).then(function (h) {
        Object.keys(h.history || {}).forEach(function (k) { P.week[+k] = h.history[k]; });
        drawItems();
      });
      setTimeout(function () { if (P.res === j) drawResult(); }, 4000);
    }, function () { P.busy = false; $('plMsg').textContent = 'Нет связи с трекером.'; });
  }

  function sec(key, title, body, open) { return ELW_INDUSTRY.fold('pl_' + key, title, body, open); }
  function drawResult() {
    var r = P.res, box = $('plResult');
    if (!r) { box.innerHTML = ''; return; }
    var t = r.totals;
    var line = function (k, v, c, note) { return '<dt' + (c ? ' class="' + c + '"' : '') + '>' + k + (note ? '<div class="in-sub">' + note + '</div>' : '') + '</dt><dd' + (c ? ' class="' + c + '"' : '') + '>' + v + '</dd>'; };
    var h = '<section class="panel"><h2>Итог плана <span class="muted small">' + (r.mode === 'full' ? 'полный цикл' : 'компоненты покупаются') + ' · ' + esc(r.market_name) + '</span></h2>';
    var sum = '<div class="tiles">' +
      '<div class="tile"><div class="k">Прибыль</div><div class="v ' + cls(t.profit) + '">' + esc(isk(t.profit)) + '</div><div class="s">ROI ' + esc(pct(t.roi)) + '</div></div>' +
      '<div class="tile"><div class="k">Себестоимость</div><div class="v">' + esc(isk(t.cost)) + '</div><div class="s">с учётом остатков</div></div>' +
      '<div class="tile"><div class="k">Выручка</div><div class="v">' + esc(isk(t.revenue)) + '</div><div class="s">после налогов</div></div>' +
      '<div class="tile"><div class="k">Время работ</div><div class="v">' + esc(L.fmtDur(Math.round(t.time))) + '</div><div class="s">все подряд, в одну линию</div></div>' +
      '<div class="tile"><div class="k">Закупка</div><div class="v">' + esc(L.fmtInt(t.volume)) + ' м³</div><div class="s">' + r.shopping.length + ' позиций</div></div></div>' +
      '<div class="in-cmp"><div style="--c:var(--accent)"><h3>Во что обходится</h3><dl>' +
      line('Закупка материалов', isk(t.buy)) + line('Запуск работ', isk(t.jobs), '', r.jobs.length + ' работ') +
      line('Изобретение', isk(t.invention), '', 'датакоры и запуски') + line('Всего потрачено', isk(t.spend), 'tot') +
      line('Остатки', t.leftovers ? '−' + isk(t.leftovers) : '0', '', 'лишнее от округления до прогонов, по цене мгновенной продажи') +
      line('Себестоимость', isk(t.cost), 'tot') + '</dl></div>' +
      '<div style="--c:var(--good)"><h3>Что получаем</h3><dl>' +
      line('Выручка за продукты', isk(t.revenue), '', 'по выбранной цене, минус налог и брокер') + line('Себестоимость', t.cost === null ? '—' : '−' + isk(t.cost)) +
      line('Прибыль', '<span class="' + cls(t.profit) + '">' + isk(t.profit) + '</span>', 'tot') + line('ROI', pct(t.roi)) + '</dl></div></div>';
    h += sec('sum', 'Итог: прибыль <span class="n">' + isk(t.profit) + ' ISK · ROI ' + pct(t.roi) + '</span>', sum, true);
    if (r.no_price && r.no_price.length) h += '<p class="small" style="color:var(--warn)">Нет цены на рынке: ' + esc(r.no_price.join(', ')) + '</p>';

    // работы
    var jobs = function (kind) { return r.jobs.filter(function (j) { return j.kind === kind; }); };
    var jobTable = function (list, id) {
      return table(id, list.map(function (j) { return Object.assign({ name: j.name }, j); }), [
        { k: 'name', t: 'Что', l: 1, f: function (j) { return ico(j.type_id) + esc(j.name) + (j.top ? ' <span class="sc-badge sure">продукт</span>' : ''); } },
        { k: 'runs', t: 'Прогонов', f: function (j) { return esc(L.fmtInt(j.runs)); } },
        { k: 'need', t: 'Нужно', f: function (j) { return esc(L.fmtInt(Math.round(j.need))); } },
        { k: 'made', t: 'Выйдет', f: function (j) { return esc(L.fmtInt(j.made)) + (j.made > j.need ? '<div class="in-sub">+' + L.fmtInt(Math.round(j.made - j.need)) + ' в остаток</div>' : ''); } },
        { k: 'time', t: 'Время', f: function (j) { return esc(L.fmtDur(Math.round(j.time))); } },
        { k: 'cost', t: 'Запуск', f: function (j) { return esc(isk(j.cost)); } }
      ], { sort: { k: 'cost', d: -1 } });
    };
    var jm = jobs('m'), jr = jobs('r');
    h += sec('jobs', 'Работы <span class="n">— производство ' + jm.length + (jr.length ? ', реакции ' + jr.length : '') + ' · запуск ' + isk(t.jobs) + ' ISK</span>',
      (jm.length ? sec('jobs_m', 'Производство <span class="n">(' + jm.length + ')</span>', jobTable(jm, 'plJobsM')) : '') +
      (jr.length ? sec('jobs_r', 'Реакции <span class="n">(' + jr.length + ')</span>', jobTable(jr, 'plJobsR')) : ''), false);

    // закупка по группам
    var groups = {}, order = [];
    r.shopping.forEach(function (x) { if (!groups[x.group]) { groups[x.group] = []; order.push(x.group); } groups[x.group].push(x); });
    var shop = order.map(function (g) {
      var sum = groups[g].reduce(function (a, x) { return a + (x.total || 0); }, 0);
      return sec('buy_' + g, esc(g) + ' <span class="n">(' + groups[g].length + ' · ' + isk(sum) + ' ISK)</span>', table('plBuy' + order.indexOf(g), groups[g], [
        { k: 'name', t: 'Предмет', l: 1, f: function (x) { return ico(x.type_id) + ELW_INDUSTRY.cp(x.name); } },
        { k: 'qty', t: 'Количество', f: function (x) { return esc(L.fmtInt(x.qty)); } },
        { k: 'price', t: 'Цена', f: function (x) { return esc(isk(x.price)); } },
        { k: 'total', t: 'Сумма', f: function (x) { return esc(isk(x.total)); } },
        { k: 'volume', t: 'м³', f: function (x) { return esc(L.fmtInt(x.volume)); } }
      ], { sort: { k: 'total', d: -1 } }));
    }).join('') + '<div class="controls" style="margin-top:8px"><button type="button" class="btn" id="plCopy">Скопировать список покупок</button><span class="small muted" id="plCopyMsg" role="status"></span></div>';
    h += sec('buy', 'Закупка <span class="n">— ' + r.shopping.length + ' позиций · ' + isk((t.buy || 0) + (r.invention.reduce(function (a, x) { return a + (x.datacores_cost || 0); }, 0))) + ' ISK</span>', shop, true);

    // изобретение
    if (r.invention.length) {
      h += sec('inv', 'Изобретение <span class="n">— ' + r.invention.length + ' продукт. · ' + isk(t.invention) + ' ISK</span>' + ELW_INDUSTRY.help('pl_inv'),
        table('plInv', r.invention, [
          { k: 'name', t: 'Для чего', l: 1, f: function (x) { return ico(x.type_id) + ELW_INDUSTRY.cp(x.name); } },
          { k: 'runs', t: 'Нужно прогонов', f: function (x) { return esc(L.fmtInt(x.runs)); } },
          { k: 'chance', t: 'Шанс', f: function (x) { return esc(String(Math.round(x.chance * 1000) / 10).replace('.', ',')) + '%'; } },
          { k: 'per_copy', t: 'Прогонов в копии' },
          { k: 'attempts', t: 'Попыток', title: 'С запасом на неудачи: прогоны ÷ (шанс × прогонов в копии), вверх' },
          { k: '', t: 'Датакоры', l: 1, f: function (x) { return x.datacores.map(function (d) { return esc(L.fmtInt(d[1])) + ' × ' + esc(((P.catalog || []).filter(function (c) { return c[0] === d[0]; })[0] || [0, ''])[1] || nameOf(d[0])); }).join('<br>'); } },
          { k: 'cost', t: 'Стоимость', f: function (x) { return esc(isk(x.cost)); } }
        ], {}), false);
    }
    // остатки
    if (r.leftovers.length) {
      h += sec('left', 'Остатки <span class="n">— ' + r.leftovers.length + ' поз. · ' + isk(t.leftovers) + ' ISK</span>' + ELW_INDUSTRY.help('pl_left'),
        table('plLeft', r.leftovers, [
          { k: 'name', t: 'Предмет', l: 1, f: function (x) { return ico(x.type_id) + ELW_INDUSTRY.cp(x.name) + (x.top ? ' <span class="sc-badge sure">продукт</span>' : ''); } },
          { k: 'qty', t: 'Лишних', f: function (x) { return esc(L.fmtInt(Math.round(x.qty))); } },
          { k: 'total', t: 'Стоят', f: function (x) { return esc(isk(x.total)); } }
        ], { sort: { k: 'total', d: -1 } }), false);
    }
    box.innerHTML = h + '</section>';
  }
  function nameOf(id) { var x = (P.res && P.res.shopping || []).filter(function (s) { return s.type_id === id; })[0]; return x ? x.name : String(id); }

  document.addEventListener('click', function (e) {
    if (!e.target || e.target.id !== 'plCopy' || !P.res) return;
    var text = P.res.shopping.map(function (x) { return x.name + ' ' + x.qty; }).join('\n'), msg = $('plCopyMsg');
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { msg.textContent = 'Скопировано — вставляется в «Купить несколько» на рынке игры.'; }, function () { msg.textContent = 'Не удалось.'; });
  });

  var st = document.createElement('style');
  st.textContent = '.pl-layout{display:grid;grid-template-columns:minmax(260px,330px) minmax(0,1fr);gap:14px;align-items:start}' +
    '.pl-side{position:sticky;top:10px;max-height:calc(100vh - 20px);display:flex;flex-direction:column;margin-top:0;padding:10px}.pl-main>.panel:first-child{margin-top:0}' +
    '.pl-side-hd{display:flex;align-items:baseline;gap:6px;margin-bottom:6px}.pl-q{width:100%;box-sizing:border-box;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px}' +
    '.pl-side .in-chip{padding:3px 8px;font-size:11.5px}.pl-tree{overflow:auto;flex:1;min-height:200px;margin:0 -4px;padding:0 4px}' +
    '.pl-gb{display:flex;align-items:center;gap:4px;width:100%;text-align:left;background:none;border:0;color:var(--text);font:inherit;font-size:13px;padding:4px 4px;border-radius:6px;cursor:pointer}' +
    '.pl-gb:hover,.pl-gb:focus{background:var(--panel2);outline:none}.pl-arr{width:12px;color:var(--muted);flex:none}.pl-n{margin-left:auto;font-size:11px;color:var(--muted)}' +
    '.pl-i{display:flex;align-items:center;gap:5px;font-size:12.5px;padding:2px 4px;border-radius:6px;min-width:0}.pl-i:hover{background:var(--panel2)}.pl-i .in-ico{width:18px;height:18px;margin:0}' +
    '.pl-in{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pl-add{padding:0 8px;line-height:1.5}' +
    '@media(max-width:900px){.pl-layout{grid-template-columns:1fr}.pl-side{position:static;max-height:420px}}';
  document.head.appendChild(st);

  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.plan = {
    needs: function () {                                       // закупка посчитанного плана — для «Планетарки»; null — плана нет
      return P.res && P.res.shopping ? P.res.shopping.map(function (x) { return { id: x.type_id, qty: x.qty }; }) : null;
    },
    add: function (id, qty) {                                  // снаружи (справочник): продукт в план и пересчитать
      if (!id) return;
      if (!P.items.some(function (i) { return i.id === id; })) P.items.push({ id: id, qty: qty || 1 });
      remember();
      if (P.built) { drawItems(); drawFound(); calc(); }
    },
    render: function () {
      var first = !P.built;
      shell();
      if (first) { drawModes(); drawItems(); drawFound(); if (P.items.length) calc(); }
    }
  };
})(window.ELW);
