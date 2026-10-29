// Вкладка модуля «Справочник»: разделы-подвкладки. Первый — «Руда»: вся руда игры, где добывается, во что перерабатывается.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$, BASE = ELW.base;
  var SECTIONS = [['ore', 'Руда'], ['bp', 'Чертежи']];
  var WHERE = { hs: ['хай', 'хай-сек (1.0–0.5)'], ls: ['лоу', 'лоу-сек (0.4–0.1)'], ns: ['нули', 'нули (0.0 и ниже)'], wh: ['ВХ', 'червоточины (ВХ)'], pv: ['Почвен', 'Почвен'] };
  var EMP = { amarr: 'Амарр', caldari: 'Калдари', gallente: 'Галленте', minmatar: 'Минматар' };
  var R = { section: 'ore', data: null, loading: false, cat: '', where: '', empire: '', mineral: '', q: '', sort: '', open: {}, key: null };
  try {
    var saved = JSON.parse(localStorage.getItem('elw.reference') || '{}');
    ['section', 'cat', 'where', 'empire', 'mineral', 'sort'].forEach(function (k) { if (typeof saved[k] === 'string') R[k] = saved[k]; });
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.reference', JSON.stringify({ section: R.section, cat: R.cat, where: R.where, empire: R.empire, mineral: R.mineral, sort: R.sort })); } catch (e) { } }
  function ico(t, size) { return t ? '<img class="rf-ico' + (size ? ' ' + size : '') + '" src="' + BASE + '/icons/' + t + '.png" alt="" loading="lazy">' : ''; }
  function chip(attr, val, label, on, title) { return '<button type="button" class="in-chip rf-chip' + (on ? ' on' : '') + '" ' + attr + '="' + esc(val) + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + label + '</button>'; }
  function num(v) { return v >= 1e6 ? L.fmtCompact(v) : L.fmtInt(v); }
  function vol(v) { return String(v < 0.1 ? Math.round(v * 10000) / 10000 : Math.round(v * 100) / 100).replace('.', ',') + ' м³'; }

  ELW.addTab({ id: 'reference', title: 'Справочник',
    css: '.rf-views{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}.rf-chip .n{opacity:.65;margin-left:4px;font-size:11.5px}' +
      '.rf-ico{width:22px;height:22px;vertical-align:middle;border-radius:4px;margin-right:6px}.rf-ico.sm{width:16px;height:16px;margin-right:3px}' +
      '.rf-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}.rf-bar .lbl{font-size:12px;color:var(--muted);margin-right:2px}' +
      '.rf-bar input,.rf-bar select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit;font-size:13px}' +
      '.rf-t{width:100%;border-collapse:collapse;font-size:13px}.rf-t th{font-size:11.5px;color:var(--muted);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}' +
      '.rf-t td{padding:6px 8px;border-top:1px solid var(--line);vertical-align:middle}.rf-t tr.rf-row{cursor:pointer}.rf-t tr.rf-row:hover>td{background:var(--panel2)}' +
      '.rf-t tr.rf-var>td{background:color-mix(in srgb,var(--panel2) 60%,transparent);font-size:12.5px}.rf-t .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}' +
      '.rf-nm{font-weight:600;white-space:nowrap}.rf-sub{font-size:11.5px;color:var(--muted)}.rf-arr{color:var(--muted);width:14px;display:inline-block}' +
      '.rf-w{display:inline-block;font-size:11px;border-radius:5px;padding:1px 6px;margin:1px 3px 1px 0;border:1px solid currentColor}' +
      '.rf-w.hs{color:#4fbf74}.rf-w.ls{color:#e3a63e}.rf-w.ns{color:#f06a5d}.rf-w.wh{color:#a58cf0}.rf-w.pv{color:#d65db1}' +
      '.rf-m{display:inline-flex;align-items:center;white-space:nowrap;margin:1px 10px 1px 0;font-size:12.5px}.rf-m b{font-weight:600;margin-left:2px;font-variant-numeric:tabular-nums}' +
      '.rf-m.hit{background:color-mix(in srgb,var(--accent) 22%,transparent);border-radius:5px;padding:0 4px}' +
      '.rf-cat{display:inline-block;font-size:10.5px;border-radius:5px;padding:0 6px;margin-left:6px;border:1px solid var(--line);color:var(--muted);vertical-align:1px}' +
      '.rf-cat.moon{color:#3cc8b4;border-color:#3cc8b4}.rf-cat.equinox{color:#e3a63e;border-color:#e3a63e}.rf-cat.pochven{color:#d65db1;border-color:#d65db1}.rf-cat.special{color:#a58cf0;border-color:#a58cf0}' +
      '.rf-pl{list-style:none;margin:0;padding:0;font-size:12px;line-height:1.45}.rf-pl li{margin:1px 0}.rf-pl .rf-w{margin-right:5px}' +
      '.rf-emp{font-weight:600;color:var(--text)}.rf-emp.hit{background:color-mix(in srgb,var(--accent) 25%,transparent);border-radius:4px;padding:0 3px}' +
      '.rf-plus{color:var(--good);font-weight:600}.rf-minus{color:var(--bad);font-weight:600}.rf-mats{white-space:normal;min-width:240px}.rf-t td .rf-sub{white-space:normal}' +
      '.rf-layout{display:grid;grid-template-columns:minmax(260px,330px) minmax(0,1fr);gap:14px;align-items:start}.rf-main>.panel:first-child,.rf-side{margin-top:0}' +
      '.rf-side{position:sticky;top:10px;max-height:calc(100vh - 20px);display:flex;flex-direction:column;padding:10px}.rf-q{width:100%;box-sizing:border-box;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px}' +
      '.rf-side .in-chip{padding:3px 8px;font-size:11.5px}.rf-tree{overflow:auto;flex:1;min-height:200px;margin:0 -4px;padding:0 4px}' +
      '.rf-gb{display:flex;align-items:center;gap:4px;width:100%;text-align:left;background:none;border:0;color:var(--text);font:inherit;font-size:13px;padding:4px;border-radius:6px;cursor:pointer}' +
      '.rf-gb:hover,.rf-gb:focus{background:var(--panel2);outline:none}.rf-n{margin-left:auto;font-size:11px;color:var(--muted)}' +
      '.rf-bi{display:flex;align-items:center;gap:5px;font-size:12.5px;padding:3px 4px;border-radius:6px;cursor:pointer;min-width:0}.rf-bi:hover,.rf-bi:focus{background:var(--panel2);outline:none}' +
      '.rf-bi.on{background:color-mix(in srgb,var(--accent) 22%,var(--panel2))}.rf-bn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.rf-dot{width:7px;height:7px;border-radius:50%;flex:none}.rf-dot.market,.rf-src.market{background:#4fbf74}.rf-dot.inv,.rf-src.inv{background:var(--accent)}.rf-dot.rev,.rf-src.rev{background:#a58cf0}' +
      '.rf-dot.lp,.rf-src.lp{background:#e3a63e}.rf-dot.rare,.rf-src.rare{background:#8a94a3}' +
      '.rf-src{display:inline-block;font-size:11px;border-radius:5px;padding:1px 7px;margin-right:4px;color:#0f1115;font-weight:600}' +
      '.rf-bph{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.rf-ico.lg{width:56px;height:56px;border-radius:8px;margin:0}.rf-bpt{font-size:18px;font-weight:700}' +
      '.rf-how{border-left:4px solid var(--line);padding:4px 0 6px 12px;margin:10px 0}.rf-how h3{margin:0 0 4px;font-size:14px}.rf-how p{margin:4px 0;font-size:13px}' +
      '.rf-how.market{border-left-color:#4fbf74}.rf-how.inv{border-left-color:var(--accent)}.rf-how.rev{border-left-color:#a58cf0}.rf-how.lp{border-left-color:#e3a63e}.rf-how.rare{border-left-color:#8a94a3}' +
      '.rf-mini{width:auto;min-width:320px;margin-top:4px}.rf-mini td,.rf-mini th{padding:3px 10px 3px 0}.rf-mini td.l{white-space:normal;min-width:140px}.rf-mini .rf-m{margin-right:8px}' +
      '@media(max-width:900px){.rf-layout{grid-template-columns:1fr}.rf-side{position:static;max-height:420px}}' +
      '@media(max-width:760px){.rf-t .hide-m{display:none}}',
    html: '<div class="rf-views" role="tablist" aria-label="Разделы справочника" id="rfSections"></div><div id="rfBody"></div>',
    render: function () { if (R.ready) draw(); } });

  function sections() {
    $('rfSections').innerHTML = SECTIONS.map(function (s) { return '<button type="button" role="tab" class="in-chip' + (R.section === s[0] ? ' on' : '') + '" aria-selected="' + (R.section === s[0]) + '" data-rf-sec="' + s[0] + '">' + s[1] + '</button>'; }).join('');
  }
  function load() {
    if (R.loading) return;
    R.loading = true;
    api('/api/reference/ores').then(function (j) {
      R.loading = false;
      if (!j.ok) { $('rfBody').innerHTML = '<section class="panel"><p class="in-bad">' + esc(j.message || 'Не получилось.') + '</p></section>'; return; }
      R.data = j; R.key = null; draw();
      if (!j.prices_at && j.online) setTimeout(function () { R.data = null; load(); }, 8000);     // средние цены догружаются
      setTimeout(function () { R.key = null; draw(); }, 6000);                                   // и иконки
    }, function () { R.loading = false; $('rfBody').innerHTML = '<section class="panel"><p class="in-bad">Нет связи с трекером.</p></section>'; });
  }

  function draw() {
    sections();
    if (R.section === 'bp') {
      var bkey = JSON.stringify(['bp', B.q, B.src, B.open, B.sel, B.det && B.det.bp, !!B.cat]);
      if (bkey === R.key) return;
      R.key = bkey;
      drawBp();
      return;
    }
    if (!R.data) { if (!R.loading) load(); if (!$('rfBody').innerHTML) $('rfBody').innerHTML = '<section class="panel"><p class="muted">Загружаю справочник…</p></section>'; return; }
    var key = JSON.stringify([R.section, R.cat, R.where, R.empire, R.mineral, R.q, R.sort, R.open, R.data.prices_at, R.drawn || 0]);
    if (key === R.key) return;                                   // ядро зовёт render каждые 4 с — рисуем только при изменениях
    R.key = key;
    drawOres();
  }

  function drawOres() {
    var d = R.data, M = d.materials, q = R.q.trim().toLowerCase();
    var rows = d.ores.filter(function (r) {
      if (R.cat && r.cat !== R.cat) return false;
      if (R.where && r.where.indexOf(R.where) < 0) return false;
      if (R.empire && r.empires.indexOf(R.empire) < 0) return false;
      if (R.mineral && !r.mats.some(function (m) { return String(m[0]) === R.mineral; })) return false;
      return !q || r.name.toLowerCase().indexOf(q) >= 0 || (r.ru && r.ru.toLowerCase().indexOf(q) >= 0) ||
        r.mats.some(function (m) { return (M[m[0]] || '').toLowerCase().indexOf(q) >= 0; });
    });
    if (R.sort === 'isk') rows.sort(function (a, b) { return (b.isk_m3 || 0) - (a.isk_m3 || 0); });
    else if (R.sort === 'name') rows.sort(function (a, b) { return a.name.localeCompare(b.name); });
    else if (R.sort === 'vol') rows.sort(function (a, b) { return a.volume - b.volume; });
    var mins = {};
    d.ores.forEach(function (r) { r.mats.forEach(function (m) { mins[m[0]] = M[m[0]] || m[0]; }); });
    var minOpts = Object.keys(mins).sort(function (a, b) { return String(mins[a]).localeCompare(String(mins[b])); });
    var counts = {};
    d.ores.forEach(function (r) { counts[r.cat] = (counts[r.cat] || 0) + 1; });
    var mats = function (list, hit) {
      return list.length ? list.map(function (m) { return '<span class="rf-m' + (String(m[0]) === hit ? ' hit' : '') + '" title="' + esc(M[m[0]] || m[0]) + '">' + ico(m[0], 'sm') + esc(M[m[0]] || m[0]) + ' <b>' + num(m[1]) + '</b></span>'; }).join('')
        : '<span class="rf-sub">не перерабатывается</span>';
    };
    var where = function (r) {                                 // где именно: зона, империи, пояса или конкретные аномалии
      if (!r.places.length) return '<span class="rf-sub">' + esc(r.note) + '</span>';
      return '<ul class="rf-pl">' + r.places.map(function (p) {
        var emp = p.empires ? (p.empires.length === 4 ? 'все империи' : p.empires.map(function (e) { return EMP[e]; }).join(', ')) : '';
        return '<li>' + (p.sec ? '<span class="rf-w ' + p.sec + '" title="' + esc(WHERE[p.sec][1]) + '">' + WHERE[p.sec][0] + '</span>' : '<span class="rf-w">✦</span>') +
          (emp ? '<b class="rf-emp' + (R.empire && p.empires && p.empires.indexOf(R.empire) >= 0 ? ' hit' : '') + '">' + esc(emp) + '</b> ' : '') + esc(p.text) + '</li>';
      }).join('') + '</ul>';
    };
    var isk = function (v) { return v ? L.fmtCompact(v) : '—'; };
    var h = '<section class="panel"><h2>Руда <span class="muted small">вся руда игры — где добывается и во что перерабатывается</span></h2>' +
      '<div class="rf-bar"><span class="lbl">Вид</span>' + chip('data-rf-cat', '', 'вся<span class="n">' + d.ores.length + '</span>', !R.cat) +
      d.cats.map(function (c) { return counts[c[0]] ? chip('data-rf-cat', c[0], esc(c[1]) + '<span class="n">' + counts[c[0]] + '</span>', R.cat === c[0]) : ''; }).join('') + '</div>' +
      '<div class="rf-bar"><span class="lbl">Где</span>' + chip('data-rf-where', '', 'везде', !R.where) +
      Object.keys(WHERE).map(function (w) { return chip('data-rf-where', w, WHERE[w][0], R.where === w, WHERE[w][1]); }).join('') + '</div>' +
      '<div class="rf-bar"><span class="lbl">Империя</span>' + chip('data-rf-emp', '', 'любая', !R.empire) +
      Object.keys(EMP).map(function (e) { return chip('data-rf-emp', e, EMP[e], R.empire === e, 'руда в хай- и лоу-секе территории ' + EMP[e]); }).join('') + '</div>' +
      '<div class="rf-bar"><input id="rfQ" type="search" placeholder="Поиск: руда или минерал…" aria-label="Поиск руды" value="' + esc(R.q) + '" style="flex:1 1 220px;min-width:0">' +
      '<select id="rfMin" aria-label="Даёт минерал"><option value="">даёт любой минерал</option>' + minOpts.map(function (k) { return '<option value="' + k + '"' + (R.mineral === k ? ' selected' : '') + '>даёт: ' + esc(mins[k]) + '</option>'; }).join('') + '</select>' +
      '<select id="rfSort" aria-label="Сортировка"><option value="">по порядку игры</option><option value="isk"' + (R.sort === 'isk' ? ' selected' : '') + '>ISK за м³ — дороже</option>' +
      '<option value="name"' + (R.sort === 'name' ? ' selected' : '') + '>по названию</option><option value="vol"' + (R.sort === 'vol' ? ' selected' : '') + '>по объёму</option></select></div>' +
      '<p class="small muted" style="margin:8px 0 0">Переработка — сколько минералов даёт порция (обычно 100 ед.) при 100% выходе; реальный выход зависит от навыков и места переработки (вкладка «Переработка»). ' +
      'ISK за м³ — по средним ценам игры' + (d.prices_at ? ' (обновлено ' + esc(L.fmtDateTime(d.prices_at)) + ')' : d.online ? ' — загружаю…' : ' — онлайн-функции выключены') + '. «Где именно» — по EVE University Wiki: пояса по империям и безопасности, рудные аномалии, массивы разведки в нулях; после патчей игры может меняться. ' +
      'Нажмите на руду — варианты с прибавкой к выходу и сжатая руда.</p></section>';
    h += '<section class="panel"><div class="small muted" style="margin-bottom:6px">Показано: ' + rows.length + ' из ' + d.ores.length + '</div><div class="tw"><table class="rf-t"><thead><tr>' +
      '<th class="l">Руда</th><th class="l" style="min-width:300px">Где именно добывается</th><th class="r hide-m">Объём ед.</th><th class="l">Переработка порции → минералы</th><th class="r">ISK за м³</th><th class="r hide-m">Вариантов</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var k = r.group_id + ':' + r.name, open = !!R.open[k];
      h += '<tr class="rf-row" data-rf-open="' + esc(k) + '" tabindex="0" aria-expanded="' + open + '"><td class="l"><span class="rf-arr">' + (r.variants.length ? (open ? '▾' : '▸') : '') + '</span>' + ico(r.type_id) +
        '<span class="rf-nm">' + esc(r.name) + '</span>' + (r.ru ? ' <span class="rf-sub">' + esc(r.ru) + '</span>' : '') +
        '<span class="rf-cat ' + r.cat + '">' + esc(r.rank || r.cat_name) + '</span></td>' +
        '<td class="l">' + where(r) + '</td><td class="r hide-m">' + vol(r.volume) + '</td>' +
        '<td class="l rf-mats"><div class="rf-sub">' + L.fmtInt(r.portion) + ' ед. →</div>' + mats(r.mats, R.mineral) + '</td><td class="r">' + isk(r.isk_m3) + '</td><td class="r hide-m">' + (r.variants.length || '—') + '</td></tr>';
      if (open) r.variants.forEach(function (v) {
        h += '<tr class="rf-var"><td class="l" style="padding-left:34px">' + ico(v.type_id, 'sm') + esc(v.name) +
          (v.bonus ? ' <span class="' + (v.bonus > 0 ? 'rf-plus' : 'rf-minus') + '">' + (v.bonus > 0 ? '+' : '') + v.bonus + '%</span>' : '') + (v.compressed ? ' <span class="rf-cat">сжатая</span>' : '') + '</td>' +
          '<td class="l rf-sub">' + (v.compressed ? 'сжатая: Rorqual, Orca, Porpoise или структура с модулем сжатия' : v.bonus > 0 ? 'та же руда с прибавкой к выходу' : v.bonus < 0 ? 'бедная руда: выход меньше' : '') + '</td>' +
          '<td class="r hide-m">' + vol(v.volume) + '</td><td class="l rf-mats"><div class="rf-sub">' + L.fmtInt(v.portion) + ' ед. →</div>' + mats(v.mats, R.mineral) + '</td>' +
          '<td class="r">' + isk(v.isk_m3) + '</td><td class="hide-m"></td></tr>';
      });
    });
    h += (rows.length ? '' : '<tr><td colspan="6" class="muted">Ничего не нашлось.</td></tr>') + '</tbody></table></div></section>';
    var focus = document.activeElement && document.activeElement.id === 'rfQ', pos = focus ? document.activeElement.selectionStart : 0;
    $('rfBody').innerHTML = h;
    if (focus) { var qi = $('rfQ'); qi.focus(); qi.setSelectionRange(pos, pos); }
  }

  var tq = null;
  document.addEventListener('click', function (e) {
    var box = $('rfSections') && $('rfSections').parentNode;
    if (!box || !box.contains(e.target)) return;
    var b = e.target.closest('[data-rf-sec],[data-rf-cat],[data-rf-where],[data-rf-emp],[data-rf-open]');
    if (!b) return;
    if (b.hasAttribute('data-rf-sec')) R.section = b.getAttribute('data-rf-sec');
    else if (b.hasAttribute('data-rf-cat')) R.cat = b.getAttribute('data-rf-cat');
    else if (b.hasAttribute('data-rf-where')) R.where = b.getAttribute('data-rf-where');
    else if (b.hasAttribute('data-rf-emp')) R.empire = b.getAttribute('data-rf-emp');
    else if (b.hasAttribute('data-rf-open')) { if (e.target.closest('.rf-m')) return; var k = b.getAttribute('data-rf-open'); R.open[k] = !R.open[k]; }
    remember(); draw();
  });
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-rf-open]')) { e.preventDefault(); e.target.click(); }
  });
  document.addEventListener('input', function (e) {
    if (!e.target || e.target.id !== 'rfQ') return;
    var v = e.target.value;
    clearTimeout(tq); tq = setTimeout(function () { R.q = v; draw(); }, 200);
  });
  document.addEventListener('change', function (e) {
    if (e.target && e.target.id === 'rfMin') { R.mineral = e.target.value; remember(); draw(); }
    if (e.target && e.target.id === 'rfSort') { R.sort = e.target.value; remember(); draw(); }
  });

  // ----- раздел «Чертежи»: дерево групп рынка и поиск (как в плане производства), карточка — как получить -----
  var SRC = { market: ['рынок NPC', 'Оригинал (BPO) продают NPC на рынке'], inv: ['изобретение', 'T2: изобретение из копии T1'],
    rev: ['реверс T3', 'T3: реверс-инжиниринг из реликвий'], lp: ['LP-магазин', 'Копия продаётся в LP-магазине'], rare: ['редкая копия', 'Только копии: сайты, дропы, события, контракты'] };
  var DECRYPTORS = [['без декриптора', 0, 0, 0, 0], ['Accelerant', 20, 1, 2, 10], ['Attainment', 80, 4, -1, 4], ['Augmentation', -40, 9, -2, 2],
    ['Optimized Attainment', 90, 2, 1, -2], ['Optimized Augmentation', -10, 7, 2, 0], ['Parity', 50, 3, 1, -2], ['Process', 10, 0, 3, 6], ['Symmetry', 0, 2, 1, 8]];
  var B = { cat: null, groups: {}, tree: null, loading: false, q: '', src: '', open: {}, sel: null, det: null, detLoading: false };
  try {
    var bs = JSON.parse(localStorage.getItem('elw.reference.bp') || '{}');
    B.open = bs.open || {}; B.src = bs.src || ''; B.sel = bs.sel || null;
  } catch (e) { }
  function bpRemember() { try { localStorage.setItem('elw.reference.bp', JSON.stringify({ open: B.open, src: B.src, sel: B.sel })); } catch (e) { } }
  function dur(s) { return s ? L.fmtDur(Math.round(s)) : '—'; }
  function srcBadges(list) { return list.map(function (s) { return '<span class="rf-src ' + s + '" title="' + esc(SRC[s][1]) + '">' + SRC[s][0] + '</span>'; }).join(''); }

  function bpLoad() {
    if (B.loading) return;
    B.loading = true;
    api('/api/reference/blueprints').then(function (j) {
      B.loading = false;
      if (!j.ok) return;
      B.cat = j.items; B.groups = j.groups || {}; bpTree(); R.key = null; draw();
    }, function () { B.loading = false; });
  }
  function bpTree() {
    var kids = {}, items = {};
    Object.keys(B.groups).forEach(function (g) { var p = B.groups[g][0] ? String(B.groups[g][0]) : ''; (kids[p] = kids[p] || []).push(g); });
    B.cat.forEach(function (r) { var g = r[3] && B.groups[r[3]] ? String(r[3]) : 'none'; (items[g] = items[g] || []).push(r); });
    if (items.none) (kids[''] = kids[''] || []).push('none');
    Object.keys(kids).forEach(function (k) { kids[k].sort(function (a, b) { return gname(a).localeCompare(gname(b), 'ru'); }); });
    B.tree = { kids: kids, items: items };
  }
  function gname(g) { return g === 'none' ? 'Без группы рынка' : (B.groups[g] || [0, g])[1]; }
  function pass(r, q) {
    if (B.src && r[5].indexOf(B.src) < 0) return false;
    return !q || r[1].toLowerCase().indexOf(q) >= 0 || (r[6] && r[6].toLowerCase().indexOf(q) >= 0);
  }
  function bpSide() {
    if (!B.tree) return '<p class="small muted">Загружаю чертежи…</p>';
    var q = B.q.trim().toLowerCase(), count = {}, total = 0, shown = 0, h = '';
    function cnt(g) {
      if (count[g] !== undefined) return count[g];
      var n = (B.tree.items[g] || []).filter(function (r) { return pass(r, q); }).length;
      (B.tree.kids[g] || []).forEach(function (k) { n += cnt(k); });
      return (count[g] = n);
    }
    (B.tree.kids[''] || []).forEach(function (g) { total += cnt(g); });
    function node(g, depth) {
      var n = cnt(g);
      if (!n) return;
      var open = q ? true : !!B.open[g];
      h += '<div style="padding-left:' + (depth * 14) + 'px"><button type="button" class="rf-gb" data-bp-grp="' + esc(g) + '" aria-expanded="' + open + '">' +
        '<span class="rf-arr">' + (open ? '▾' : '▸') + '</span>' + esc(gname(g)) + ' <span class="rf-n">' + n + '</span></button></div>';
      if (!open) return;
      (B.tree.kids[g] || []).forEach(function (k) { node(k, depth + 1); });
      (B.tree.items[g] || []).filter(function (r) { return pass(r, q); }).forEach(function (r) {
        if (shown++ > 600) return;
        h += '<div class="rf-bi' + (String(r[0]) === String(B.sel) ? ' on' : '') + '" style="padding-left:' + ((depth + 1) * 14 + 16) + 'px" data-bp-sel="' + r[0] + '" tabindex="0" role="button" title="' + esc(r[1] + ' Blueprint') + '">' +
          ico(r[2], 'sm') + '<span class="rf-bn">' + esc(r[1]) + '</span>' + r[5].map(function (s) { return '<i class="rf-dot ' + s + '" title="' + esc(SRC[s][1]) + '"></i>'; }).join('') + '</div>';
      });
    }
    (B.tree.kids[''] || []).forEach(function (g) { node(g, 0); });
    return '<div class="small muted" style="margin:2px 0 6px">' + (q || B.src ? 'найдено ' : 'всего ') + L.fmtInt(total) + '</div>' + (h || '<p class="small muted">Ничего не нашлось.</p>');
  }
  function bpCard() {
    var d = B.det;
    if (!B.sel) return '<section class="panel"><p class="muted">Выберите чертёж слева — здесь будет, как его получить, что нужно на прогон и сколько длятся исследования.</p></section>';
    if (!d || String(d.bp) !== String(B.sel)) return '<section class="panel"><p class="muted">Загружаю…</p></section>';
    var mat = function (m) { return '<span class="rf-m">' + ico(m.type_id, 'sm') + ELW_cp(m.name) + ' <b>×' + L.fmtInt(m.qty) + '</b></span>'; };
    var h = '<section class="panel"><div class="rf-bph">' + ico(d.product, 'lg') + '<div><div class="rf-bpt">' + ELW_cp(d.product_name) + (d.tech ? ' <span class="rf-cat">T' + d.tech + '</span>' : '') +
      (d.kind === 'r' ? ' <span class="rf-cat">реакция</span>' : '') + '</div><div class="rf-sub">' + esc(d.name) + (d.product_ru ? ' · ' + esc(d.product_ru) : '') + '</div>' +
      '<div style="margin-top:4px">' + srcBadges(d.sources) + '</div></div>' +
      (window.ELW_INDUSTRY && ELW_INDUSTRY.open ? '<button type="button" class="btn" data-bp-calc="' + esc(d.product_name) + '" style="margin-left:auto">Рассчитать в «Производстве»</button>' : '') + '</div></section>';
    // как получить
    h += '<section class="panel"><h2>Как получить</h2>';
    d.sources.forEach(function (s) {
      if (s === 'market') {
        h += '<div class="rf-how market"><h3>Купить оригинал у NPC</h3><p>Оригинал чертежа (BPO) продают NPC на рынке — бессрочный, можно исследовать ME/TE и делать копии.' +
          (d.market_path.length ? ' Окно рынка: <b>' + esc(d.market_path.join(' → ')) + '</b>.' : '') + (d.base_price ? ' Базовая цена: <b>' + L.fmtIsk(d.base_price) + '</b> (на рынке может отличаться).' : '') + '</p></div>';
      } else if (s === 'inv' || s === 'rev') {
        var list = d.invention.filter(function (x) { return x.relic === (s === 'rev'); });
        var dc = list[0] ? list[0].datacores : [];
        h += '<div class="rf-how ' + s + '"><h3>' + (s === 'inv' ? 'Изобретение (T2)' : 'Реверс-инжиниринг (T3)') + '</h3><p>' +
          (s === 'inv' ? 'Нужна копия чертежа T1 и датакоры; изобретение с шансом даёт копию T2 (BPC, ME 2 / TE 4). Оригиналы T2 не продаются.' :
            'Нужна реликвия Sleeper (сайты реликвий в червоточинах) и датакоры; с шансом получается копия T3 (BPC). Чем целее реликвия — тем выше шанс и больше прогонов.') + '</p>' +
          '<table class="rf-t rf-mini"><thead><tr><th class="l">' + (s === 'inv' ? 'Копия T1' : 'Реликвия') + '</th><th class="r">Базовый шанс</th><th class="r">Прогонов в копии</th><th class="r">Время</th></tr></thead><tbody>' +
          list.map(function (x) { return '<tr><td class="l">' + ico(x.source, 'sm') + ELW_cp(x.source_name) + '</td><td class="r">' + Math.round(x.chance * 1000) / 10 + '%</td><td class="r">' + x.runs + '</td><td class="r">' + dur(x.time) + '</td></tr>'; }).join('') +
          '</tbody></table><p style="margin-top:6px">Датакоры на попытку: ' + dc.map(mat).join('') + '</p>' +
          '<p class="rf-sub">Шанс растёт с навыками: две науки (+1/30 за уровень каждой) и шифрование расы (+1/40 за уровень). Декриптор — по желанию:</p>' +
          '<table class="rf-t rf-mini"><thead><tr><th class="l">Декриптор</th><th class="r">Шанс</th><th class="r">Прогонов</th><th class="r">ME</th><th class="r">TE</th></tr></thead><tbody>' +
          DECRYPTORS.map(function (x) { var sg = function (v, p) { return v ? (v > 0 ? '+' : '') + v + (p || '') : '0'; };
            return '<tr><td class="l">' + esc(x[0]) + '</td><td class="r">' + sg(x[1], '%') + '</td><td class="r">' + sg(x[2]) + '</td><td class="r">' + sg(x[3]) + '</td><td class="r">' + sg(x[4]) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      } else if (s === 'lp') {
        h += '<div class="rf-how lp"><h3>LP-магазин</h3><p>Копию чертежа (BPC) продают за LP (очки лояльности) в магазинах NPC-корпораций — LP дают за миссии агентов этих корпораций и за фракционные войны.</p>' +
          '<table class="rf-t rf-mini"><thead><tr><th class="r">LP</th><th class="r">ISK</th><th class="l">Ещё нужно</th><th class="l">Где (корпорации)</th></tr></thead><tbody>' +
          d.lp.map(function (o) {
            var corps = o.corps.slice(0, 6).join(', ') + (o.corps.length > 6 ? ' и ещё ' + (o.corps.length - 6) : '');
            return '<tr><td class="r">' + L.fmtInt(o.lp) + '</td><td class="r">' + (o.isk ? L.fmtIsk(o.isk) : '—') + '</td><td class="l">' + (o.required.length ? o.required.map(mat).join('') : '—') + '</td>' +
              '<td class="l rf-sub" title="' + esc(o.corps.join(', ')) + '">' + esc(corps) + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      } else {
        h += '<div class="rf-how rare"><h3>Только копии</h3><p>NPC оригинал не продают, в LP-магазинах его нет, изобретением не получить. Копии добывают в сайтах исследований (Data/Relic), с NPC, в событиях — или покупают у игроков на контрактах.</p></div>';
      }
    });
    h += '</section>';
    // производство и исследования
    h += '<section class="panel"><h2>Производство <span class="muted small">на один прогон, без ME</span></h2><div class="tiles">' +
      ELW.tile('Выходит за прогон', L.fmtInt(d.out) + ' шт.', d.kind === 'r' ? 'реакция' : '') + ELW.tile('Время прогона', dur(d.time), 'без навыков и бонусов') +
      ELW.tile('Макс. прогонов', d.max_runs ? L.fmtInt(d.max_runs) : '—', 'в одной работе') + '</div>' +
      '<div style="margin-top:8px">' + d.materials.map(mat).join('') + '</div>';
    if (d.copy_time || d.me_time || d.te_time) h += '<div class="tiles" style="margin-top:10px">' + ELW.tile('Исследование ME', dur(d.me_time), 'уровень 1, базовое') +
      ELW.tile('Исследование TE', dur(d.te_time), 'уровень 1, базовое') + ELW.tile('Копирование', dur(d.copy_time), 'один прогон копии') + '</div>';
    return h + '</section>';
  }
  function ELW_cp(n) { return window.ELW_INDUSTRY && ELW_INDUSTRY.cp ? ELW_INDUSTRY.cp(n) : esc(n); }
  function bpSelect(id) {
    B.sel = id; bpRemember(); R.key = null; draw();
    api('/api/reference/blueprint?id=' + encodeURIComponent(id)).then(function (j) {
      if (j.ok && String(B.sel) === String(j.bp)) { B.det = j; R.key = null; draw(); setTimeout(function () { R.key = null; draw(); }, 3000); }
    });
  }
  function drawBp() {
    if (!B.cat) { bpLoad(); $('rfBody').innerHTML = '<section class="panel"><p class="muted">Загружаю чертежи…</p></section>'; return; }
    if (B.sel && (!B.det || String(B.det.bp) !== String(B.sel)) && !B.detLoading) { B.detLoading = true; api('/api/reference/blueprint?id=' + B.sel).then(function (j) { B.detLoading = false; if (j.ok) { B.det = j; R.key = null; draw(); } }, function () { B.detLoading = false; }); }
    var side = $('rfBpSide');
    var keepScroll = side ? side.querySelector('.rf-tree').scrollTop : 0;
    var focus = document.activeElement && document.activeElement.id === 'rfBpQ', pos = focus ? document.activeElement.selectionStart : 0;
    $('rfBody').innerHTML = '<div class="rf-layout"><aside class="panel rf-side" id="rfBpSide"><input id="rfBpQ" type="search" class="rf-q" placeholder="Поиск: Caracal, Hobgoblin II…" value="' + esc(B.q) + '" aria-label="Поиск чертежа">' +
      '<div class="rf-bar" style="margin:6px 0">' + chip('data-bp-src', '', 'все', !B.src) + Object.keys(SRC).map(function (s) { return chip('data-bp-src', s, SRC[s][0], B.src === s, SRC[s][1]); }).join('') + '</div>' +
      '<div class="rf-tree">' + bpSide() + '</div></aside><div class="rf-main">' + bpCard() + '</div></div>';
    $('rfBpSide').querySelector('.rf-tree').scrollTop = keepScroll;
    if (focus) { var qi = $('rfBpQ'); qi.focus(); qi.setSelectionRange(pos, pos); }
  }
  document.addEventListener('click', function (e) {
    var body = $('rfBody');
    if (!body || !body.contains(e.target) || R.section !== 'bp') return;
    var b = e.target.closest('[data-bp-grp],[data-bp-sel],[data-bp-src],[data-bp-calc]');
    if (!b) return;
    if (b.hasAttribute('data-bp-grp')) {
      var g = b.getAttribute('data-bp-grp'); B.open[g] = !B.open[g]; bpRemember(); R.key = null; draw();
      var ids = (B.tree.items[g] || []).map(function (r) { return r[2]; });
      if (B.open[g] && ids.length) api('/api/reference/icons', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: ids }) })
        .then(function () { setTimeout(function () { R.key = null; draw(); }, 2500); }, function () { });
    } else if (b.hasAttribute('data-bp-sel')) { if (!e.target.closest('.in-cp')) bpSelect(b.getAttribute('data-bp-sel')); }
    else if (b.hasAttribute('data-bp-src')) { B.src = b.getAttribute('data-bp-src'); bpRemember(); R.key = null; draw(); }
    else if (b.hasAttribute('data-bp-calc')) ELW_INDUSTRY.open(b.getAttribute('data-bp-calc'));
  });
  document.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-bp-sel]')) { e.preventDefault(); bpSelect(e.target.getAttribute('data-bp-sel')); } });
  var tbq = null;
  document.addEventListener('input', function (e) { if (e.target && e.target.id === 'rfBpQ') { var v = e.target.value; clearTimeout(tbq); tbq = setTimeout(function () { B.q = v; R.key = null; draw(); }, 200); } });
  R.ready = true;
  setTimeout(function () { if ($('rfSections') && $('rfSections').offsetParent) draw(); }, 0);   // вкладка уже открыта при запуске
})(window.ELW);
