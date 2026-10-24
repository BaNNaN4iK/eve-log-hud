// Вкладка модуля «Производство». Подключается ядром (window.ELW), см. modules/README.md.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, $ = ELW.$, BASE = ELW.base;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };

  function opt(v, t) { return '<option value="' + v + '">' + t + '</option>'; }
  // подсказки: значок «?» у названия поля, текст всплывает при наведении или фокусе (Tab)
  var HELP = {
    product: 'Что производите. Начните вводить название (по-английски, как в игре) и выберите из списка. Реакции (лунные материалы, полимеры) тоже есть.',
    runs: 'Сколько раз запустить чертёж. Обычно один прогон даёт одну штуку; у зарядов, дронов и реакций за прогон выходит сразу пачка.',
    me: 'ME — Material Efficiency, экономия материалов. От 0 до 10: каждый уровень −1% материалов. Оригиналы чертежей обычно исследуют до ME 10; копии T2 после изобретения — ME 2. Смотрите в игре: «Показать информацию» у чертежа.',
    te: 'TE — Time Efficiency, экономия времени. От 0 до 20: каждый уровень −1% времени производства. Исследованный оригинал — TE 20; копии T2 после изобретения — TE 4.',
    struct: 'Где запускаете работу. Инженерные комплексы (Raitaru, Azbel, Sotiyo) дают −1% материалов, −15/20/30% времени и −3/4/5% к стоимости работы. Athanor и Tatara — для реакций (Tatara −25% времени реакций). На станции NPC бонусов нет.',
    rig: 'Риг на структуре для этого вида производства: T1 −2% материалов и −20% времени, T2 −2,4% и −24%. В лоу-секе бонус ×1,9, в нулях и ВХ ×2,1. На станции NPC ригов нет.',
    sec: 'Безопасность системы со структурой — от неё зависит сила ригов. Реакции в хай-секе запрещены.',
    system: 'Система, где строите. По ней берётся индекс стоимости работ из игры: чем больше в системе производят, тем дороже запуск.',
    index: 'Индекс стоимости работ в процентах. Оставьте пустым — возьмётся из игры по системе. Впишите своё число, если хотите посчитать «а что если».',
    tax: 'Налог владельца сооружения в процентах от ориентировочной стоимости. Станция NPC — 0,25%; в структуре — сколько поставил владелец (часто 0–1%).',
    scc: 'Надбавка SCC — обязательный сбор игры к стоимости любой работы, в процентах.',
    ind: 'Навык Industry: −4% времени производства за уровень.',
    adv: 'Навык Advanced Industry: ещё −3% времени производства за уровень.',
    react: 'Навык Reactions: −4% времени реакций за уровень.',
    cme: 'ME чертежей компонентов, которые вы отметили «Строю сам» (например, Vexor для Ishtar или Hobgoblin I для Hobgoblin II).',
    cte: 'TE чертежей компонентов, которые строите сами.',
    market: 'Хаб, по ценам которого считаются материалы и продукт.',
    buy: '«Сразу» — покупаете у ордеров на продажу, дороже, но мгновенно. «Своим ордером» — выставляете ордер на покупку, дешевле, но ждать. «По середине» — среднее между ними.',
    sell: '«Своим ордером» — выставляете продукт на продажу (дороже, плюс комиссия брокера). «Сразу» — продаёте в ордера покупки (дешевле, но мгновенно).',
    salestax: 'Налог с продаж: берётся с каждой продажи. Зависит от навыка Accounting (при Accounting 5 около 3,6%).',
    broker: 'Комиссия брокера за выставление ордера — только если продаёте своим ордером. Зависит от навыков и репутации (обычно 1–3%).',
    pl_mode: '«Полный цикл» — всё, что строится по чертежу, строите сами: компоненты, реакции из лунных материалов, изобретаете копии T2. «Покупаю компоненты» — строите только сами продукты, всё остальное покупаете.',
    pl_inv: 'Копии чертежей T2 получают изобретением из копии T1 и датакоров, с шансом. Попыток берётся с запасом: прогоны ÷ (шанс × прогонов в одной копии). Шанс растёт с навыками наук и шифрования (на экране «Калькулятор»).',
    pl_left: 'Прогон даёт целую пачку, поэтому часто выходит больше, чем нужно. Лишнее остаётся у вас; его стоимость (по цене мгновенной продажи) вычитается из себестоимости.',
    sci: 'Уровень двух научных навыков для изобретения (например, Mechanical Engineering и Electronic Engineering). Шанс растёт на 1/30 за уровень каждого.',
    enc: 'Навык шифрования расы (Amarr / Caldari / Gallente / Minmatar Encryption Methods): шанс изобретения +1/40 за уровень.',
    sc_sure: 'Только то, что выгодно и при продаже своим ордером, и при мгновенной продаже в ордера покупки, без подозрительных цен.',
    t_cost: 'Сколько стоит всё производство: материалы, которые покупаете, плюс стоимость всех работ (включая компоненты, которые строите сами).',
    t_mat: 'Материалы, которые покупаете, по выбранной цене. Ниже — сколько стоят сами запуски работ.',
    t_rev: 'Сколько выручите за продукт по выбранной цене, и сколько уйдёт на налог с продаж и брокера.',
    t_profit: 'Выручка минус налоги, минус себестоимость. Маржа — прибыль в процентах от выручки.',
    t_iskh: 'Прибыль, делённая на время всех работ. Если линий производства несколько и работы идут параллельно — в час выйдет больше.',
    t_time: 'Время главной работы. Если строите компоненты сами — ниже время всех работ подряд.',
    t_vol: 'Объём всего, что нужно купить, — чтобы понять, сколько везти.',
    c_eiv: 'Ориентировочная стоимость (EIV) — оценка игры по средним ценам материалов. От неё считается стоимость запуска работы.',
    c_cost: 'Стоимость запуска: EIV × (индекс системы + налог сооружения + сбор SCC); комплексы дают скидку.'
  };
  function help(key) {
    return HELP[key] ? ' <span class="in-help" tabindex="0" role="button" aria-label="Подсказка">?<span class="in-tip" role="tooltip">' + esc(HELP[key]) + '</span></span>' : '';
  }
  function lab(text, key) { return '<span class="in-lab">' + text + help(key) + '</span>'; }
  function lv(id, label, hi, key) {
    var h = '<label class="small muted">' + lab(label, key) + '<select id="' + id + '">';
    for (var i = 0; i <= hi; i++) h += opt(i, i);
    return h + '</select></label>';
  }
  function inp(id, label, ph, key) { return '<label class="small muted">' + lab(label, key) + '<input id="' + id + '" inputmode="decimal" placeholder="' + (ph || '') + '"></label>'; }
  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }
  function ico(t) { return t ? '<img class="in-ico" src="' + BASE + '/icons/' + t + '.png" alt="" loading="lazy">' : ''; }
  function dur(s) { return s ? L.fmtDur(Math.round(s)) : '—'; }

  ELW.addTab({ id: 'industry', title: 'Производство',
    css: '.in-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px 14px;margin-top:8px}\n' +
      '.in-grid input,.in-grid select,#inProduct{width:100%;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px}\n' +
      '.in-ico{width:20px;height:20px;vertical-align:middle;margin-right:5px;border-radius:3px}.in-sub{font-size:11.5px;color:var(--muted)}\n' +
      '.in-good{color:var(--good)}.in-bad{color:var(--bad)} details.in-set{margin-top:10px}details.in-set>summary{cursor:pointer;color:var(--muted);font-size:13px}\n' +
      'tr.in-built>td:first-child{box-shadow:inset 4px 0 0 var(--accent)} .in-ind{display:inline-block}\n' +
      '.in-lab{display:flex;align-items:center;gap:4px}.in-help{position:relative;display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;border-radius:50%;' +
      'background:var(--panel2);border:1px solid var(--line);color:var(--muted);font-size:10.5px;font-weight:700;cursor:help;flex:none}\n' +
      '.in-help:hover,.in-help:focus{color:var(--text);border-color:var(--accent);outline:none}\n' +
      '.in-tip{display:none;position:absolute;z-index:20;top:calc(100% + 6px);left:-8px;width:280px;padding:8px 10px;border-radius:8px;background:var(--panel);' +
      'border:1px solid var(--line);box-shadow:0 6px 24px rgba(0,0,0,.35);color:var(--text);font-size:12.5px;font-weight:400;line-height:1.4;white-space:normal;text-align:left}\n' +
      '.in-help:hover .in-tip,.in-help:focus .in-tip{display:block}\n' +
      '.in-views{display:flex;gap:6px;margin-bottom:12px}.in-chip{background:var(--panel2);border:1px solid var(--line);color:var(--muted);border-radius:7px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px}\n' +
      '.in-chip:hover{color:var(--text)}.in-chip.on{color:var(--text);border-color:var(--accent);background:color-mix(in srgb,var(--accent) 18%,var(--panel2))}.in-chip .n{opacity:.65;margin-left:4px;font-size:11.5px}\n' +
      '.in-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.in-back{font-size:13px;cursor:pointer;color:var(--muted);background:none;border:0;padding:0;margin-bottom:8px}.in-back:hover{color:var(--text)}\n' +
      '.in-cmp{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}@media(max-width:760px){.in-cmp{grid-template-columns:1fr}}\n' +
      '.in-cmp>div{background:var(--panel2);border-radius:10px;padding:10px 14px;border-top:3px solid var(--c)}.in-cmp h3{margin:0 0 6px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}\n' +
      '.in-cmp dl{display:grid;grid-template-columns:1fr auto;gap:3px 12px;margin:0;font-variant-numeric:tabular-nums}.in-cmp dt{color:var(--muted)}.in-cmp dd{margin:0;text-align:right}\n' +
      '.in-cmp .tot{border-top:1px solid var(--line);padding-top:4px;margin-top:2px;font-weight:650}\n' +
      '.sc-card{display:grid;grid-template-columns:44px 1fr auto 18px;gap:4px 12px;align-items:center;background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:8px;cursor:pointer}\n' +
      '.sc-card:hover,.sc-card:focus{border-color:var(--accent);outline:none}.sc-ico{width:40px;height:40px;border-radius:6px;background:var(--panel)}.sc-ico img{width:40px;height:40px;border-radius:6px;margin:0}.sc-name{font-weight:650;font-size:14.5px}\n' +
      '.sc-meta{font-size:12px;color:var(--muted);margin-top:2px}.sc-meta b{color:var(--text);font-weight:600}.sc-right{text-align:right;font-variant-numeric:tabular-nums}\n' +
      '.sc-big{font-size:18px;font-weight:700;color:var(--good)}.sc-big.neg{color:var(--bad)}.sc-sub{font-size:12px;color:var(--muted)}.sc-arrow{color:var(--muted);font-size:18px}\n' +
      '.sc-badge{display:inline-block;font-size:10.5px;border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:2px;border:1px solid var(--line);color:var(--muted)}\n' +
      '.sc-badge.sure{color:var(--good);border-color:var(--good)}.sc-badge.t2{color:var(--accent);border-color:var(--accent)}.sc-badge.lp{color:var(--warn);border-color:var(--warn)}\n' +
      '.sc-bar{height:6px;background:var(--panel2);border-radius:3px;overflow:hidden;margin-top:6px}.sc-bar>div{height:100%;background:var(--accent);transition:width .4s}\n' +
      '.sc-pages{display:flex;gap:6px;justify-content:center;margin-top:12px;flex-wrap:wrap}\n' +
      'details.in-sec{margin-top:14px;border-top:1px solid var(--line);padding-top:8px}details.in-sec>summary{cursor:pointer;list-style:none;font-size:13px;color:var(--muted);font-weight:600;padding:2px 0 6px}\n' +
      'details.in-sec>summary::-webkit-details-marker{display:none}details.in-sec>summary::before{content:"\\25B8";display:inline-block;width:1.1em;transition:transform .15s}\n' +
      'details.in-sec[open]>summary::before{transform:rotate(90deg)}details.in-sec>summary:hover{color:var(--text)}details.in-sec>summary .n{font-weight:400}\n' +
      'tr.in-rgood>td:first-child{box-shadow:inset 4px 0 0 var(--good)}tr.in-rbad>td:first-child{box-shadow:inset 4px 0 0 var(--bad)}\n' +
      '.tile.in-t{position:relative;cursor:help}.tile.in-t .k{text-decoration:underline dotted;text-underline-offset:3px}.tile.in-t:hover .in-tip,.tile.in-t:focus .in-tip{display:block}',
    html: '<div class="in-views" role="tablist" aria-label="Экран производства"><button type="button" class="in-chip" id="inViewScan" role="tab">Сканер прибыльности</button>' +
      '<button type="button" class="in-chip" id="inViewCalc" role="tab">Калькулятор</button><button type="button" class="in-chip" id="inViewPlan" role="tab">План производства</button></div>' +
      '<div id="inScanView"></div><div id="inPlanView"></div><div id="inCalcView">' +
      '<section class="panel"><h2>Калькулятор производства <span class="muted small">материалы, стоимость работы, время и прибыль</span></h2>' +
      '<div class="in-grid" style="grid-template-columns:minmax(260px,2fr) repeat(3,minmax(110px,1fr))">' +
      '<label class="small muted">' + lab('Что строим', 'product') + '<input id="inProduct" list="inList" autocomplete="off" spellcheck="false" placeholder="например: Vexor, Hobgoblin II, Ishtar"><datalist id="inList"></datalist></label>' +
      inp('inRuns', 'Прогонов', '1', 'runs') + lv('inMe', 'ME чертежа', 10, 'me') + lv('inTe', 'TE чертежа', 20, 'te') +
      '</div>' +
      '<details class="in-set" open><summary>Где строим и навыки</summary><div class="in-grid">' +
      '<label class="small muted">' + lab('Сооружение', 'struct') + '<select id="inStruct">' + opt('station', 'станция NPC') + opt('raitaru', 'Raitaru') + opt('azbel', 'Azbel') + opt('sotiyo', 'Sotiyo') +
        opt('athanor', 'Athanor (реакции)') + opt('tatara', 'Tatara (реакции)') + opt('other', 'другая структура') + '</select></label>' +
      '<label class="small muted">' + lab('Риг', 'rig') + '<select id="inRig">' + opt('none', 'нет') + opt('t1', 'T1') + opt('t2', 'T2') + '</select></label>' +
      '<label class="small muted">' + lab('Безопасность', 'sec') + '<select id="inSec">' + opt('high', 'хай-сек') + opt('low', 'лоу-сек') + opt('null', 'нули / ВХ') + '</select></label>' +
      '<label class="small muted">' + lab('Система (для индекса)', 'system') + '<input id="inSystem" spellcheck="false" placeholder="например: Jita"></label>' +
      inp('inIndex', 'Свой индекс, %', 'авто', 'index') +
      inp('inTax', 'Налог сооружения, %', '0,25', 'tax') +
      inp('inScc', 'Сбор SCC, %', '4', 'scc') +
      lv('inInd', 'Industry', 5, 'ind') + lv('inAdv', 'Advanced Industry', 5, 'adv') +
      lv('inReact', 'Reactions', 5, 'react') +
      lv('inCme', 'ME компонентов', 10, 'cme') + lv('inCte', 'TE компонентов', 20, 'cte') +
      lv('inSci', 'Науки (изобретение)', 5, 'sci') + lv('inEnc', 'Шифрование', 5, 'enc') +
      '</div></details>' +
      '<details class="in-set"><summary>Цены и налоги</summary><div class="in-grid">' +
      '<label class="small muted">' + lab('Рынок', 'market') + '<select id="inMarket">' + opt('jita', 'Jita 4-4') + opt('amarr', 'Amarr') + opt('dodixie', 'Dodixie') + opt('rens', 'Rens') + opt('hek', 'Hek') + '</select></label>' +
      '<label class="small muted">' + lab('Материалы покупаю', 'buy') + '<select id="inBuy">' + opt('sell', 'сразу (по ордерам продажи)') + opt('buy', 'своим ордером (по покупке)') + opt('split', 'по середине') + '</select></label>' +
      '<label class="small muted">' + lab('Продукт продаю', 'sell') + '<select id="inSell">' + opt('sell', 'своим ордером (по продаже)') + opt('buy', 'сразу (в ордера покупки)') + opt('split', 'по середине') + '</select></label>' +
      inp('inSalesTax', 'Налог с продаж, %', '3,6', 'salestax') + inp('inBroker', 'Брокер, %', '1,5', 'broker') +
      '</div></details>' +
      '<div class="controls" style="margin-top:10px"><button type="button" class="btn primary" id="inGo">Посчитать</button>' +
      '<span class="small" id="inMsg" role="status" aria-live="polite"></span></div></section><div id="inResult"></div></div>',
    render: function () {
      init();
      showView();
      if (I.view === 'scan') { if (window.ELW_INDUSTRY && ELW_INDUSTRY.scanner) ELW_INDUSTRY.scanner.render(); return; }
      if (I.view === 'plan') { if (window.ELW_INDUSTRY && ELW_INDUSTRY.plan) ELW_INDUSTRY.plan.render(); return; }
      var key = JSON.stringify((ELW.S && ELW.S.sort) || {});             // ядро зовёт render() каждые 4 с и при сортировке
      if (I.sortKey !== key) { I.sortKey = key; draw(); }
    } });

  var F = [['inRuns', 'runs'], ['inMe', 'me'], ['inTe', 'te'], ['inStruct', 'structure'], ['inRig', 'rig'], ['inSec', 'security'], ['inSystem', 'system'],
    ['inIndex', 'cost_index'], ['inTax', 'facility_tax'], ['inScc', 'scc'], ['inInd', 'industry'], ['inAdv', 'adv_industry'], ['inReact', 'reactions'],
    ['inCme', 'comp_me'], ['inCte', 'comp_te'], ['inMarket', 'market'], ['inBuy', 'buy_mode'], ['inSell', 'sell_mode'], ['inSalesTax', 'sales_tax'], ['inBroker', 'broker'], ['inSci', 'inv_sci'], ['inEnc', 'inv_enc']];
  var I = { inited: false, res: null, build: [], t: null, view: 'scan', week: null };
  try { var v0 = localStorage.getItem('elw.industry.view'); I.view = v0 === 'calc' || v0 === 'plan' ? v0 : 'scan'; } catch (e) { }
  function showView() {
    [['scan', 'inScanView', 'inViewScan'], ['calc', 'inCalcView', 'inViewCalc'], ['plan', 'inPlanView', 'inViewPlan']].forEach(function (v) {
      $(v[1]).hidden = I.view !== v[0];
      $(v[2]).classList.toggle('on', I.view === v[0]);
      $(v[2]).setAttribute('aria-selected', I.view === v[0]);
    });
  }
  function setView(v) {
    I.view = v;
    try { localStorage.setItem('elw.industry.view', v); } catch (e) { }
    showView();
    if (v === 'scan' && window.ELW_INDUSTRY && ELW_INDUSTRY.scanner) ELW_INDUSTRY.scanner.render(true);
    if (v === 'plan' && window.ELW_INDUSTRY && ELW_INDUSTRY.plan) ELW_INDUSTRY.plan.render();
    window.scrollTo(0, 0);
  }
  // для сканера (scan.js): открыть предмет в калькуляторе, общие настройки и подсказки
  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.open = function (name, src, me, te) {
    $('inProduct').value = name; $('inRuns').value = '1'; I.build = [];
    if (src === 'inv') { $('inMe').value = '2'; $('inTe').value = '4'; }           // копия после изобретения
    else if (me !== undefined && me !== null) { $('inMe').value = String(me); $('inTe').value = String(te); }   // как в сканере
    setView('calc'); calc();
  };
  ELW_INDUSTRY.settings = function () { return settings(); };
  ELW_INDUSTRY.help = function (key) { return help(key); };
  ELW_INDUSTRY.ico = function (t) { return ico(t); };

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

  // подсказка у правого края окна — открывать влево, чтобы не уходила за экран
  function placeTip(e) {
    var host = e.target.closest && e.target.closest('.in-help, .tile.in-t');
    var tip = host && host.querySelector('.in-tip');
    if (!tip) return;
    tip.style.left = ''; tip.style.right = '';
    var r = tip.getBoundingClientRect();
    if (r.right > window.innerWidth - 8) { tip.style.left = 'auto'; tip.style.right = '-8px'; }
  }
  document.addEventListener('mouseover', placeTip);
  document.addEventListener('focusin', placeTip);

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
  $('inViewScan').addEventListener('click', function () { setView('scan'); });
  $('inViewCalc').addEventListener('click', function () { setView('calc'); });
  $('inViewPlan').addEventListener('click', function () { setView('plan'); });

  function calc() {
    var msg = $('inMsg'), btn = $('inGo');
    if (!$('inProduct').value.trim()) { msg.textContent = 'Укажите, что строить.'; return; }
    btn.disabled = true; msg.textContent = 'Считаю…';
    api('/api/industry', { method: 'POST', headers: POST, body: JSON.stringify({ product: $('inProduct').value, settings: settings() }) }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { msg.innerHTML = '<span class="in-bad">' + esc(j.message || 'Не получилось.') + '</span>'; return; }
      msg.textContent = j.note || '';
      I.res = j; I.build = j.settings.build || []; I.week = null;
      draw();
      api('/api/industry/history?market=' + encodeURIComponent(j.settings.market) + '&ids=' + j.product.type_id).then(function (h) {
        var w = h.history && h.history[String(j.product.type_id)];
        if (w && I.res === j) { I.week = w; draw(); }
      }, function () { });
      setTimeout(function () { if (I.res === j) draw(); }, 4000);           // иконки догружаются
    }, function () { btn.disabled = false; msg.textContent = 'Нет связи с трекером.'; });
  }

  // строки материалов: дерево с вложенными компонентами, которые строим сами
  function matRows(node, depth, out) {
    node.materials.forEach(function (m) {
      out.push({ m: m, depth: depth, runs: node.runs });
      if (m.build) matRows(m.build, depth + 1, out);
    });
    return out;
  }

  function draw() {
    var r = I.res, box = $('inResult');
    if (!r) { box.innerHTML = ''; return; }
    var t = r.totals, p = r.product, up = r.unit_prices || {};
    var tile = function (k, v, s, cls, key) {
      return '<div class="tile' + (key ? ' in-t" tabindex="0' : '') + '"><div class="k">' + k + '</div><div class="v' + (cls ? ' ' + cls : '') + '">' + v + '</div><div class="s">' + (s || '') + '</div>' +
        (key ? '<span class="in-tip" role="tooltip">' + esc(HELP[key]) + '</span>' : '') + '</div>';
    };
    var cmp = r.compare || {}, cs = cmp.sell || {}, cb = cmp.buy || {}, best = cs.isk_hour !== null && cs.isk_hour !== undefined ? cs : cb;
    var week = I.week;
    var h = '<section class="panel"><button type="button" class="in-back" id="inBack">← к сканеру</button><h2>' + ico(p.type_id) + esc(p.name) + ' <span class="muted small">' + (p.kind === 'r' ? 'реакция' : 'производство') + ' · ' + L.fmtInt(p.units) + ' шт. · ' +
      esc(r.market_name) + (r.cost_index !== null && r.cost_index !== undefined ? ' · индекс ' + String(Math.round(r.cost_index * 100) / 100).replace('.', ',') + '%' + (r.system ? ' (' + esc(r.system) + ')' : '') : '') + '</span></h2>';
    if (r.warning) h += '<p class="small in-bad">' + esc(r.warning) + '</p>';
    if (r.cost_index === null || r.cost_index === undefined) h += '<p class="small muted">Стоимость работы не посчитана: укажите систему (индекс возьмётся из игры) или впишите свой индекс.</p>';
    if (r.missing_price && r.missing_price.length) h += '<p class="small" style="color:var(--warn)">Нет цены на рынке: ' + esc(r.missing_price.join(', ')) + '</p>';
    h += '<div class="tiles">' +
      tile('ISK в час', isk(cs.isk_hour), 'продажа своим ордером', cs.isk_hour > 0 ? 'in-good' : cs.isk_hour < 0 ? 'in-bad' : '', 't_iskh') +
      tile('Прибыль за прогон', isk(cs.per_run), r.tree.runs > 1 ? 'за все прогоны ' + isk(cs.profit) : '', cs.per_run > 0 ? 'in-good' : cs.per_run < 0 ? 'in-bad' : '', 't_profit') +
      tile('Маржа', cs.margin === null || cs.margin === undefined ? '—' : String(cs.margin).replace('.', ',') + '%', 'мгновенно ' + (cb.margin === null || cb.margin === undefined ? '—' : String(cb.margin).replace('.', ',') + '%')) +
      tile('Спрос за неделю', week ? L.fmtInt(week.week) : '…', week ? (week.week ? '≈ ' + L.fmtInt(Math.round(week.week / 7)) + ' в день' : 'продаж не было') : 'загружаю', week && week.week < 7 ? 'in-bad' : '') + '</div>';
    var col = function (title, c, color, mode) {
      var row = function (k, v, cls) { return '<dt' + (cls ? ' class="' + cls + '"' : '') + '>' + k + '</dt><dd' + (cls ? ' class="' + cls + '"' : '') + '>' + v + '</dd>'; };
      return '<div style="--c:' + color + '"><h3>' + title + '</h3><dl>' +
        row('Цена продукта', isk(c.price)) + row('Выручка', isk(c.revenue)) + row('Налоги' + (mode === 'sell' ? ' и брокер' : ''), c.fees === null || c.fees === undefined ? '—' : '−' + isk(c.fees)) +
        row('Материалы', t.materials === null ? '—' : '−' + isk(t.materials)) + row('Работы', t.jobs === null ? '—' : '−' + isk(t.jobs)) +
        row('Прибыль', '<span class="' + (c.profit > 0 ? 'in-good' : c.profit < 0 ? 'in-bad' : '') + '">' + isk(c.profit) + '</span>', 'tot') +
        row('ISK в час', isk(c.isk_hour)) + row('Маржа', c.margin === null || c.margin === undefined ? '—' : String(c.margin).replace('.', ',') + '%') + '</dl></div>';
    };
    h += '<div class="in-cmp">' + col('Продажа своим ордером', cs, 'var(--good)', 'sell') + col('Мгновенная продажа', cb, 'var(--accent)', 'buy') + '</div>';
    h += '<div class="tiles" style="margin-top:12px">' +
      tile('Себестоимость', isk(t.cost), 'за штуку ' + isk(t.per_unit) + ' ISK', '', 't_cost') +
      tile('Материалы', isk(t.materials), 'работы ' + isk(t.jobs) + ' ISK', '', 't_mat') +
      tile('Время', dur(t.top_time), r.jobs.length > 1 ? 'всех работ подряд ' + dur(t.time) : '', '', 't_time') +
      tile('Закупка', L.fmtInt(t.volume) + ' м³', r.shopping.length + ' позиций', '', 't_vol') + '</div>';
    if (/ II$| III$/.test(p.name) || r.tree.materials.some(function (m) { return m.kind && /^(R\.A\.M|Construction Blocks)/.test(m.name); })) {
      h += '<p class="small muted">Чертежи T2 после изобретения обычно ME 2 / TE 4 — проверьте ME и TE.</p>';
    }

    // материалы (дерево)
    var rows = matRows(r.tree, 0, []);
    var canBuild = rows.some(function (x) { return x.m.buildable; });
    h += '<h3 class="small muted" style="margin:16px 0 6px">Материалы — ' + (canBuild ? 'отметьте, что строите сами, а не покупаете' :
      'всё покупается: построить по чертежу здесь ничего нельзя (минералы и другое сырьё добывают)') + '</h3>' +
      table('inMats', rows.map(function (x) {
        var m = x.m, price = up[String(m.type_id)];
        return { name: m.name, qty: m.qty, depth: x.depth, runs: x.runs, m: m, price: price, total: price !== null && price !== undefined ? price * m.qty : null };
      }), [
        { k: '', t: 'Материал', l: 1, f: function (x) {
          var m = x.m;
          return '<span class="in-ind" style="padding-left:' + (x.depth * 22) + 'px">' + ico(m.type_id) + esc(m.name) + '</span>' +
            (m.build ? '<div class="in-sub" style="padding-left:' + (x.depth * 22 + 25) + 'px">строю: ' + L.fmtInt(m.build.runs) + ' прог. → ' + L.fmtInt(m.build.out) + ' шт.' + (m.build.out > m.qty ? ', останется ' + L.fmtInt(m.build.out - m.qty) : '') + '</div>' : '');
        } },
        { k: '', t: 'По чертежу', title: 'Сколько нужно без ME и бонусов: количество в чертеже × прогоны', f: function (x) { return '<span class="muted">' + esc(L.fmtInt(x.m.base * x.runs)) + '</span>'; } },
        { k: '', t: 'Нужно', title: 'После ME, структуры и ригов', f: function (x) { return esc(L.fmtInt(x.qty)); } },
        { k: '', t: 'Цена', f: function (x) { return x.m.build ? '<span class="muted">строю</span>' : esc(isk(x.price)); } },
        { k: '', t: 'Купить за', f: function (x) { return x.m.build ? '<span class="muted">' + esc(isk(x.total)) + '</span>' : esc(isk(x.total)); } },
        { k: '', t: 'Строю сам', f: function (x) {
          return x.m.buildable ? '<input type="checkbox" data-build="' + x.m.type_id + '"' + (x.m.build ? ' checked' : '') + ' aria-label="Строить ' + esc(x.m.name) + ' самому">' +
            (x.m.kind === 'r' ? ' <span class="in-sub">реакция</span>' : '') :
            '<span class="in-sub" title="Для этого материала нет чертежа: его добывают, получают переработкой, на планетах или с NPC">не строится</span>';
        } }
      ], { rowAttrs: function (x) { return x.m.build ? ' class="in-built"' : ''; } });

    // работы
    h += '<h3 class="small muted" style="margin:16px 0 6px">Работы</h3>' + table('inJobs', r.jobs, [
      { k: 'name', t: 'Что', l: 1, f: function (j) { return '<span style="padding-left:' + (j.depth * 22) + 'px">' + ico(j.type_id) + esc(j.name) + '</span>' + (j.kind === 'r' ? ' <span class="in-sub">реакция</span>' : ''); } },
      { k: 'runs', t: 'Прогонов', f: function (j) { return esc(L.fmtInt(j.runs)); } },
      { k: 'out', t: 'Выйдет', f: function (j) { return esc(L.fmtInt(j.out)); } },
      { k: 'time', t: 'Время', f: function (j) { return esc(dur(j.time)); } },
      { k: 'eiv', t: 'EIV', title: HELP.c_eiv, f: function (j) { return esc(isk(j.eiv)); } },
      { k: 'cost', t: 'Стоимость работы', title: HELP.c_cost, f: function (j) { return esc(isk(j.cost)); } }
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
    if (e.target.id === 'inBack') { setView('scan'); return; }
    if (e.target.id !== 'inCopy' || !I.res) return;
    var text = I.res.shopping.map(function (x) { return x.name + ' ' + x.qty; }).join('\n'), msg = $('inCopyMsg');
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { msg.textContent = 'Скопировано — вставляется в «Купить несколько» на рынке игры.'; }, function () { msg.textContent = 'Не удалось.'; });
  });
})(window.ELW);
