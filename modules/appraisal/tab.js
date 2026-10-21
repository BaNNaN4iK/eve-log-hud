// Вкладка модуля «Оценка» для страницы EVE Log HUD. Подключается ядром (window.ELW), см. modules/README.md.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, empty = ELW.empty, icon = ELW.icon, $ = ELW.$, S = ELW.S;
  var BASE = ELW.base;
  ELW.addTab({ id: "appraisal", title: "\u041e\u0446\u0435\u043d\u043a\u0430",
    css: "#apText{width:100%;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:13px/1.4 ui-monospace,Consolas,monospace;resize:vertical}\n.chg{font-size:11.5px;margin-right:6px} .chg.up{color:#2f8f4e} .chg.down{color:#d4483b}\n.tile.pick{outline:2px solid var(--accent)}",
    html: "      <section class=\"panel\"><h2>Оценка предметов <span class=\"muted small\">цены прямо с рынка игры</span></h2>\n        <label class=\"sr\" for=\"apText\">Список предметов</label>\n        <textarea id=\"apText\" rows=\"8\" spellcheck=\"false\" placeholder=\"Вставьте список из игры: выделите предметы в инвентаре или контракте → Ctrl+C → Ctrl+V сюда. Подойдут и строки «Название x 10», «10 Название», фит EFT.\"></textarea>\n        <div class=\"controls\" style=\"margin-top:8px\">\n          <label class=\"small muted\">Рынок <select id=\"apMarket\" aria-label=\"Рынок\">\n            <option value=\"jita\">Jita 4-4</option><option value=\"amarr\">Amarr</option><option value=\"dodixie\">Dodixie</option>\n            <option value=\"rens\">Rens</option><option value=\"hek\">Hek</option></select></label>\n          <label class=\"small muted\">Итог по <select id=\"apMode\" aria-label=\"Какую цену считать итогом\">\n            <option value=\"buy\">покупке (продать сразу)</option><option value=\"split\" selected>середине</option>\n            <option value=\"sell\">продаже (выставить ордер)</option></select></label>\n          <button type=\"button\" class=\"btn primary\" id=\"apGo\">Оценить</button>\n          <label class=\"small muted\">История <select id=\"apHist\" aria-label=\"Прошлые оценки\"><option value=\"\">—</option></select></label>\n          <span class=\"small muted\" id=\"apMsg\" role=\"status\" aria-live=\"polite\"></span>\n        </div>\n      </section>\n      <div id=\"apResult\"></div>\n    ",
    render: function () { renderAppraisal(); } });

  // ---------- оценка предметов (как Janice): цены хаба из ESI ----------
  var AP = { cur: null, unit: false, listAt: 0 };
  function apLoadList(force) {
    if (!force && Date.now() - AP.listAt < 30000) return;
    AP.listAt = Date.now();
    api('/api/appraisals').then(function (j) {
      if (!j.ok) return;
      var h = '<option value="">—</option>';
      (j.appraisals || []).forEach(function (a) {
        h += '<option value="' + esc(a.code) + '">' + esc(L.fmtDateTime(a.created) + ' · ' + a.market_name + ' · ' + a.items + ' поз. · ' + L.fmtCompact(a.split) + ' ISK') + '</option>';
      });
      $('apHist').innerHTML = h;
      if (AP.cur) $('apHist').value = AP.cur.code;
    }, function () { });
  }
  function apChange(v) {
    if (v === null || v === undefined) return '';
    return '<span class="chg ' + (v > 0 ? 'up' : v < 0 ? 'down' : '') + '" title="К средней цене за 7 дней">' + (v > 0 ? '+' : '') + esc(v.toFixed(1)) + '%</span>';
  }
  function apIsk(v) { return v === null || v === undefined ? '<span class="muted">нет ордеров</span>' : esc(L.fmtInt(Math.round(v * 100) / 100)) + ' ISK'; }
  function renderAppraisal() {
    apLoadList(false);
    var a = AP.cur, box = $('apResult');
    if (!a) { box.innerHTML = ''; return; }
    var t = a.totals, unit = AP.unit;
    var tile = function (key, label, v) {
      return '<div class="tile' + (a.mode === key ? ' pick' : '') + '"><div class="k">' + label + '</div><div class="v">' + esc(L.fmtInt(Math.round(v))) + '</div><div class="s">ISK</div></div>';
    };
    var h = '<section class="panel"><h2>Оценка ' + esc(a.code) + ' <span class="muted small">' + esc(a.market_name) + ' · ' + esc(L.fmtDateTime(a.created)) + '</span></h2>' +
      '<div class="tiles">' + tile('buy', 'Покупка (продать сразу)', t.buy) + tile('split', 'Середина', t.split) + tile('sell', 'Продажа (выставить ордер)', t.sell) +
      '<div class="tile"><div class="k">Объём</div><div class="v">' + esc(L.fmtInt(Math.round(t.volume * 100) / 100)) + '</div><div class="s">м³ · позиций ' + t.items + '</div></div></div>' +
      '<div class="controls" style="margin-top:10px"><button type="button" class="btn" id="apCopy">Скопировать итог</button>' +
      '<button type="button" class="btn" id="apCopyTable">Скопировать таблицу</button>' +
      '<button type="button" class="btn" id="apUnit">' + (unit ? 'Показать суммы' : 'Показать цену за штуку') + '</button>' +
      '<span class="small muted" id="apCopyMsg" role="status"></span></div>';
    if (a.missing && a.missing.length) h += '<p class="small" style="color:var(--warn)">Не найдено в игре: ' + esc(a.missing.join(', ')) + '</p>';
    if (a.unparsed && a.unparsed.length) h += '<p class="small muted">Не понял строки: ' + esc(a.unparsed.slice(0, 5).join(' · ')) + (a.unparsed.length > 5 ? ' …' : '') + '</p>';
    if (t.no_price) h += '<p class="small muted">Без цены (нет ордеров на станции): ' + t.no_price + '</p>';
    h += table('apRows', a.rows.map(function (r) { return Object.assign({ sortBuy: r.buy_total || 0, sortSell: r.sell_total || 0 }, r); }), [
      { k: 'name', t: 'Предмет', l: 1, f: function (r) { return icon(r.name) + esc(r.name); } },
      { k: 'qty', t: 'Количество', f: function (r) { return esc(L.fmtInt(r.qty)); } },
      { k: 'volume', t: 'Объём, м³', f: function (r) { return esc(L.fmtInt(Math.round((unit ? r.unit_volume : r.volume) * 100) / 100)); } },
      { k: 'sortBuy', t: 'Покупка', f: function (r) { return apChange(r.buy_change) + apIsk(unit ? r.buy : r.buy_total); } },
      { k: 'sortSell', t: 'Продажа', f: function (r) { return apChange(r.sell_change) + apIsk(unit ? r.sell : r.sell_total); } }
    ], { sort: { k: 'sortSell', d: -1 } });
    box.innerHTML = h + '</section>';
  }
  function apCopy(text, label) {
    var msg = $('apCopyMsg');
    function done(ok) { msg.textContent = ok ? 'Скопировано: ' + label : 'Не удалось — выделите текст вручную.'; }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    else done(false);
  }
  $('apResult').addEventListener('click', function (e) {
    var a = AP.cur;
    if (!a) return;
    if (e.target.id === 'apUnit') { AP.unit = !AP.unit; renderAppraisal(); }
    else if (e.target.id === 'apCopy') {
      var modeName = { buy: 'Покупка', split: 'Середина', sell: 'Продажа' }[a.mode];
      apCopy(a.market_name + ' · ' + modeName + ': ' + L.fmtInt(Math.round(a.totals[a.mode])) + ' ISK · объём ' + L.fmtInt(Math.round(a.totals.volume)) + ' м³', 'итог');
    } else if (e.target.id === 'apCopyTable') {
      var lines = ['Предмет\tКоличество\tОбъём м3\tПокупка ISK\tПродажа ISK'];
      a.rows.forEach(function (r) { lines.push([r.name, r.qty, Math.round(r.volume * 100) / 100, r.buy_total === null ? '' : Math.round(r.buy_total), r.sell_total === null ? '' : Math.round(r.sell_total)].join('\t')); });
      lines.push(['Итого', '', Math.round(a.totals.volume), Math.round(a.totals.buy), Math.round(a.totals.sell)].join('\t'));
      apCopy(lines.join('\n'), 'таблица (вставляется в Excel)');
    }
  });
  $('apGo').addEventListener('click', function () {
    var btn = this, msg = $('apMsg'), text = $('apText').value;
    if (!text.trim()) { msg.textContent = 'Вставьте список предметов.'; return; }
    btn.disabled = true; msg.textContent = 'Запрашиваю цены…';
    api('/api/appraise', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, market: $('apMarket').value, mode: $('apMode').value }) }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { msg.textContent = j.message || 'Не получилось.'; return; }
      msg.textContent = '';
      AP.cur = j;
      apLoadList(true);
      renderAppraisal();
    }, function () { btn.disabled = false; msg.textContent = 'Нет связи с трекером.'; });
  });
  $('apHist').addEventListener('change', function () {
    var code = this.value;
    if (!code) return;
    api('/api/appraisal?code=' + encodeURIComponent(code)).then(function (j) {
      if (j._status !== 200) return;
      AP.cur = j;
      $('apText').value = j.text || '';
      $('apMarket').value = j.market; $('apMode').value = j.mode;
      renderAppraisal();
    });
  });
})(window.ELW);
