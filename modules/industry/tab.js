// Вкладка модуля «Производство». Подключается ядром (window.ELW), см. modules/README.md.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, $ = ELW.$, BASE = ELW.base;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };

  function opt(v, t) { return '<option value="' + v + '">' + t + '</option>'; }
  function lv(id, label, hi, title) {
    var h = '<label class="small muted" title="' + (title || '') + '">' + label + '<select id="' + id + '">';
    for (var i = 0; i <= hi; i++) h += opt(i, i);
    return h + '</select></label>';
  }
  function inp(id, label, ph, title) { return '<label class="small muted" title="' + (title || '') + '">' + label + '<input id="' + id + '" inputmode="decimal" placeholder="' + (ph || '') + '"></label>'; }
  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function ico(t) { return t ? '<img class="in-ico" src="' + BASE + '/icons/' + t + '.png" alt="" loading="lazy">' : ''; }
  function dur(s) { return s ? L.fmtDur(Math.round(s)) : '—'; }

  ELW.addTab({ id: 'industry', title: 'Производство',
    css: '.in-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px 14px;margin-top:8px}\n' +
      '.in-grid input,.in-grid select,#inProduct{width:100%;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px}\n' +
      '.in-ico{width:20px;height:20px;vertical-align:middle;margin-right:5px;border-radius:3px}.in-sub{font-size:11.5px;color:var(--muted)}\n' +
      '.in-good{color:var(--good)}.in-bad{color:var(--bad)} details.in-set{margin-top:10px}details.in-set>summary{cursor:pointer;color:var(--muted);font-size:13px}\n' +
      'tr.in-built>td:first-child{box-shadow:inset 4px 0 0 var(--accent)} .in-ind{display:inline-block}',
    html: '<section class="panel"><h2>Калькулятор производства <span class="muted small">материалы, стоимость работы, время и прибыль</span></h2>' +
      '<div class="in-grid" style="grid-template-columns:minmax(260px,2fr) repeat(3,minmax(110px,1fr))">' +
      '<label class="small muted">Что строим<input id="inProduct" list="inList" autocomplete="off" spellcheck="false" placeholder="например: Vexor, Hobgoblin II, Ishtar"><datalist id="inList"></datalist></label>' +
      inp('inRuns', 'Прогонов', '1') + lv('inMe', 'ME чертежа', 10, 'Material Efficiency: −1% материалов за уровень') + lv('inTe', 'TE чертежа', 20, 'Time Efficiency: −1% времени за уровень') +
      '</div>' +
      '<details class="in-set" open><summary>Где строим и навыки</summary><div class="in-grid">' +
      '<label class="small muted">Сооружение<select id="inStruct">' + opt('station', 'станция NPC') + opt('raitaru', 'Raitaru') + opt('azbel', 'Azbel') + opt('sotiyo', 'Sotiyo') +
        opt('athanor', 'Athanor (реакции)') + opt('tatara', 'Tatara (реакции)') + opt('other', 'другая структура') + '</select></label>' +
      '<label class="small muted">Риг<select id="inRig">' + opt('none', 'нет') + opt('t1', 'T1') + opt('t2', 'T2') + '</select></label>' +
      '<label class="small muted">Безопасность<select id="inSec">' + opt('high', 'хай-сек') + opt('low', 'лоу-сек') + opt('null', 'нули / ВХ') + '</select></label>' +
      '<label class="small muted" title="Индекс стоимости работ берётся из игры по системе">Система (для индекса)<input id="inSystem" spellcheck="false" placeholder="например: Jita"></label>' +
      inp('inIndex', 'Свой индекс, %', 'авто', 'Если знаете индекс системы — впишите, он заменит данные игры') +
      inp('inTax', 'Налог сооружения, %', '0,25', 'Станция NPC — 0,25%; в структуре — сколько поставил владелец') +
      inp('inScc', 'Сбор SCC, %', '4', 'Надбавка SCC к стоимости работы') +
      lv('inInd', 'Industry', 5, '−4% времени производства за уровень') + lv('inAdv', 'Advanced Industry', 5, '−3% времени за уровень') +
      lv('inReact', 'Reactions', 5, '−4% времени реакций за уровень') +
      lv('inCme', 'ME компонентов', 10, 'Для компонентов, которые строите сами') + lv('inCte', 'TE компонентов', 20) +
      '</div></details>' +
      '<details class="in-set"><summary>Цены и налоги</summary><div class="in-grid">' +
      '<label class="small muted">Рынок<select id="inMarket">' + opt('jita', 'Jita 4-4') + opt('amarr', 'Amarr') + opt('dodixie', 'Dodixie') + opt('rens', 'Rens') + opt('hek', 'Hek') + '</select></label>' +
      '<label class="small muted">Материалы покупаю<select id="inBuy">' + opt('sell', 'сразу (по ордерам продажи)') + opt('buy', 'своим ордером (по покупке)') + opt('split', 'по середине') + '</select></label>' +
      '<label class="small muted">Продукт продаю<select id="inSell">' + opt('sell', 'своим ордером (по продаже)') + opt('buy', 'сразу (в ордера покупки)') + opt('split', 'по середине') + '</select></label>' +
      inp('inSalesTax', 'Налог с продаж, %', '3,6') + inp('inBroker', 'Брокер, %', '1,5', 'Комиссия брокера за выставление ордера (только при продаже своим ордером)') +
      '</div></details>' +
      '<div class="controls" style="margin-top:10px"><button type="button" class="btn primary" id="inGo">Посчитать</button>' +
      '<span class="small" id="inMsg" role="status" aria-live="polite"></span></div></section><div id="inResult"></div>',
    render: function () {
      init();
      var key = JSON.stringify((ELW.S && ELW.S.sort) || {});             // ядро зовёт render() каждые 4 с и при сортировке
      if (I.sortKey !== key) { I.sortKey = key; draw(); }
    } });

  var F = [['inRuns', 'runs'], ['inMe', 'me'], ['inTe', 'te'], ['inStruct', 'structure'], ['inRig', 'rig'], ['inSec', 'security'], ['inSystem', 'system'],
    ['inIndex', 'cost_index'], ['inTax', 'facility_tax'], ['inScc', 'scc'], ['inInd', 'industry'], ['inAdv', 'adv_industry'], ['inReact', 'reactions'],
    ['inCme', 'comp_me'], ['inCte', 'comp_te'], ['inMarket', 'market'], ['inBuy', 'buy_mode'], ['inSell', 'sell_mode'], ['inSalesTax', 'sales_tax'], ['inBroker', 'broker']];
  var I = { inited: false, res: null, build: [], t: null };

  function settings() {
    var s = { build: I.build };
    F.forEach(function (f) { s[f[1]] = $(f[0]).value; });
    return s;
  }
  function fill(s) {
    F.forEach(function (f) { var v = s[f[1]]; $(f[0]).value = v === null || v === undefined ? '' : String(v).replace('.', ','); });
    I.build = s.build || [];
  }
  function init() {
    if (I.inited) return;
    I.inited = true;
    api('/api/industry/settings').then(function (j) {
      if (!j.ok) return;
      fill(j.settings);
      if (j.product) $('inProduct').value = j.product;
      if (!j.prices) $('inMsg').textContent = 'Онлайн-функции выключены: будут материалы и время, без цен.';
    }, function () { });
  }

  $('inProduct').addEventListener('input', function () {
    var q = this.value;
    clearTimeout(I.t);
    if (q.length < 2) return;
    I.t = setTimeout(function () {
      api('/api/industry/search?q=' + encodeURIComponent(q)).then(function (j) {
        $('inList').innerHTML = (j.items || []).map(function (i) { return '<option value="' + esc(i.name) + '">' + (i.kind === 'r' ? 'реакция' : '') + '</option>'; }).join('');
      }, function () { });
    }, 200);
  });
  $('inProduct').addEventListener('change', function () { I.build = []; });
  $('inProduct').addEventListener('keydown', function (e) { if (e.key === 'Enter') calc(); });
  $('inGo').addEventListener('click', function () { calc(); });

  function calc() {
    var msg = $('inMsg'), btn = $('inGo');
    if (!$('inProduct').value.trim()) { msg.textContent = 'Укажите, что строить.'; return; }
    btn.disabled = true; msg.textContent = 'Считаю…';
    api('/api/industry', { method: 'POST', headers: POST, body: JSON.stringify({ product: $('inProduct').value, settings: settings() }) }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { msg.innerHTML = '<span class="in-bad">' + esc(j.message || 'Не получилось.') + '</span>'; return; }
      msg.textContent = j.note || '';
      I.res = j; I.build = j.settings.build || [];
      draw();
      setTimeout(function () { if (I.res === j) draw(); }, 4000);           // иконки догружаются
    }, function () { btn.disabled = false; msg.textContent = 'Нет связи с трекером.'; });
  }

  // строки материалов: дерево с вложенными компонентами, которые строим сами
  function matRows(node, depth, out) {
    node.materials.forEach(function (m) {
      out.push({ m: m, depth: depth });
      if (m.build) matRows(m.build, depth + 1, out);
    });
    return out;
  }

  function draw() {
    var r = I.res, box = $('inResult');
    if (!r) { box.innerHTML = ''; return; }
    var t = r.totals, p = r.product, up = r.unit_prices || {};
    var tile = function (k, v, s, cls) { return '<div class="tile"><div class="k">' + k + '</div><div class="v' + (cls ? ' ' + cls : '') + '">' + v + '</div><div class="s">' + (s || '') + '</div></div>'; };
    var h = '<section class="panel"><h2>' + ico(p.type_id) + esc(p.name) + ' <span class="muted small">' + (p.kind === 'r' ? 'реакция' : 'производство') + ' · ' + L.fmtInt(p.units) + ' шт. · ' +
      esc(r.market_name) + (r.cost_index !== null && r.cost_index !== undefined ? ' · индекс ' + String(Math.round(r.cost_index * 100) / 100).replace('.', ',') + '%' + (r.system ? ' (' + esc(r.system) + ')' : '') : '') + '</span></h2>';
    if (r.warning) h += '<p class="small in-bad">' + esc(r.warning) + '</p>';
    if (r.cost_index === null || r.cost_index === undefined) h += '<p class="small muted">Стоимость работы не посчитана: укажите систему (индекс возьмётся из игры) или впишите свой индекс.</p>';
    if (r.missing_price && r.missing_price.length) h += '<p class="small" style="color:var(--warn)">Нет цены на рынке: ' + esc(r.missing_price.join(', ')) + '</p>';
    h += '<div class="tiles">' +
      tile('Себестоимость', isk(t.cost), 'за штуку ' + isk(t.per_unit) + ' ISK') +
      tile('Материалы', isk(t.materials), 'работы ' + isk(t.jobs) + ' ISK') +
      tile('Продажа', isk(t.revenue), 'за штуку ' + isk(p.price) + ' · налоги ' + isk(t.fees)) +
      tile('Прибыль', isk(t.profit), t.margin === null || t.margin === undefined ? '' : 'маржа ' + String(t.margin).replace('.', ',') + '%', t.profit > 0 ? 'in-good' : t.profit < 0 ? 'in-bad' : '') +
      tile('ISK в час', isk(t.isk_hour), 'по времени всех работ') +
      tile('Время', dur(t.top_time), r.jobs.length > 1 ? 'всех работ подряд ' + dur(t.time) : '') +
      tile('Закупка', L.fmtInt(t.volume) + ' м³', r.shopping.length + ' позиций') + '</div>';
    if (/ II$| III$/.test(p.name) || r.tree.materials.some(function (m) { return m.kind && /^(R\.A\.M|Construction Blocks)/.test(m.name); })) {
      h += '<p class="small muted">Чертежи T2 после изобретения обычно ME 2 / TE 4 — проверьте ME и TE.</p>';
    }

    // материалы (дерево)
    var rows = matRows(r.tree, 0, []);
    h += '<h3 class="small muted" style="margin:16px 0 6px">Материалы — отметьте, что строите сами, а не покупаете</h3>' +
      table('inMats', rows.map(function (x) {
        var m = x.m, price = up[String(m.type_id)];
        return { name: m.name, qty: m.qty, depth: x.depth, m: m, price: price, total: price !== null && price !== undefined ? price * m.qty : null };
      }), [
        { k: '', t: 'Материал', l: 1, f: function (x) {
          var m = x.m;
          return '<span class="in-ind" style="padding-left:' + (x.depth * 22) + 'px">' + ico(m.type_id) + esc(m.name) + '</span>' +
            (m.build ? '<div class="in-sub" style="padding-left:' + (x.depth * 22 + 25) + 'px">строю: ' + L.fmtInt(m.build.runs) + ' прог. → ' + L.fmtInt(m.build.out) + ' шт.' + (m.build.out > m.qty ? ', останется ' + L.fmtInt(m.build.out - m.qty) : '') + '</div>' : '');
        } },
        { k: '', t: 'Нужно', f: function (x) { return esc(L.fmtInt(x.qty)); } },
        { k: '', t: 'Цена', f: function (x) { return x.m.build ? '<span class="muted">строю</span>' : esc(isk(x.price)); } },
        { k: '', t: 'Купить за', f: function (x) { return x.m.build ? '<span class="muted">' + esc(isk(x.total)) + '</span>' : esc(isk(x.total)); } },
        { k: '', t: 'Строю сам', f: function (x) {
          return x.m.buildable ? '<input type="checkbox" data-build="' + x.m.type_id + '"' + (x.m.build ? ' checked' : '') + ' aria-label="Строить ' + esc(x.m.name) + ' самому">' +
            (x.m.kind === 'r' ? ' <span class="in-sub">реакция</span>' : '') : '';
        } }
      ], { rowAttrs: function (x) { return x.m.build ? ' class="in-built"' : ''; } });

    // работы
    h += '<h3 class="small muted" style="margin:16px 0 6px">Работы</h3>' + table('inJobs', r.jobs, [
      { k: 'name', t: 'Что', l: 1, f: function (j) { return '<span style="padding-left:' + (j.depth * 22) + 'px">' + ico(j.type_id) + esc(j.name) + '</span>' + (j.kind === 'r' ? ' <span class="in-sub">реакция</span>' : ''); } },
      { k: 'runs', t: 'Прогонов', f: function (j) { return esc(L.fmtInt(j.runs)); } },
      { k: 'out', t: 'Выйдет', f: function (j) { return esc(L.fmtInt(j.out)); } },
      { k: 'time', t: 'Время', f: function (j) { return esc(dur(j.time)); } },
      { k: 'eiv', t: 'EIV', title: 'Ориентировочная стоимость — от неё считается цена работы', f: function (j) { return esc(isk(j.eiv)); } },
      { k: 'cost', t: 'Стоимость работы', f: function (j) { return esc(isk(j.cost)); } }
    ], {});

    // закупка
    h += '<h3 class="small muted" style="margin:16px 0 6px">Что купить</h3>' + table('inBuyList', r.shopping, [
      { k: 'name', t: 'Предмет', l: 1, f: function (x) { return ico(x.type_id) + esc(x.name); } },
      { k: 'qty', t: 'Количество', f: function (x) { return esc(L.fmtInt(x.qty)); } },
      { k: 'price', t: 'Цена', f: function (x) { return esc(isk(x.price)); } },
      { k: 'total', t: 'Сумма', f: function (x) { return esc(isk(x.total)); } },
      { k: 'volume', t: 'Объём, м³', f: function (x) { return esc(L.fmtInt(x.volume)); } }
    ], { sort: { k: 'total', d: -1 } }) +
      '<div class="controls" style="margin-top:8px"><button type="button" class="btn" id="inCopy">Скопировать список покупок</button>' +
      '<span class="small muted" id="inCopyMsg" role="status"></span></div>';
    box.innerHTML = h + '</section>';
  }

  $('inResult').addEventListener('change', function (e) {
    var cb = e.target.closest && e.target.closest('input[data-build]');
    if (!cb) return;
    var id = +cb.getAttribute('data-build');
    I.build = I.build.filter(function (x) { return x !== id; });
    if (cb.checked) I.build.push(id);
    calc();
  });
  $('inResult').addEventListener('click', function (e) {
    if (e.target.id !== 'inCopy' || !I.res) return;
    var text = I.res.shopping.map(function (x) { return x.name + ' ' + x.qty; }).join('\n'), msg = $('inCopyMsg');
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { msg.textContent = 'Скопировано — вставляется в «Купить несколько» на рынке игры.'; }, function () { msg.textContent = 'Не удалось.'; });
  });
})(window.ELW);
