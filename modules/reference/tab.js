// Вкладка модуля «Справочник»: разделы-подвкладки. Первый — «Руда»: вся руда игры, где добывается, во что перерабатывается.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$, BASE = ELW.base;
  var SECTIONS = [['ore', 'Руда']];
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
  R.ready = true;
  setTimeout(function () { if ($('rfSections') && $('rfSections').offsetParent) draw(); }, 0);   // вкладка уже открыта при запуске
})(window.ELW);
