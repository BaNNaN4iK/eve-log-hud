// Вкладка модуля «Справочник»: разделы-подвкладки — «Руда» (где добывается, во что перерабатывается), «Чертежи» (как получить),
// «Фракционные войны» (фракции, милиции, живая статистика, LP-магазины милиций).
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$, BASE = ELW.base;
  var SECTIONS = [['ore', 'Руда'], ['bp', 'Чертежи'], ['fw', 'Фракционные войны']];
  var WHERE = { hs: ['хай', 'хай-сек (1.0–0.5)'], ls: ['лоу', 'лоу-сек (0.4–0.1)'], ns: ['нули', 'нули (0.0 и ниже)'], wh: ['ВХ', 'червоточины (ВХ)'], pv: ['Почвен', 'Почвен'] };
  var EMP = { amarr: 'Амарр', caldari: 'Калдари', gallente: 'Галленте', minmatar: 'Минматар' };
  var R = { section: 'ore', data: null, loading: false, cat: '', where: '', empire: '', mineral: '', q: '', sort: '', open: {}, key: null, oreView: 'ores', cr: null, crLoading: false, up: null, upLoading: false, upEdit: false, upErr: '' };
  try {
    var saved = JSON.parse(localStorage.getItem('elw.reference') || '{}');
    ['section', 'cat', 'where', 'empire', 'mineral', 'sort', 'oreView'].forEach(function (k) { if (typeof saved[k] === 'string') R[k] = saved[k]; });
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.reference', JSON.stringify({ section: R.section, cat: R.cat, where: R.where, empire: R.empire, mineral: R.mineral, sort: R.sort, oreView: R.oreView })); } catch (e) { } }
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
      '.rf-fws{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px;margin-top:10px}' +
      '.rf-fc{border:1px solid var(--line);border-left:5px solid var(--muted);border-radius:10px;background:var(--panel2);padding:10px 12px;display:flex;flex-direction:column;gap:6px}' +
      '.rf-fc.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}.rf-fc h3{margin:0;font-size:15px}.rf-fc .en{font-size:11.5px;color:var(--muted)}' +
      '.rf-fst{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 8px;font-size:12px}.rf-fst b{display:block;font-size:14px;font-variant-numeric:tabular-nums}.rf-fst span{color:var(--muted)}' +
      '.rf-plan{color:var(--accent);text-decoration:none;font-weight:600}.rf-plan:hover{text-decoration:underline}' +
      '.rf-vs{font-size:12px}.rf-vs b{font-weight:600}.rf-pir{color:#e3a63e;border-color:#e3a63e}' +
      '.rf-copy{cursor:copy;border-bottom:1px dashed var(--muted)}.rf-copy:hover,.rf-copy:focus{color:var(--accent);outline:none}.rf-copy.done{color:var(--good);border-bottom-color:var(--good)}.rf-copy.done::after{content:" ✓ скопировано";font-size:11px}' +
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
    if (R.section === 'fw') {
      var fkey = JSON.stringify(['fw', W.sel, W.cat, W.q, W.sort, W.priced, !!W.data, W.data && W.data.live_at, W.store && W.store.id, W.store && W.store.prices_at, W.tick]);
      if (fkey === R.key) return;
      R.key = fkey;
      drawFw();
      return;
    }
    if (R.section === 'bp') {
      var bkey = JSON.stringify(['bp', B.q, B.src, B.open, B.sel, B.det && B.det.bp, !!B.cat]);
      if (bkey === R.key) return;
      R.key = bkey;
      drawBp();
      return;
    }
    if (!R.data) { if (!R.loading) load(); if (!$('rfBody').innerHTML) $('rfBody').innerHTML = '<section class="panel"><p class="muted">Загружаю справочник…</p></section>'; return; }
    var key = JSON.stringify([R.section, R.oreView, !!R.cr, R.up && R.up.text, R.upEdit, R.upErr, R.cat, R.where, R.empire, R.mineral, R.q, R.sort, R.open, R.data.prices_at, R.drawn || 0]);
    if (key === R.key) return;                                   // ядро зовёт render каждые 4 с — рисуем только при изменениях
    R.key = key;
    if (R.oreView === 'crystals') drawCrystals(); else if (R.oreView === 'upg') drawUpg(); else drawOres();
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
    var h = oreViews() + '<section class="panel"><h2>Руда <span class="muted small">вся руда игры — где добывается и во что перерабатывается</span></h2>' +
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
      '<th class="l">Руда</th><th class="l" style="min-width:300px">Где именно добывается</th><th class="r hide-m">Объём ед.</th><th class="l">Переработка порции → минералы</th><th class="r">ISK за м³</th><th class="l hide-m" title="Каким кристаллом добывать — подробнее на «Кристаллы для добычи»">Кристалл</th><th class="r hide-m">Вариантов</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var k = r.group_id + ':' + r.name, open = !!R.open[k];
      h += '<tr class="rf-row" data-rf-open="' + esc(k) + '" tabindex="0" aria-expanded="' + open + '"><td class="l"><span class="rf-arr">' + (r.variants.length ? (open ? '▾' : '▸') : '') + '</span>' + ico(r.type_id) +
        '<span class="rf-nm">' + esc(r.name) + '</span>' + (r.ru ? ' <span class="rf-sub">' + esc(r.ru) + '</span>' : '') +
        '<span class="rf-cat ' + r.cat + '">' + esc(r.rank || r.cat_name) + '</span></td>' +
        '<td class="l">' + where(r) + '</td><td class="r hide-m">' + vol(r.volume) + '</td>' +
        '<td class="l rf-mats"><div class="rf-sub">' + L.fmtInt(r.portion) + ' ед. →</div>' + mats(r.mats, R.mineral) + '</td><td class="r">' + isk(r.isk_m3) + '</td><td class="l hide-m">' + (r.crystal ? '<span class="rf-cat" data-rf-crys="1" style="cursor:pointer;margin:0">' + esc(r.crystal) + '</span>' : '<span class="rf-sub">нет</span>') + '</td><td class="r hide-m">' + (r.variants.length || '—') + '</td></tr>';
      if (open) r.variants.forEach(function (v) {
        h += '<tr class="rf-var"><td class="l" style="padding-left:34px">' + ico(v.type_id, 'sm') + esc(v.name) +
          (v.bonus ? ' <span class="' + (v.bonus > 0 ? 'rf-plus' : 'rf-minus') + '">' + (v.bonus > 0 ? '+' : '') + v.bonus + '%</span>' : '') + (v.compressed ? ' <span class="rf-cat">сжатая</span>' : '') + '</td>' +
          '<td class="l rf-sub">' + (v.compressed ? 'сжатая: Rorqual, Orca, Porpoise или структура с модулем сжатия' : v.bonus > 0 ? 'та же руда с прибавкой к выходу' : v.bonus < 0 ? 'бедная руда: выход меньше' : '') + '</td>' +
          '<td class="r hide-m">' + vol(v.volume) + '</td><td class="l rf-mats"><div class="rf-sub">' + L.fmtInt(v.portion) + ' ед. →</div>' + mats(v.mats, R.mineral) + '</td>' +
          '<td class="r">' + isk(v.isk_m3) + '</td><td class="hide-m"></td><td class="hide-m"></td></tr>';
      });
    });
    h += (rows.length ? '' : '<tr><td colspan="7" class="muted">Ничего не нашлось.</td></tr>') + '</tbody></table></div></section>';
    var focus = document.activeElement && document.activeElement.id === 'rfQ', pos = focus ? document.activeElement.selectionStart : 0;
    $('rfBody').innerHTML = h;
    if (focus) { var qi = $('rfQ'); qi.focus(); qi.setSelectionRange(pos, pos); }
  }

  // текст, который копируется по нажатию (название навыка — вставить в поиск навыков в игре)
  function copyable(t) { return t ? '<span class="rf-copy" data-rf-copy="' + esc(t) + '" tabindex="0" role="button" title="Нажмите — скопировать">' + esc(t) + '</span>' : '—'; }
  function copyText(text) {
    var ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(ta); ta.select(); var ok = false; try { ok = document.execCommand('copy'); } catch (e) { }
    document.body.removeChild(ta);
    if (!ok && navigator.clipboard) navigator.clipboard.writeText(text).catch(function () { });
  }
  document.addEventListener('click', function (e) {
    var el = e.target.closest && e.target.closest('[data-rf-copy]');
    if (!el) return;
    copyText(el.getAttribute('data-rf-copy'));
    el.classList.add('done'); setTimeout(function () { el.classList.remove('done'); }, 1500);
  });
  document.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-rf-copy]')) { e.preventDefault(); e.target.click(); } });
  function oreViews() {
    return '<div class="rf-bar" style="margin:0 0 10px">' + chip('data-rf-oview', 'ores', 'Руда', R.oreView !== 'crystals') +
      chip('data-rf-oview', 'crystals', 'Кристаллы для добычи', R.oreView === 'crystals', 'Какой кристалл на какую руду и чем отличаются типы A, B и C') +
      chip('data-rf-oview', 'upg', 'Апгрейды систем', R.oreView === 'upg', 'Где стоят массивы разведки (Prospecting Array): какой минерал, какой уровень, в каких системах') + '</div>';
  }
  function upLoad() {
    if (R.upLoading) return;
    R.upLoading = true;
    api('/api/reference/upgrades').then(function (j) { R.upLoading = false; if (j.ok) { R.up = j; R.key = null; draw(); } }, function () { R.upLoading = false; });
  }
  function drawUpg() {
    if (!R.up) { upLoad(); $('rfBody').innerHTML = oreViews() + '<section class="panel"><p class="muted">Загружаю апгрейды…</p></section>'; return; }
    var u = R.up, sec = function (v) { return v === null || v === undefined ? '' : String(v.toFixed(2)).replace('.', ','); };
    var h = oreViews() + '<section class="panel"><h2>Апгрейды систем <span class="muted small">массивы разведки (Prospecting Array) — где какую руду добывать</span>' +
      (R.upEdit ? '' : ' <button type="button" class="btn" data-rf-upedit="1" style="float:right">Изменить список</button>') + '</h2>' +
      '<p class="small" style="margin:4px 0">Массив разведки ставится в суверенный хаб системы и вызывает в ней рудные аномалии с рудой, богатой своим минералом. ' +
      'Уровень массива — 1, 2 или 3: чем выше, тем богаче аномалии. Нажмите на систему — имя скопируется, на руду — откроется её карточка в таблице руды.</p></section>';
    if (R.upEdit) {
      h += '<section class="panel"><h2>Изменить список</h2><p class="small muted" style="margin:4px 0">Одна строка — один массив: «Минерал уровень: системы через запятую». ' +
        'Минерал можно по-английски или по-русски; безопасность рядом с системой («-0.46») можно оставить — она пропускается. Пример: <code>Pyerite 3: JL-ZUQ, FIZU-X, 1GH-48</code></p>' +
        '<textarea id="rfUpText" rows="12" spellcheck="false" style="width:100%;box-sizing:border-box;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:8px 10px;font:13px/1.5 ui-monospace,Consolas,monospace">' + esc(u.text || '') + '</textarea>' +
        (R.upErr ? '<p class="in-bad small" style="margin:6px 0">' + esc(R.upErr) + '</p>' : '') +
        '<div style="display:flex;gap:8px;margin-top:8px"><button type="button" class="btn" data-rf-upsave="1">Сохранить</button><button type="button" class="btn" data-rf-upcancel="1">Отмена</button></div>' +
        '<p class="small muted" style="margin:8px 0 0">Список хранится только на этом компьютере, в данных программы.</p></section>';
    }
    h += '<section class="panel"><div class="tw"><table class="rf-t"><thead><tr><th class="l">Минерал</th><th class="l">Массив</th><th class="l">Системы</th><th class="l">Руда в аномалиях</th></tr></thead><tbody>' +
      (u.items.length ? u.items.map(function (x) {
        return '<tr><td class="l">' + ico(x.mineral) + '<span class="rf-nm">' + esc(x.ru) + '</span> <span class="rf-sub">' + esc(x.name) + '</span></td>' +
          '<td class="l"><span class="rf-cat equinox" style="margin:0" title="' + esc(x.array) + '">ур. ' + x.level + '</span></td>' +
          '<td class="l" style="white-space:normal">' + x.systems.map(function (y) {
            return '<span style="display:inline-block;margin:1px 14px 1px 0;white-space:nowrap">' + copyable(y.name) +
              (y.sec !== null ? ' <span class="rf-w ns" style="margin:0 0 0 3px">' + sec(y.sec) + '</span>' : ' <span class="rf-sub">нет в данных карты</span>') +
              (y.region ? ' <span class="rf-sub">' + esc(y.region) + '</span>' : '') + '</span>';
          }).join('') + '</td>' +
          '<td class="l">' + (x.ores.length ? x.ores.map(function (o) {
            return '<a href="#" class="rf-plan" data-rf-upore="' + esc(o[1]) + '" title="Показать в таблице руды">' + ico(o[0], 'sm') + esc(o[1]) + '</a>';
          }).join(', ') : '—') + '</td></tr>';
      }).join('') : '<tr><td colspan="4" class="muted">Список пуст — нажмите «Изменить список» и впишите, где стоят массивы.</td></tr>') +
      '</tbody></table></div></section>';
    $('rfBody').innerHTML = h;
  }
  function upSave() {
    var t = $('rfUpText') ? $('rfUpText').value : '';
    api('/api/reference/upgrades', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) }).then(function (j) {
      if (j.ok) { R.up = j; R.upEdit = false; R.upErr = ''; } else R.upErr = j.message || 'Не получилось сохранить.';
      R.key = null; draw();
    }, function () { R.upErr = 'Нет связи с трекером.'; R.key = null; draw(); });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-rf-upedit],[data-rf-upsave],[data-rf-upcancel],[data-rf-upore]');
    if (!b || !$('rfBody') || !$('rfBody').contains(b)) return;
    e.preventDefault(); e.stopPropagation();
    if (b.hasAttribute('data-rf-upsave')) { upSave(); return; }
    if (b.hasAttribute('data-rf-upedit')) { R.upEdit = true; R.upErr = ''; }
    else if (b.hasAttribute('data-rf-upcancel')) { R.upEdit = false; R.upErr = ''; }
    else { R.oreView = 'ores'; R.q = b.getAttribute('data-rf-upore'); R.cat = R.where = R.empire = R.mineral = ''; remember(); }
    R.key = null; draw();
  });
  function drawCrystals() {
    if (!R.cr) {
      if (!R.crLoading) { R.crLoading = true; api('/api/reference/crystals').then(function (j) { R.crLoading = false; if (j.ok) { R.cr = j; R.key = null; draw(); } }, function () { R.crLoading = false; }); }
      $('rfBody').innerHTML = oreViews() + '<section class="panel"><p class="muted">Загружаю кристаллы…</p></section>';
      return;
    }
    var c = R.cr, pc = function (v) { return String(Math.round(v * 1000) / 10).replace('.', ','); };
    var rng = function (a, f, unit) { return a[0] === a[1] ? f(a[0]) + (unit || '') : f(a[0]) + '–' + f(a[1]) + (unit || ''); };
    var x = function (v) { return '×' + String(Math.round(v * 100) / 100).replace('.', ','); };
    var plus = function (v) { return v ? '+' + String(v).replace('.', ',') + '%' : '0'; };
    var prng = function (a) { var f = function (v) { return String(v).replace('.', ','); }; return a[0] === a[1] ? plus(a[0]) : '+' + f(a[0]) + '…' + f(a[1]) + '%'; };
    var h = oreViews() + '<section class="panel"><h2>Кристаллы для добычи <span class="muted small">какой кристалл на какую руду и чем отличаются A, B и C</span></h2>' +
      '<p class="small" style="margin:4px 0">Кристаллы заряжаются, как патроны, в модулированные шахтёрские лазеры (T2 со словом <b>Modulated</b> в названии) и в ORE Deep Core Mining Laser. ' +
      'Каждый кристалл подходит только к своему семейству руды: на другой руде он ничего не прибавляет. Кристаллы изнашиваются и ломаются — держите запас. ' +
      'Для T1-кристалла нужен навык переработки своей руды на 3, для T2 — на 4.</p></section>';
    // сравнение типов
    h += '<section class="panel"><h2>Типы A, B и C</h2><div class="tw"><table class="rf-t"><thead><tr><th class="l">Тип</th>' +
      '<th class="r" title="Сколько руды за один цикл относительно лазера без кристалла">Руды за цикл</th><th class="r">Цикл</th>' +
      '<th class="r" title="Руды за цикл ÷ длительность цикла">Руды в час</th><th class="r" title="Прибавка к шансу, что часть руды уйдёт в отходы">Шанс отходов</th>' +
      '<th class="r" title="Насколько больше объём отходов, когда они случаются">Объём отходов</th><th class="r" title="Прибавка к расходу накопителя лазером (у разных семейств разная)">Накопитель</th>' +
      '<th class="r" title="Шанс повредить кристалл за цикл (у лунных и редких руд выше)">Износ за цикл</th><th class="l">Зачем</th></tr></thead><tbody>' +
      c.compare.map(function (t) {
        var best = t.type === 'B' && t.tech === 2, bad = t.type === 'C';
        return '<tr><td class="l"><b>' + esc(t.type) + ' ' + (t.tech === 2 ? 'II' : 'I') + '</b> <span class="rf-sub">' + esc(t.label) + '</span></td>' +
          '<td class="r' + (bad ? ' rf-minus' : '') + '">' + rng(t.yield, x) + '</td><td class="r">' + rng(t.duration, x) + '</td>' +
          '<td class="r"><b class="' + (bad ? 'rf-minus' : best ? 'rf-plus' : '') + '">' + rng(t.per_hour, x) + '</b></td>' +
          '<td class="r">' + prng(t.residue_chance) + '</td><td class="r">' + prng(t.residue_volume) + '</td><td class="r">' + prng(t.cap) + '</td>' +
          '<td class="r">' + rng(t.volatility, pc, '%') + '</td><td class="l rf-sub" style="min-width:220px">' + esc(t.tech === 1 ? t.about : '') + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<ul class="small" style="margin:8px 0 0;padding-left:18px;line-height:1.5">' +
      '<li><b>A</b> — основной выбор: +50% руды (A II +80%) почти без отходов.</li>' +
      '<li><b>B</b> — столько же руды за цикл, но цикл на 10% (B II на 20%) короче: в час выходит больше всего (B II ×2,25). Цена — отходы (+20…30% к шансу) и накопитель. Хорош, когда руды в поясе много и накопителя хватает.</li>' +
      '<li><b>C</b> — не для заработка: руды за цикл в 4–5 раз меньше, отходов очень много. Нужен, чтобы быстро «выжечь» пояс или лунный чанк, например на чужой территории.</li>' +
      '<li>Отходы — часть руды, которая пропадает (уходит из астероида, но не в трюм). Шанс и объём отходов зависят ещё от модуля и навыков.</li></ul></section>';
    // какой кристалл на какую руду
    h += '<section class="panel"><h2>Какой кристалл на какую руду</h2><div class="tw"><table class="rf-t"><thead><tr><th class="l">Кристаллы</th><th class="l">Руда</th>' +
      '<th class="l">Навык</th><th class="r" title="Шанс повредить кристалл за цикл: A I — C II">Износ A I … C II</th></tr></thead><tbody>' +
      c.families.map(function (f) {
        var v = f.crystals.map(function (k) { return k.volatility; });
        return '<tr><td class="l">' + ico(f.crystals[0].id) + '<span class="rf-nm">' + esc(f.ru) + '</span><div class="rf-sub" style="padding-left:28px">' + esc(f.family) + ' Mining Crystal · ' +
          f.crystals.map(function (k) { return k.type + (k.tech === 2 ? ' II' : ' I'); }).join(', ') + '</div></td>' +
          '<td class="l" style="white-space:normal">' + esc(f.ores.join(', ')) + (f.special.length ? '<div class="rf-sub">и особые: ' + esc(f.special.join(', ')) + '</div>' : '') +
          (f.note ? '<div class="rf-sub">' + esc(f.note) + '</div>' : '') + '</td>' +
          '<td class="l">' + copyable(f.skill) + '<div class="rf-sub">T1 — уровень 3, T2 — уровень 4</div></td><td class="r">' + pc(Math.min.apply(null, v)) + '–' + pc(Math.max.apply(null, v)) + '%</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="small muted" style="margin:8px 0 0">Кристаллов нет для Mercoxit и особых руд заданий и событий — их добывают без кристалла. ' +
      'Варианты руды (II-, III-, IV-Grade, Brimful, Glistening…) добываются тем же кристаллом, что и базовая руда. Данные — справочник игры и ESI' + (c.built ? ', ' + esc(c.built) : '') + '.</p></section>';
    $('rfBody').innerHTML = h;
  }

  var tq = null;
  document.addEventListener('click', function (e) {
    var ov = e.target.closest && e.target.closest('[data-rf-oview],[data-rf-crys]');
    if (ov && $('rfBody') && $('rfBody').contains(ov)) {
      e.stopPropagation();
      R.oreView = ov.hasAttribute('data-rf-crys') ? 'crystals' : ov.getAttribute('data-rf-oview');
      remember(); R.key = null; draw(); return;
    }
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
      (window.ELW_INDUSTRY && ELW_INDUSTRY.open ? '<span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap">' + toPlan(d.product, d.product_name, true) +
        '<a href="#" class="btn" data-goto="industry" data-bp-calc="' + esc(d.product_name) + '">Рассчитать в «Ведении производства»</a></span>' : '') + '</div></section>';
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
  // «В план производства»: вкладка «Производство» → «План производства», продукт чертежа добавлен и посчитан
  function toPlan(pid, name, big) {
    if (!window.ELW_INDUSTRY || !ELW_INDUSTRY.toPlan) return '';
    return '<a href="#" class="' + (big ? 'btn primary' : 'rf-plan') + '" data-goto="industry" data-to-plan="' + pid + '" title="' + esc('Добавить «' + name + '» в план производства') + '">В план производства</a>';
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
  document.addEventListener('click', function (e) {               // переход в план: вкладку переключает data-goto ядра
    var a = e.target.closest && e.target.closest('[data-to-plan]');
    if (a && window.ELW_INDUSTRY && ELW_INDUSTRY.toPlan) ELW_INDUSTRY.toPlan(+a.getAttribute('data-to-plan'));
  });
  document.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-bp-sel]')) { e.preventDefault(); bpSelect(e.target.getAttribute('data-bp-sel')); } });
  var tbq = null;
  document.addEventListener('input', function (e) { if (e.target && e.target.id === 'rfBpQ') { var v = e.target.value; clearTimeout(tbq); tbq = setTimeout(function () { B.q = v; R.key = null; draw(); }, 200); } });
  // ----- раздел «Фракционные войны»: фракции, живая статистика, LP-магазины милиций -----
  var FCOL = { 500003: '#d9a84a', 500002: '#c8643f', 500011: '#c04848', 500001: '#4a9ad9', 500004: '#4fb07a', 500010: '#b5b04a' };
  var W = { data: null, loading: false, sel: '', store: null, storeLoading: false, cat: '', q: '', sort: 'isk_lp', priced: false, tick: 0 };
  try {
    var ws = JSON.parse(localStorage.getItem('elw.reference.fw') || '{}');
    W.sel = ws.sel || ''; W.cat = ws.cat || ''; W.sort = ws.sort || 'isk_lp'; W.priced = !!ws.priced;
  } catch (e) { }
  function fwRemember() { try { localStorage.setItem('elw.reference.fw', JSON.stringify({ sel: W.sel, cat: W.cat, sort: W.sort, priced: W.priced })); } catch (e) { } }
  function fwLoad() {
    if (W.loading) return;
    W.loading = true;
    api('/api/reference/fw').then(function (j) {
      W.loading = false;
      if (!j.ok) return;
      W.data = j; R.key = null; draw();
      if (!j.live_at && j.online) setTimeout(function () { W.data = null; R.key = null; draw(); }, 6000);   // статистика догружается
    }, function () { W.loading = false; $('rfBody').innerHTML = '<section class="panel"><p class="in-bad">Нет связи с трекером.</p></section>'; });
  }
  function fwStore(id) {
    if (W.storeLoading) return;
    W.storeLoading = true;
    api('/api/reference/fw/store?id=' + encodeURIComponent(id)).then(function (j) {
      W.storeLoading = false;
      if (!j.ok || String(id) !== String(W.sel)) return;
      j.id = String(id); W.store = j; R.key = null; draw();
      setTimeout(function () { W.tick++; R.key = null; draw(); }, 4000);                                  // иконки
      if (!j.prices_at) setTimeout(function () { W.store = null; R.key = null; draw(); }, 8000);           // средние цены догружаются
    }, function () { W.storeLoading = false; });
  }
  function drawFw() {
    if (!W.data) { fwLoad(); $('rfBody').innerHTML = '<section class="panel"><p class="muted">Загружаю фракционные войны…</p></section>'; return; }
    var d = W.data, f = d.factions;
    if (!f.length) { $('rfBody').innerHTML = '<section class="panel"><p class="muted">Нет данных — нужен файл reference_fw.json (собирается скриптом build_reference_fw.py).</p></section>'; return; }
    if (!W.sel || !f.some(function (x) { return String(x.militia_id) === W.sel; })) W.sel = String(f[0].militia_id);
    var h = '<section class="panel"><h2>Фракционные войны <span class="muted small">фракции, милиции и их LP-магазины</span></h2>' +
      '<p class="small" style="margin:4px 0">Вступить в войну — значит записаться в милицию фракции (в окне агентов или у корпорации милиции; нужна репутация у фракции не ниже 0). ' +
      'Милиционеры захватывают комплексы в системах зоны боёв (плексинг), убивают пилотов вражеской милиции и выполняют задания милиции — за это начисляются LP милиции. ' +
      'LP тратят в магазине милиции (на станциях милиции и фракции): навигационные и фракционные корабли, модули, импланты, копии чертежей. Вражеская милиция — законная цель везде, в том числе в хай-секе.</p>' +
      '<p class="small muted" style="margin:4px 0 0">Статистика — из ESI' + (d.live_at ? ', обновлено ' + esc(L.fmtDateTime(d.live_at)) : d.online ? ' — загружаю…' : ' — онлайн-функции выключены') +
      (d.live_error ? ' (ошибка: ' + esc(d.live_error) + ')' : '') + '. «Вчера» — за прошлые игровые сутки. Магазины выгружены ' + esc(d.built || '—') + '.</p>' +
      '<div class="rf-fws">' + f.map(function (x) {
        var l = x.live, on = String(x.militia_id) === W.sel, st = function (v) { return l ? L.fmtInt(v) : '—'; };
        return '<div class="rf-fc' + (on ? ' on' : '') + '" style="border-left-color:' + (FCOL[x.id] || 'var(--muted)') + '">' +
          '<div><h3>' + esc(x.ru) + (x.pirate ? ' <span class="rf-cat rf-pir">пираты</span>' : '') + '</h3><div class="en">' + esc(x.name) + ' · милиция <b>' + esc(x.militia) + '</b>' + (x.hq ? ' · штаб ' + esc(x.hq) : '') + '</div></div>' +
          '<div class="rf-vs">Воюет с: ' + x.against_names.map(function (n) { return '<b>' + esc(n) + '</b>'; }).join(', ') + '</div>' +
          (x.note ? '<div class="rf-sub">' + esc(x.note) + '</div>' : '') +
          '<div class="rf-fst"><div><b>' + st(l && l.systems) + '</b><span>систем</span></div><div><b>' + st(l && l.contested) + '</b><span>оспаривается</span></div><div><b>' + st(l && l.pilots) + '</b><span>пилотов</span></div>' +
          '<div><b>' + st(l && l.kills_day) + '</b><span>убийств вчера</span></div><div><b>' + st(l && l.kills_week) + '</b><span>за неделю</span></div><div><b>' + (l ? L.fmtCompact(l.vp_day) : '—') + '</b><span>очков победы вчера</span></div></div>' +
          '<button type="button" class="btn' + (on ? ' primary' : '') + '" data-fw-sel="' + x.militia_id + '">LP-магазин · ' + x.offers + ' предложений</button></div>';
      }).join('') + '</div></section>';
    var fac = f.filter(function (x) { return String(x.militia_id) === W.sel; })[0];
    if (!W.store || W.store.id !== W.sel) { fwStore(W.sel); h += '<section class="panel"><p class="muted">Загружаю магазин ' + esc(fac.militia) + '…</p></section>'; }
    else h += fwShop(fac);
    var focus = document.activeElement && document.activeElement.id === 'rfFwQ', pos = focus ? document.activeElement.selectionStart : 0;
    $('rfBody').innerHTML = h;
    if (focus) { var qi = $('rfFwQ'); qi.focus(); qi.setSelectionRange(pos, pos); }
  }
  function fwShop(fac) {
    var st = W.store, q = W.q.trim().toLowerCase();
    var rows = st.offers.filter(function (o) {
      if (W.cat && String(o.cat) !== W.cat) return false;
      if (W.priced && o.isk_lp === null) return false;
      return !q || o.name.toLowerCase().indexOf(q) >= 0 || (o.ru && o.ru.toLowerCase().indexOf(q) >= 0) || o.group.toLowerCase().indexOf(q) >= 0;
    });
    var cmp = { isk_lp: function (a, b) { return (b.isk_lp === null ? -1e15 : b.isk_lp) - (a.isk_lp === null ? -1e15 : a.isk_lp); },
      lp: function (a, b) { return a.lp - b.lp; }, lp_desc: function (a, b) { return b.lp - a.lp; }, name: function (a, b) { return a.name.localeCompare(b.name); } };
    rows.sort(cmp[W.sort] || cmp.isk_lp);
    var mat = function (m) { return '<span class="rf-m">' + ico(m.type_id, 'sm') + ELW_cp(m.name) + ' <b>×' + L.fmtInt(m.qty) + '</b></span>'; };
    var h = '<section class="panel"><h2>LP-магазин: ' + esc(fac.militia) + ' <span class="muted small">' + esc(fac.ru) + '</span></h2>' +
      '<div class="rf-bar"><span class="lbl">Что</span>' + chip('data-fw-cat', '', 'всё<span class="n">' + st.offers.length + '</span>', !W.cat) +
      st.cats.map(function (c) { return chip('data-fw-cat', String(c[0]), esc(c[1]) + '<span class="n">' + c[2] + '</span>', W.cat === String(c[0])); }).join('') + '</div>' +
      '<div class="rf-bar"><input id="rfFwQ" type="search" placeholder="Поиск: предмет или группа…" aria-label="Поиск в магазине" value="' + esc(W.q) + '" style="flex:1 1 220px;min-width:0">' +
      '<select id="rfFwSort" aria-label="Сортировка"><option value="isk_lp"' + (W.sort === 'isk_lp' ? ' selected' : '') + '>ISK за LP — выгоднее</option>' +
      '<option value="lp"' + (W.sort === 'lp' ? ' selected' : '') + '>LP — дешевле</option><option value="lp_desc"' + (W.sort === 'lp_desc' ? ' selected' : '') + '>LP — дороже</option>' +
      '<option value="name"' + (W.sort === 'name' ? ' selected' : '') + '>по названию</option></select>' +
      '<label class="small"><input type="checkbox" id="rfFwPriced"' + (W.priced ? ' checked' : '') + '> только с оценкой ISK/LP</label></div>' +
      '<p class="small muted" style="margin:8px 0 0">Оценка — по средним ценам игры' + (st.prices_at ? ' (обновлено ' + esc(L.fmtDateTime(st.prices_at)) + ')' : ' — загружаю…') +
      ': ISK за LP = (цена предмета × кол-во − ISK − цена нужных предметов) ÷ LP. Средняя цена — ориентир, перед покупкой сверяйтесь с рынком. ' +
      'Для копий чертежей средней цены нет — у них оценки нет.</p></section>';
    h += '<section class="panel"><div class="small muted" style="margin-bottom:6px">Показано: ' + Math.min(rows.length, 400) + ' из ' + rows.length + (rows.length > 400 ? ' — уточните поиск' : '') + '</div>' +
      '<div class="tw"><table class="rf-t"><thead><tr><th class="l">Предмет</th><th class="r">Кол-во</th><th class="r">LP</th><th class="r">ISK</th><th class="l">Ещё нужно</th>' +
      '<th class="r hide-m">Ценность</th><th class="r">ISK за LP</th></tr></thead><tbody>' +
      rows.slice(0, 400).map(function (o) {
        return '<tr><td class="l">' + ico(o.type_id) + '<span class="rf-nm">' + ELW_cp(o.name) + '</span>' + (o.ru ? ' <span class="rf-sub">' + esc(o.ru) + '</span>' : '') +
          '<div class="rf-sub" style="padding-left:28px">' + esc(o.group) + (o.product ? ' · ' + toPlan(o.product.type_id, o.product.name) : '') + '</div></td><td class="r">' + L.fmtInt(o.qty) + '</td><td class="r">' + L.fmtInt(o.lp) + '</td>' +
          '<td class="r">' + (o.isk ? L.fmtCompact(o.isk) : '—') + '</td><td class="l rf-mats">' + (o.required.length ? o.required.map(mat).join('') : '<span class="rf-sub">—</span>') + '</td>' +
          '<td class="r hide-m">' + (o.value ? L.fmtCompact(o.value) : '—') + '</td>' +
          '<td class="r">' + (o.isk_lp === null ? '<span class="rf-sub">—</span>' : '<b class="' + (o.isk_lp > 0 ? 'rf-plus' : 'rf-minus') + '">' + L.fmtInt(o.isk_lp) + '</b>') + '</td></tr>';
      }).join('') + (rows.length ? '' : '<tr><td colspan="7" class="muted">Ничего не нашлось.</td></tr>') + '</tbody></table></div></section>';
    return h;
  }
  document.addEventListener('click', function (e) {
    var body = $('rfBody');
    if (!body || !body.contains(e.target) || R.section !== 'fw') return;
    var b = e.target.closest('[data-fw-sel],[data-fw-cat]');
    if (!b) return;
    if (b.hasAttribute('data-fw-sel')) { W.sel = b.getAttribute('data-fw-sel'); W.cat = ''; }
    else W.cat = b.getAttribute('data-fw-cat');
    fwRemember(); R.key = null; draw();
  });
  document.addEventListener('change', function (e) {
    if (e.target && e.target.id === 'rfFwSort') { W.sort = e.target.value; fwRemember(); R.key = null; draw(); }
    if (e.target && e.target.id === 'rfFwPriced') { W.priced = e.target.checked; fwRemember(); R.key = null; draw(); }
  });
  var tfq = null;
  document.addEventListener('input', function (e) { if (e.target && e.target.id === 'rfFwQ') { var v = e.target.value; clearTimeout(tfq); tfq = setTimeout(function () { W.q = v; R.key = null; draw(); }, 200); } });
  R.ready = true;
  setTimeout(function () { if ($('rfSections') && $('rfSections').offsetParent) draw(); }, 0);   // вкладка уже открыта при запуске
})(window.ELW);
