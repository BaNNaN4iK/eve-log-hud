// Сканер прибыльности модуля «Производство»: все чертежи хаба карточками (как ISK Scout). Рисуется во вкладке из tab.js.
(function (ELW) {
  'use strict';
  if (!ELW) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var HUBS = [['jita', 'Jita 4-4'], ['amarr', 'Amarr'], ['dodixie', 'Dodixie'], ['rens', 'Rens'], ['hek', 'Hek']];
  var SORTS = [['isk_hour', 'ISK в час'], ['profit', 'Прибыль'], ['margin', 'Маржа'], ['volume', 'Предложение']];
  var CATS = [['', 'Всё'], ['ships', 'Корабли'], ['modules', 'Модули'], ['charges', 'Заряды'], ['drones', 'Дроны'], ['components', 'Компоненты'],
    ['implants', 'Импланты'], ['structures', 'Структуры'], ['materials', 'Материалы'], ['other', 'Прочее']];
  var SC = { market: 'jita', sort: 'isk_hour', mode: 'sell', cat: '', q: '', page: 1, sure: false, bpc: false, thin: false, odd: false,
             data: null, key: '', at: 0, busy: false, built: false };
  try { var saved = JSON.parse(localStorage.getItem('elw.industry.scan') || '{}'); ['market', 'sort', 'mode', 'cat', 'sure'].forEach(function (k) { if (saved[k] !== undefined) SC[k] = saved[k]; }); } catch (e) { }
  function remember() { try { localStorage.setItem('elw.industry.scan', JSON.stringify({ market: SC.market, sort: SC.sort, mode: SC.mode, cat: SC.cat, sure: SC.sure })); } catch (e) { } }

  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function ago(ts) {
    if (!ts) return 'не загружены';
    var m = Math.round((Date.now() / 1000 - ts) / 60);
    return m < 1 ? 'только что' : m < 60 ? m + ' мин назад' : Math.round(m / 60) + ' ч назад';
  }
  function chip(group, value, label, on, extra) {
    return '<button type="button" class="in-chip' + (on ? ' on' : '') + '" data-' + group + '="' + esc(value) + '">' + label + (extra ? '<span class="n">' + extra + '</span>' : '') + '</button>';
  }
  function query() {
    return '/api/industry/scan?market=' + SC.market + '&sort=' + SC.sort + '&mode=' + SC.mode + '&cat=' + encodeURIComponent(SC.cat) +
      '&q=' + encodeURIComponent(SC.q) + '&page=' + SC.page + '&sure=' + (SC.sure ? 1 : 0) + '&bpc=' + (SC.bpc ? 1 : 0) + '&thin=' + (SC.thin ? 1 : 0) + '&odd=' + (SC.odd ? 1 : 0);
  }

  function shell() {
    var box = $('inScanView');
    if (!box || SC.built) return;
    SC.built = true;
    box.innerHTML = '<section class="panel"><h2>Сканер прибыльности <span class="muted small">все чертежи хаба: что выгодно строить прямо сейчас</span></h2>' +
      '<p class="small muted" style="margin-top:0">Считается один прогон каждого чертежа с вашими настройками (ME, TE, сооружение, налоги — на экране «Калькулятор») ' +
      'по ценам хаба. Стоимость работы — по индексу системы хаба. Нажмите на карточку — откроется подробный расчёт.</p>' +
      '<div class="in-chips" id="scHubs"></div><div id="scStatus" class="small" style="margin-top:8px"></div>' +
      '<div class="in-chips" style="margin-top:12px"><span class="small muted">Сортировка</span><span id="scSorts" class="in-chips"></span>' +
      '<span class="small muted" style="margin-left:10px">Продаю</span><span id="scModes" class="in-chips"></span></div>' +
      '<div class="in-chips" id="scCats" style="margin-top:8px"></div>' +
      '<div class="in-chips" style="margin-top:10px"><input id="scQ" type="search" placeholder="Поиск предмета…" aria-label="Поиск предмета" spellcheck="false" ' +
      'style="flex:1 1 260px;min-width:0;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px">' +
      '<label class="small"><input type="checkbox" id="scSure"> только надёжные' + ELW_INDUSTRY.help('sc_sure') + '</label></div>' +
      '<div id="scFilters" class="small muted" style="margin-top:8px"></div><div id="scSettings" class="small muted" style="margin-top:4px"></div></section>' +
      '<div id="scList"></div>';
    $('scQ').value = SC.q; $('scSure').checked = SC.sure;
    var t = null;
    $('scQ').addEventListener('input', function () { var v = this.value; clearTimeout(t); t = setTimeout(function () { SC.q = v; SC.page = 1; load(); }, 250); });
    $('scSure').addEventListener('change', function () { SC.sure = this.checked; SC.page = 1; remember(); load(); });
    box.addEventListener('click', onClick);
    box.addEventListener('keydown', function (e) {
      var c = e.target.closest && e.target.closest('.sc-card');
      if (c && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); ELW_INDUSTRY.open(c.getAttribute('data-name'), c.getAttribute('data-src'), (SC.data.settings || {}).me, (SC.data.settings || {}).te); }
    });
  }

  function onClick(e) {
    var b = e.target.closest && e.target.closest('[data-hub],[data-sort],[data-mode],[data-cat],[data-page],[data-flag],#scRefresh,#scEdit,.sc-card');
    if (!b) return;
    if (b.classList.contains('sc-card')) { ELW_INDUSTRY.open(b.getAttribute('data-name'), b.getAttribute('data-src'), (SC.data.settings || {}).me, (SC.data.settings || {}).te); return; }
    if (b.id === 'scRefresh') { refresh(); return; }
    if (b.id === 'scEdit') { $('inViewCalc').click(); return; }
    if (b.hasAttribute('data-hub')) { SC.market = b.getAttribute('data-hub'); SC.page = 1; }
    else if (b.hasAttribute('data-sort')) { SC.sort = b.getAttribute('data-sort'); SC.page = 1; }
    else if (b.hasAttribute('data-mode')) { SC.mode = b.getAttribute('data-mode'); SC.page = 1; }
    else if (b.hasAttribute('data-cat')) { SC.cat = b.getAttribute('data-cat'); SC.page = 1; }
    else if (b.hasAttribute('data-page')) { SC.page = +b.getAttribute('data-page'); window.scrollTo(0, $('scList').offsetTop - 80); }
    else if (b.hasAttribute('data-flag')) { var f = b.getAttribute('data-flag'); SC[f] = !SC[f]; SC.page = 1; }
    remember();
    load();
  }

  function refresh() {
    api('/api/industry/scan/refresh', { method: 'POST', headers: POST, body: JSON.stringify({ market: SC.market }) }).then(function (j) {
      if (!j.ok) { $('scStatus').innerHTML = '<span class="in-bad">' + esc(j.message) + '</span>'; return; }
      load();
    });
  }

  function load() {
    if (SC.busy) { SC.again = true; return; }
    SC.busy = true;
    var key = query();
    api(key).then(function (j) {
      SC.busy = false;
      if (j.ok) { SC.data = j; SC.key = key; SC.at = Date.now(); draw(); }
      if (SC.again) { SC.again = false; load(); }
    }, function () { SC.busy = false; });
  }

  function draw() {
    var d = SC.data;
    if (!d) return;
    var st = d.status || {}, ages = d.ages || {};
    $('scHubs').innerHTML = HUBS.map(function (h) {
      return chip('hub', h[0], h[1], h[0] === SC.market, h[0] === SC.market && d.counts[h[0]] ? d.counts[h[0]] : ages[h[0]] ? '' : '·');
    }).join('');
    var s = '';
    if (st.running) {
      var pct = st.pages ? Math.round(st.done * 100 / st.pages) : 0;
      s = 'Загружаю все ордера ' + esc(d.market_name) + ': ' + st.done + ' из ' + (st.pages || '…') + ' страниц' +
        '<div class="sc-bar" role="progressbar" aria-valuenow="' + pct + '" aria-valuemin="0" aria-valuemax="100"><div style="width:' + pct + '%"></div></div>';
    } else {
      s = 'Цены ' + esc(d.market_name) + ': ' + ago(st.at) + ' <button type="button" class="btn" id="scRefresh" style="margin-left:6px">' +
        (st.at ? 'Обновить цены' : 'Загрузить цены') + '</button>' + (st.error ? ' <span class="in-bad">' + esc(st.error) + '</span>' : '');
      if (!st.at) s += '<div class="muted" style="margin-top:4px">Сканер берёт все ордера региона: для Jita это ~400 страниц ESI, 1–4 минуты; для Rens или Hek — меньше минуты. Дальше цены хранятся на диске.</div>';
    }
    if (d.demand && d.demand.running) s += '<div class="muted" style="margin-top:4px">Проверяю спрос (история продаж): ' + d.demand.done + ' из ' + d.demand.todo + '…</div>';
    $('scStatus').innerHTML = s;
    $('scSorts').innerHTML = SORTS.map(function (x) { return chip('sort', x[0], x[1], x[0] === SC.sort); }).join('');
    $('scModes').innerHTML = chip('mode', 'sell', 'своим ордером', SC.mode === 'sell') + chip('mode', 'buy', 'мгновенно', SC.mode === 'buy');
    $('scCats').innerHTML = CATS.map(function (x) { return chip('cat', x[0], x[1], x[0] === SC.cat); }).join('');
    var flag = function (key, label, n) {
      return n || SC[key] ? '<button type="button" class="in-chip' + (SC[key] ? ' on' : '') + '" data-flag="' + key + '">' + (SC[key] ? 'скрыть ' : 'показать ') + label + ' <span class="n">' + n + '</span></button>' : '';
    };
    $('scFilters').innerHTML = '<span class="in-chips">' + flag('thin', 'с малым спросом', d.thin) + flag('bpc', 'редкие и из LP-магазина', d.rare) + flag('odd', 'с подозрительной ценой', d.odd) + '</span>';
    var se = d.settings || {};
    $('scSettings').innerHTML = 'Настройки расчёта: ME ' + se.me + ' / TE ' + se.te + ' · ' + esc({ station: 'станция NPC', raitaru: 'Raitaru', azbel: 'Azbel', sotiyo: 'Sotiyo', athanor: 'Athanor', tatara: 'Tatara', other: 'структура' }[se.structure] || '') +
      (se.rig !== 'none' ? ', риг ' + se.rig.toUpperCase() : '') + ' · материалы ' + (se.buy_mode === 'sell' ? 'покупаю сразу' : se.buy_mode === 'buy' ? 'своим ордером' : 'по середине') +
      ' · T2 из изобретения: ME 2 / TE 4' + ' · налог ' + String(se.sales_tax).replace('.', ',') + '%, брокер ' + String(se.broker).replace('.', ',') + '% <button type="button" class="in-back" id="scEdit" style="margin:0 0 0 6px">изменить</button>';

    var list = $('scList'), h = '';
    if (!st.at && !st.running) { list.innerHTML = ''; return; }
    h += '<div class="small muted" style="margin:10px 2px 0">Выгодных: ' + L.fmtInt(d.total) + ' из ' + L.fmtInt(d.scanned) + ' чертежей с ценами' + (d.pages > 1 ? ' · страница ' + d.page + ' из ' + d.pages : '') + '</div>';
    d.rows.forEach(function (r) {
      var m = r[SC.mode] || {}, other = r[SC.mode === 'sell' ? 'buy' : 'sell'] || {};
      var perDay = r.week ? r.week / 7 : null;
      var badges = (r.sure ? '<span class="sc-badge sure" title="Выгодно и при продаже ордером, и при мгновенной продаже">надёжно</span>' : '') +
        (r.src === 'inv' ? '<span class="sc-badge t2" title="Чертёж получают изобретением: посчитано с ME 2 / TE 4, без стоимости самого изобретения (датакоры, копии)">изобретение</span>' : '') +
        (r.src === 'lp' || r.src === 'bpc' ? '<span class="sc-badge lp" title="Чертёж — редкая копия или из LP-магазина: на рынке оригинала нет">редкий чертёж</span>' : '') +
        (r.kind === 'r' ? '<span class="sc-badge">реакция</span>' : '');
      h += '<div class="sc-card" tabindex="0" role="button" data-src="' + esc(r.src) + '" data-name="' + esc(r.name) + '" aria-label="Открыть расчёт: ' + esc(r.name) + '"><div class="sc-ico">' + ELW_INDUSTRY.ico(r.id) + '</div>' +
        '<div><div class="sc-name">' + esc(r.name) + badges + '</div>' +
        '<div class="sc-meta">Время <b>' + esc(L.fmtDur(Math.round(r.time))) + '</b> · выход <b>' + L.fmtInt(r.out) + '</b> · себестоимость <b>' + esc(isk(r.cost)) + '</b>' +
        ' · на рынке <b>' + L.fmtInt(r.supply || 0) + '</b> шт.</div>' +
        '<div class="sc-meta">Спрос: ' + (r.week === null || r.week === undefined ? '<span class="muted">проверяется…</span>' : 'за неделю <b>' + L.fmtInt(r.week) + '</b>' +
          (perDay ? ' · ≈ ' + L.fmtInt(Math.round(perDay)) + ' в день · прогон продастся за ' + (r.out / perDay < 1 ? 'день' : '≈ ' + Math.ceil(r.out / perDay) + ' дн.') : ' · продаж не было')) + '</div></div>' +
        '<div class="sc-right"><div class="sc-big' + (m.isk_hour < 0 ? ' neg' : '') + '">' + esc(isk(m.isk_hour)) + '/ч</div>' +
        '<div class="sc-sub">' + esc(isk(m.profit)) + ' за прогон · ' + (m.margin === null || m.margin === undefined ? '—' : String(Math.round(m.margin * 10) / 10).replace('.', ',') + '%') + '</div>' +
        '<div class="sc-sub">' + (SC.mode === 'sell' ? 'мгновенно ' : 'ордером ') + esc(isk(other.isk_hour)) + '/ч</div></div><div class="sc-arrow" aria-hidden="true">›</div></div>';
    });
    if (!d.rows.length) h += '<div class="panel small muted" style="margin-top:8px">Ничего не нашлось. Попробуйте другую категорию или снимите фильтры.</div>';
    if (d.pages > 1) {
      var p = d.page, pages = [1, p - 2, p - 1, p, p + 1, p + 2, d.pages].filter(function (x, i, a) { return x >= 1 && x <= d.pages && a.indexOf(x) === i; }).sort(function (a, b) { return a - b; });
      h += '<div class="sc-pages">' + (p > 1 ? chip('page', p - 1, '←', false) : '') + pages.map(function (x) { return chip('page', x, String(x), x === p); }).join('') + (p < d.pages ? chip('page', p + 1, '→', false) : '') + '</div>';
    }
    list.innerHTML = h;
  }

  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.scanner = {
    render: function (force) {
      shell();
      var d = SC.data, live = d && ((d.status && d.status.running) || (d.demand && d.demand.running));
      if (force || !d || SC.key !== query() || (live && Date.now() - SC.at > 2500)) load();
    }
  };
})(window.ELW);
