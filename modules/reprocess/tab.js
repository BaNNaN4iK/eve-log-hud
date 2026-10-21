// Вкладка модуля «Переработка» для страницы EVE Log HUD. Подключается ядром (window.ELW), см. modules/README.md.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, $ = ELW.$, BASE = ELW.base;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };

  function opt(v, t) { return '<option value="' + v + '">' + t + '</option>'; }
  function lv(id, label, title) {
    var h = '<label class="small muted" title="' + title + '">' + label + ' <select id="' + id + '" aria-label="' + label + '">';
    for (var i = 0; i <= 5; i++) h += opt(i, i);
    return h + '</select></label>';
  }

  ELW.addTab({ id: 'reprocess', title: 'Переработка',
    css: '#rpText{width:100%;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:13px/1.4 ui-monospace,Consolas,monospace;resize:vertical}\n' +
      '.rp-grid{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:8px}\n.rp-yield{font-variant-numeric:tabular-nums;font-weight:650}\n' +
      '.rp-good{color:var(--good)} .rp-bad{color:var(--bad)} .rp-out{font-size:12px;color:var(--muted);white-space:normal}\n' +
      '.rp-ico{width:22px;height:22px;vertical-align:middle;margin-right:6px;border-radius:3px}\n.tile.pick{outline:2px solid var(--accent)}\n' +
      '#rpCustom input{width:5em;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:2px 6px}',
    html: '<section class="panel"><h2>Переработка <span class="muted small">что выйдет из руды, льда, модулей и кораблей — и что выгоднее</span></h2>' +
      '<label class="sr" for="rpText">Что перерабатываете</label>' +
      '<textarea id="rpText" rows="7" spellcheck="false" placeholder="Вставьте список из игры (выделить в инвентаре → Ctrl+C → Ctrl+V) или возьмите добычу из сессии кнопкой ниже."></textarea>' +
      '<div class="controls" style="margin-top:8px">' +
      '<label class="small muted">Добыча из сессии <select id="rpSession" aria-label="Взять добычу из сессии"><option value="">—</option></select></label>' +
      '<button type="button" class="btn primary" id="rpGo">Посчитать</button>' +
      '<span class="small muted" id="rpMsg" role="status" aria-live="polite"></span></div>' +
      '<details id="rpSet" style="margin-top:10px"><summary>Навыки и место переработки — выход руды <span class="rp-yield" id="rpOreY">…</span>, остального <span class="rp-yield" id="rpScrapY">…</span></summary>' +
      '<div class="rp-grid">' +
      '<label class="small muted">Где <select id="rpPlace" aria-label="Где перерабатываете">' + opt('station', 'станция NPC') + opt('athanor', 'Athanor') + opt('tatara', 'Tatara') + opt('other', 'другая структура') + '</select></label>' +
      '<label class="small muted">Риг <select id="rpRig" aria-label="Риг переработки">' + opt('none', 'нет') + opt('t1', 'T1') + opt('t2', 'T2') + '</select></label>' +
      '<label class="small muted">Безопасность <select id="rpSec" aria-label="Безопасность системы">' + opt('high', 'хай-сек') + opt('low', 'лоу-сек') + opt('null', 'нули / ВХ') + '</select></label>' +
      '<label class="small muted">Имплант <select id="rpImpl" aria-label="Имплант">' + opt('0', 'нет') + opt('1', 'RX-801 (+1%)') + opt('2', 'RX-802 (+2%)') + opt('4', 'RX-804 (+4%)') + '</select></label>' +
      '</div><div class="rp-grid">' +
      lv('rpR', 'Reprocessing', 'Переработка: +3% за уровень') +
      lv('rpRE', 'Reprocessing Efficiency', 'Эффективность переработки: +2% за уровень') +
      lv('rpOre', 'Обработка руды', 'Навык обработки этой руды (Simple/Coherent/… Ore Processing, Ice Processing): +2% за уровень') +
      lv('rpScrap', 'Scrapmetal Processing', 'Переработка модулей и кораблей: +2% за уровень') +
      '</div><div class="rp-grid" id="rpCustom">' +
      '<label class="small muted">Налог, % <input id="rpTax" inputmode="decimal" aria-label="Налог на переработку в процентах"></label>' +
      '<label class="small muted" title="Если знаете точный выход из окна переработки в игре — впишите, он заменит расчёт">Свой выход руды, % <input id="rpOreCustom" inputmode="decimal" placeholder="авто"></label>' +
      '<label class="small muted">Свой выход остального, % <input id="rpScrapCustom" inputmode="decimal" placeholder="авто"></label>' +
      '<label class="small muted">Рынок <select id="rpMarket" aria-label="Рынок">' + opt('jita', 'Jita 4-4') + opt('amarr', 'Amarr') + opt('dodixie', 'Dodixie') + opt('rens', 'Rens') + opt('hek', 'Hek') + '</select></label>' +
      '<label class="small muted">Цена <select id="rpMode" aria-label="Какую цену считать">' + opt('buy', 'покупки (продать сразу)') + opt('split', 'середина') + opt('sell', 'продажи (выставить ордер)') + '</select></label>' +
      '</div></details></section><div id="rpResult"></div>',
    render: function () { rpInit(); } });

  var RP = { cur: null, inited: false, sessionsAt: 0, sessions: {} };
  var FIELDS = [['rpPlace', 'place'], ['rpRig', 'rig'], ['rpSec', 'security'], ['rpImpl', 'implant'], ['rpR', 'reprocessing'], ['rpRE', 'efficiency'],
    ['rpOre', 'ore'], ['rpScrap', 'scrap'], ['rpTax', 'tax'], ['rpOreCustom', 'ore_yield'], ['rpScrapCustom', 'scrap_yield'], ['rpMarket', 'market'], ['rpMode', 'mode']];

  function settings() {
    var s = {};
    FIELDS.forEach(function (f) { s[f[1]] = $(f[0]).value; });
    return s;
  }
  function fill(s) {
    FIELDS.forEach(function (f) { var v = s[f[1]]; $(f[0]).value = v === null || v === undefined ? '' : String(v); });
    preview();
  }
  // выход — та же формула, что в reprocess.py (чтобы видеть цифру сразу при смене навыков)
  function preview() {
    var s = settings(), st = s.place !== 'station';
    var rig = { none: 0, t1: 1, t2: 3 }[s.rig] || 0, sec = { high: 0, low: 0.06, null: 0.12 }[s.security] || 0;
    var str = { station: 0, athanor: 0.02, tatara: 0.055, other: 0 }[s.place] || 0, impl = (+s.implant || 0) / 100;
    var ore = (50 + (st ? rig : 0)) / 100 * (1 + (st ? sec : 0)) * (1 + str) * (1 + 0.03 * s.reprocessing) * (1 + 0.02 * s.efficiency) * (1 + 0.02 * s.ore) * (1 + impl);
    var scrap = 0.5 * (1 + 0.02 * s.scrap);
    var num = function (v) { v = String(v || '').replace(',', '.'); return v === '' || isNaN(+v) ? null : +v / 100; };
    if (num(s.ore_yield) !== null) ore = num(s.ore_yield);
    if (num(s.scrap_yield) !== null) scrap = num(s.scrap_yield);
    $('rpOreY').textContent = (Math.min(ore, 1) * 100).toFixed(1).replace('.', ',') + '%';
    $('rpScrapY').textContent = (Math.min(scrap, 1) * 100).toFixed(1).replace('.', ',') + '%';
    var rigOn = s.place !== 'station';
    $('rpRig').disabled = !rigOn; $('rpSec').disabled = !rigOn;
  }

  function rpInit() {
    if (!RP.inited) {
      RP.inited = true;
      api('/api/reprocess/settings').then(function (j) { if (j.ok) fill(j.settings); }, function () { });
      FIELDS.forEach(function (f) { $(f[0]).addEventListener('change', preview); $(f[0]).addEventListener('input', preview); });
    }
    loadSessions();
    render();
  }

  // ---------- добыча из сессий трекера ----------
  function loadSessions() {
    if (Date.now() - RP.sessionsAt < 20000) return;
    RP.sessionsAt = Date.now();
    var since = Math.floor(Date.now() / 1000) - 14 * 86400;
    Promise.all([api('/api/live'), api('/api/history?since=' + since)]).then(function (res) {
      var live = (res[0] && res[0].sessions) || [], hist = ((res[1] && res[1].sessions) || []).slice().reverse();
      var list = [], seen = {};
      live.concat(hist).forEach(function (s) {
        if (seen[s.id] || !s.ore || !Object.keys(s.ore).length) return;
        seen[s.id] = 1; list.push(s);
      });
      RP.sessions = {};
      var cur = $('rpSession').value, h = '<option value="">—</option>';
      list.slice(0, 30).forEach(function (s, i) {
        RP.sessions[s.id] = s;
        var units = 0; Object.keys(s.ore).forEach(function (k) { units += s.ore[k]; });
        var isLive = live.some(function (x) { return x.id === s.id; });
        h += '<option value="' + esc(s.id) + '">' + esc((isLive ? 'идёт · ' : '') + s.who + ' · ' + L.fmtDateTime(s.t0) + ' · ' + L.fmtInt(units) + ' ед.') + '</option>';
      });
      $('rpSession').innerHTML = h;
      if (RP.sessions[cur]) $('rpSession').value = cur;
    }, function () { });
  }
  $('rpSession').addEventListener('change', function () {
    var s = RP.sessions[this.value];
    if (!s) return;
    $('rpText').value = Object.keys(s.ore).sort(function (a, b) { return s.ore[b] - s.ore[a]; })
      .map(function (k) { return k + '\t' + s.ore[k]; }).join('\n');
    $('rpGo').click();
  });

  // ---------- результат ----------
  function isk(v) { return v === null || v === undefined ? '<span class="muted">—</span>' : esc(L.fmtInt(v)) + ' ISK'; }
  function ico(id) { return '<img class="rp-ico" src="' + BASE + '/icons/' + id + '.png" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">'; }
  function render() {
    var a = RP.cur, box = $('rpResult');
    if (!a) { box.innerHTML = ''; return; }
    var t = a.totals, h = '<section class="panel"><h2>Результат <span class="muted small">выход руды ' + esc(String(a.ore_yield).replace('.', ',')) +
      '%, остального ' + esc(String(a.scrap_yield).replace('.', ',')) + '%' + (a.prices ? ' · цены ' + esc(a.market_name) : '') + '</span></h2>';
    if (a.prices) {
      var better = t.value > t.as_is;
      h += '<div class="tiles">' +
        '<div class="tile' + (!better ? ' pick' : '') + '"><div class="k">Продать как есть</div><div class="v">' + esc(L.fmtCompact(t.as_is)) + '</div><div class="s">ISK</div></div>' +
        '<div class="tile' + (better ? ' pick' : '') + '"><div class="k">Переработать и продать</div><div class="v">' + esc(L.fmtCompact(t.value)) + '</div><div class="s">ISK' + (t.tax ? ', налог ' + esc(L.fmtCompact(t.tax)) : '') + '</div></div>' +
        '<div class="tile"><div class="k">Лучший вариант по каждой строке</div><div class="v">' + esc(L.fmtCompact(t.best)) + '</div><div class="s">ISK</div></div>' +
        '<div class="tile"><div class="k">Объём</div><div class="v">' + esc(L.fmtInt(t.volume_out)) + '</div><div class="s">м³ после (было ' + esc(L.fmtInt(t.volume_in)) + ')</div></div></div>';
    } else {
      h += '<p class="small muted">' + esc(a.note || 'Цены не получены — показан только выход материалов.') + '</p>';
    }
    if (a.missing && a.missing.length) h += '<p class="small" style="color:var(--warn)">Не найдено в игре: ' + esc(a.missing.join(', ')) + '</p>';
    if (a.cannot && a.cannot.length) h += '<p class="small muted">Не перерабатывается: ' + esc(a.cannot.join(', ')) + '</p>';
    if (a.unparsed && a.unparsed.length) h += '<p class="small muted">Не понял строки: ' + esc(a.unparsed.slice(0, 5).join(' · ')) + '</p>';
    if (t.leftover) h += '<p class="small muted">Перерабатываются только целые порции (руда — по 100 шт.); остаток показан в столбце «Остаток» и учтён по цене как есть.</p>';

    h += '<h3 class="small muted" style="margin:14px 0 6px">Что получится</h3>' + table('rpMats', a.materials, [
      { k: 'name', t: 'Материал', l: 1, f: function (m) { return ico(m.type_id) + esc(m.name); } },
      { k: 'qty', t: 'Количество', f: function (m) { return esc(L.fmtInt(m.qty)); } },
      { k: 'volume', t: 'Объём, м³', f: function (m) { return esc(L.fmtInt(m.volume)); } },
      { k: 'price', t: 'Цена', f: function (m) { return m.price === null ? '<span class="muted">—</span>' : esc(L.fmtInt(Math.round(m.price * 100) / 100)); } },
      { k: 'value', t: 'Стоимость', f: function (m) { return isk(m.value); } }
    ], { sort: { k: 'value', d: -1 }, empty: 'Ничего не выйдет: меньше одной порции.' });

    h += '<h3 class="small muted" style="margin:14px 0 6px">По предметам</h3>' + table('rpRows', a.rows.map(function (r) {
      return Object.assign({ sortGain: r.gain === null ? -1e18 : r.gain }, r);
    }), [
      { k: 'name', t: 'Предмет', l: 1, f: function (r) {
        return ico(r.type_id) + esc(r.name) + '<div class="rp-out">' + esc(r.out.slice(0, 6).map(function (o) { return o.name + ' ' + L.fmtInt(o.qty); }).join(' · ')) + (r.out.length > 6 ? ' …' : '') + '</div>'; } },
      { k: 'qty', t: 'Количество', f: function (r) { return esc(L.fmtInt(r.qty)); } },
      { k: 'left', t: 'Остаток', f: function (r) { return r.left ? esc(L.fmtInt(r.left)) : ''; } },
      { k: 'yield', t: 'Выход', f: function (r) { return esc(String(r.yield).replace('.', ',')) + '%'; } },
      { k: 'as_is', t: 'Как есть', f: function (r) { return isk(r.as_is); } },
      { k: 'value', t: 'Переработать', f: function (r) { return isk(r.value); } },
      { k: 'sortGain', t: 'Выгоднее', f: function (r) {
        if (!r.verdict) return '<span class="muted">—</span>';
        return r.verdict === 'reprocess' ? '<span class="rp-good">переработать +' + esc(L.fmtCompact(r.gain)) + '</span>'
          : '<span class="rp-bad">продать как есть +' + esc(L.fmtCompact(-r.gain)) + '</span>'; } }
    ], { sort: { k: 'sortGain', d: -1 } });

    h += '<div class="controls" style="margin-top:10px"><button type="button" class="btn" id="rpCopy">Скопировать материалы</button>' +
      '<span class="small muted" id="rpCopyMsg" role="status"></span></div>';
    box.innerHTML = h + '</section>';
  }
  $('rpResult').addEventListener('click', function (e) {
    if (e.target.id !== 'rpCopy' || !RP.cur) return;
    var text = RP.cur.materials.map(function (m) { return m.name + '\t' + m.qty; }).join('\n'), msg = $('rpCopyMsg');
    function done(ok) { msg.textContent = ok ? 'Скопировано — вставляется в «Оценку», контракт или Excel.' : 'Не удалось — выделите текст вручную.'; }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    else done(false);
  });
  $('rpGo').addEventListener('click', function () {
    var btn = this, msg = $('rpMsg'), text = $('rpText').value;
    if (!text.trim()) { msg.textContent = 'Вставьте список или выберите сессию.'; return; }
    btn.disabled = true; msg.textContent = 'Считаю…';
    api('/api/reprocess', { method: 'POST', headers: POST, body: JSON.stringify({ text: text, settings: settings() }) }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { msg.textContent = j.message || 'Не получилось.'; return; }
      msg.textContent = '';
      RP.cur = j;
      render();
      setTimeout(function () { if (RP.cur === j) render(); }, 4000);      // иконки догружаются в фоне
    }, function () { btn.disabled = false; msg.textContent = 'Нет связи с трекером.'; });
  });
})(window.ELW);
