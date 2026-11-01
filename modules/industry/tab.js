// Вкладка модуля «Производство»: сканер, план и ведение производства (расчёт предмета — там же). Подключается ядром (window.ELW).
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
    pl_inv: 'Копии чертежей T2 получают изобретением из копии T1 и датакоров, с шансом. Попыток берётся с запасом: прогоны ÷ (шанс × прогонов в одной копии). Шанс растёт с навыками наук и шифрования (в настройках расчёта).',
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
      '.tile.in-t{position:relative;cursor:help}.tile.in-t .k{text-decoration:underline dotted;text-underline-offset:3px}.tile.in-t:hover .in-tip,.tile.in-t:focus .in-tip{display:block}' +
      '\n.pj-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin-top:10px}' +
      '.pj-card{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer;display:flex;flex-direction:column;gap:6px}.pj-card:hover,.pj-card:focus{border-color:var(--accent);outline:none}' +
      '.pj-hd{display:grid;grid-template-columns:44px 1fr auto;gap:10px;align-items:center}.pj-row{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;color:var(--muted);align-items:center}.pj-row b{color:var(--text)}' +
      '.pj-st{font-size:11px;border-radius:6px;padding:2px 8px;border:1px solid var(--line);white-space:nowrap}.pj-collect{color:var(--warn);border-color:var(--warn)}.pj-building{color:var(--accent);border-color:var(--accent)}.pj-done{color:var(--good);border-color:var(--good)}' +
      '.pj-prog{height:8px;background:var(--panel);border-radius:4px;overflow:hidden}.pj-prog>div{height:100%;background:linear-gradient(90deg,var(--accent),var(--good));transition:width .4s}.pj-prog.sm{height:6px;margin-bottom:2px}' +
      '.pj-steps{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:8px 0;counter-reset:st}.pj-steps li{flex:1 1 140px;padding:7px 10px;border-radius:8px;background:var(--panel2);font-size:13px;color:var(--muted)}' +
      '.pj-steps li::before{counter-increment:st;content:counter(st) ". ";font-weight:700}.pj-steps li.done{color:var(--text);background:color-mix(in srgb,var(--good) 20%,var(--panel2))}.pj-steps li.done::before{content:"\\2713  "}' +
      '.pj-steps li.now{color:var(--text);font-weight:650;background:color-mix(in srgb,var(--accent) 22%,var(--panel2));box-shadow:inset 0 0 0 1px var(--accent)}.pj-actions{margin:6px 0 12px}' +
      '.pj-charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-top:4px}.pj-box{background:var(--panel2);border-radius:10px;padding:10px 12px}.pj-box h3{margin:0 0 8px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}' +
      '.pj-dn{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.pj-dn svg{flex:none}.pj-leg{display:flex;flex-direction:column;gap:3px;font-size:12px;min-width:0;flex:1}.pj-leg>div{display:flex;gap:6px;align-items:center;min-width:0}' +
      '.pj-leg i{width:10px;height:10px;border-radius:3px;flex:none}.pj-leg span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}.pj-leg b{font-variant-numeric:tabular-nums;font-weight:600}.pj-leg em{font-style:normal;color:var(--muted);width:46px;text-align:right}' +
      '.pj-leg-row{flex-direction:row;flex-wrap:wrap;gap:4px 14px;margin-top:4px}.pj-leg-row>div{flex:none}.pj-rev{font-size:20px;font-weight:700;margin-bottom:6px}' +
      '.pj-stack{display:flex;height:22px;border-radius:6px;overflow:hidden;margin-bottom:8px;background:var(--panel)}.pj-stack>div{height:100%}' +
      '.pj-chart{position:relative}.pj-tip{position:absolute;z-index:5;pointer-events:none;font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 9px;box-shadow:0 6px 20px rgba(0,0,0,.35);white-space:nowrap}' +
      '.pj-tip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}.pj-stats{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:12.5px;color:var(--muted);margin:2px 0 6px}.pj-stats b{color:var(--text)}' +
      '.pj-mats td,.pj-mats th{vertical-align:middle}.pj-have{width:110px;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:4px 6px;text-align:right;font:inherit;font-variant-numeric:tabular-nums}' +
      '.pj-have:focus{border-color:var(--accent);outline:none}.pj-paste{background:var(--panel2);border-radius:8px;padding:10px;margin-bottom:10px}.pj-paste textarea{width:100%;box-sizing:border-box;margin:6px 0;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:12.5px ui-monospace,Consolas,monospace}' +
      '.pj-bars{display:flex;align-items:flex-end;gap:3px;height:70px;margin:4px 0 10px}.pj-bars>div{flex:1;height:100%;display:flex;align-items:flex-end}.pj-bars span{display:block;width:100%;border-radius:3px 3px 0 0}' +
      '.pj-log{list-style:none;padding:0;margin:0;font-size:12.5px;max-height:240px;overflow:auto}.pj-log li{padding:2px 0}' +
      '.pj-draft{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;padding:10px 12px;margin:8px 0;border-radius:10px;background:color-mix(in srgb,var(--warn) 14%,var(--panel2));border:1px dashed var(--warn)}' +
      '.in-fam{display:inline-block;font-size:10.5px;line-height:1.5;border-radius:5px;padding:0 6px;white-space:nowrap;border:1px solid currentColor;color:var(--muted);max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:1px}' +
      '.in-fam.f-mineral{color:#9fb3c8}.in-fam.f-reaction{color:#b48cf0}.in-fam.f-moon{color:#3cc8b4}.in-fam.f-pi{color:#6fcf5f}.in-fam.f-ice{color:#7fd4ff}' +
      '.in-fam.f-gas{color:#f0a050}.in-fam.f-datacore{color:#e8c840}.in-fam.f-fuel{color:#e07a5f}.in-fam.f-component{color:var(--accent)}.in-fam.f-commodity{color:#c8a27a}' +
      '.in-cp{cursor:copy;border-bottom:1px dashed transparent;transition:color .15s}.in-cp:hover,.in-cp:focus{border-bottom-color:var(--muted);outline:none}.in-cp.in-copied{color:var(--good);border-bottom-color:var(--good)}' +
      '.in-cp.in-copied::after{content:" \\2713  скопировано";font-size:11px}' +
      '.pj-rawbar{background:var(--panel2);border-radius:10px;padding:10px 12px;margin:4px 0 10px;display:flex;flex-direction:column;gap:6px}' +
      '.pj-fam{display:grid;grid-template-columns:minmax(150px,210px) 1fr;gap:10px;align-items:center}.pj-fam-n .in-fam{font-size:11.5px}' +
      '.pj-prog.big.f-mineral>div{background:linear-gradient(90deg,#6c7a89,#aab7c4)}.pj-prog.big.f-reaction>div{background:linear-gradient(90deg,#6a4fb0,#b48cf0)}' +
      '.pj-prog.big.f-pi>div{background:linear-gradient(90deg,#3b8a32,#6fcf5f)}.pj-prog.big.f-moon>div{background:linear-gradient(90deg,#1f8a7c,#3cc8b4)}.pj-prog.big.f-gas>div{background:linear-gradient(90deg,#a8622a,#f0a050)}' +
      '.pj-prog.big.min>div{background:linear-gradient(90deg,#6c7a89,#aab7c4)}.pj-prog.big{height:22px;border-radius:7px;position:relative}.pj-prog.big>span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12.5px;font-weight:700;color:var(--text);text-shadow:0 1px 2px rgba(0,0,0,.6)}' +
      '.pj-hbars{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:6px 18px;margin:4px 0 10px}.pj-hb{display:grid;grid-template-columns:minmax(120px,1.2fr) 2fr auto;gap:8px;align-items:center;font-size:12.5px}' +
      '.pj-hb .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pj-hb .tr{height:10px;background:var(--panel);border-radius:5px;overflow:hidden}.pj-hb .tr>div{height:100%;border-radius:5px}.pj-hb .vl{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}',
    html: '<div class="in-views" role="tablist" aria-label="Экран производства"><button type="button" class="in-chip" id="inViewScan" role="tab">Сканер прибыльности</button>' +
      '<button type="button" class="in-chip" id="inViewPlan" role="tab">План производства</button>' +
      '<button type="button" class="in-chip" id="inViewProj" role="tab">📌 Ведение производства</button>' +
      '<button type="button" class="in-chip" id="inViewPi" role="tab">🪐 Планетарка</button></div>' +
      '<div id="inScanView"></div><div id="inPlanView"></div><div id="inProjView"></div><div id="inPiView"></div>',
    render: function () { if (I && I.ready) renderTab(); } });   // ядро может позвать сразу из addTab — модуль ещё не готов

  function renderTab() {
    init();
    showView();
    var X = window.ELW_INDUSTRY || {};
    if (I.view === 'scan') { if (X.scanner) X.scanner.render(); return; }
    if (I.view === 'plan') { if (X.plan) X.plan.render(); return; }
    if (I.view === 'pi') { if (X.pi) X.pi.render(); return; }
    if (X.projects) X.projects.render();
  }

  var I = { inited: false, view: 'scan', defaults: null, waiting: [] };
  try { var v0 = localStorage.getItem('elw.industry.view'); I.view = v0 === 'plan' || v0 === 'pi' ? v0 : v0 === 'proj' || v0 === 'calc' ? 'proj' : 'scan'; } catch (e) { }
  var VIEWS = [['scan', 'inScanView', 'inViewScan'], ['plan', 'inPlanView', 'inViewPlan'], ['proj', 'inProjView', 'inViewProj'], ['pi', 'inPiView', 'inViewPi']];
  function showView() {
    VIEWS.forEach(function (v) {
      $(v[1]).hidden = I.view !== v[0];
      $(v[2]).classList.toggle('on', I.view === v[0]);
      $(v[2]).setAttribute('aria-selected', I.view === v[0]);
    });
  }
  function setView(v) {
    I.view = v;
    try { localStorage.setItem('elw.industry.view', v); } catch (e) { }
    showView();
    var X = window.ELW_INDUSTRY || {};
    if (v === 'scan' && X.scanner) X.scanner.render(true);
    if (v === 'plan' && X.plan) X.plan.render();
    if (v === 'proj' && X.projects) X.projects.render(true);
    if (v === 'pi' && X.pi) X.pi.render();
    window.scrollTo(0, 0);
  }
  VIEWS.forEach(function (v) { $(v[2]).addEventListener('click', function () { setView(v[0]); }); });

  // сворачиваемые разделы: что свёрнуто — запоминается (общий помощник для сканера, плана и ведения)
  var FOLD = {};
  try { FOLD = JSON.parse(localStorage.getItem('elw.industry.folded') || '{}') || {}; } catch (e) { FOLD = {}; }
  function fold(key, title, body, open) {
    if (!body) return '';
    var closed = Object.prototype.hasOwnProperty.call(FOLD, key) ? FOLD[key] : open === false;
    return '<details class="in-sec" data-fold="' + esc(key) + '"' + (closed ? '' : ' open') + '><summary>' + title + '</summary>' + body + '</details>';
  }
  document.addEventListener('click', function (e) {
    var sm = e.target.closest && e.target.closest('details[data-fold] > summary');
    if (!sm || (e.target.closest('.in-help') && e.target.closest('.in-help') !== null)) return;
    FOLD[sm.parentNode.getAttribute('data-fold')] = sm.parentNode.open;          // открыт → после нажатия свернётся
    try { localStorage.setItem('elw.industry.folded', JSON.stringify(FOLD)); } catch (err) { }
  }, true);

  // ----- форма настроек расчёта: одна и та же для проекта и для «настроек по умолчанию» -----
  var F = [['Runs', 'runs'], ['Me', 'me'], ['Te', 'te'], ['Struct', 'structure'], ['Rig', 'rig'], ['Sec', 'security'], ['System', 'system'],
    ['Index', 'cost_index'], ['Tax', 'facility_tax'], ['Scc', 'scc'], ['Ind', 'industry'], ['Adv', 'adv_industry'], ['React', 'reactions'],
    ['Cme', 'comp_me'], ['Cte', 'comp_te'], ['Market', 'market'], ['Buy', 'buy_mode'], ['Sell', 'sell_mode'], ['SalesTax', 'sales_tax'],
    ['Broker', 'broker'], ['Sci', 'inv_sci'], ['Enc', 'inv_enc']];
  function form(px, o) {
    o = o || {};
    var top = (o.runs === false ? '' : inp(px + 'Runs', 'Прогонов', '1', 'runs')) + (o.me === false ? '' : lv(px + 'Me', 'ME чертежа', 10, 'me') + lv(px + 'Te', 'TE чертежа', 20, 'te'));
    return (top ? '<div class="in-grid">' + top + '</div>' : '') +
      '<details class="in-set" open><summary>Где строим и навыки</summary><div class="in-grid">' +
      '<label class="small muted">' + lab('Сооружение', 'struct') + '<select id="' + px + 'Struct">' + opt('station', 'станция NPC') + opt('raitaru', 'Raitaru') + opt('azbel', 'Azbel') + opt('sotiyo', 'Sotiyo') +
        opt('athanor', 'Athanor (реакции)') + opt('tatara', 'Tatara (реакции)') + opt('other', 'другая структура') + '</select></label>' +
      '<label class="small muted">' + lab('Риг', 'rig') + '<select id="' + px + 'Rig">' + opt('none', 'нет') + opt('t1', 'T1') + opt('t2', 'T2') + '</select></label>' +
      '<label class="small muted">' + lab('Безопасность', 'sec') + '<select id="' + px + 'Sec">' + opt('high', 'хай-сек') + opt('low', 'лоу-сек') + opt('null', 'нули / ВХ') + '</select></label>' +
      '<label class="small muted">' + lab('Система (для индекса)', 'system') + '<input id="' + px + 'System" spellcheck="false" placeholder="например: Jita"></label>' +
      inp(px + 'Index', 'Свой индекс, %', 'авто', 'index') + inp(px + 'Tax', 'Налог сооружения, %', '0,25', 'tax') + inp(px + 'Scc', 'Сбор SCC, %', '4', 'scc') +
      lv(px + 'Ind', 'Industry', 5, 'ind') + lv(px + 'Adv', 'Advanced Industry', 5, 'adv') + lv(px + 'React', 'Reactions', 5, 'react') +
      lv(px + 'Cme', 'ME компонентов', 10, 'cme') + lv(px + 'Cte', 'TE компонентов', 20, 'cte') +
      lv(px + 'Sci', 'Науки (изобретение)', 5, 'sci') + lv(px + 'Enc', 'Шифрование', 5, 'enc') + '</div></details>' +
      '<details class="in-set"><summary>Цены и налоги</summary><div class="in-grid">' +
      '<label class="small muted">' + lab('Рынок', 'market') + '<select id="' + px + 'Market">' + opt('jita', 'Jita 4-4') + opt('amarr', 'Amarr') + opt('dodixie', 'Dodixie') + opt('rens', 'Rens') + opt('hek', 'Hek') + '</select></label>' +
      '<label class="small muted">' + lab('Материалы покупаю', 'buy') + '<select id="' + px + 'Buy">' + opt('sell', 'сразу (по ордерам продажи)') + opt('buy', 'своим ордером (по покупке)') + opt('split', 'по середине') + '</select></label>' +
      '<label class="small muted">' + lab('Продукт продаю', 'sell') + '<select id="' + px + 'Sell">' + opt('sell', 'своим ордером (по продаже)') + opt('buy', 'сразу (в ордера покупки)') + opt('split', 'по середине') + '</select></label>' +
      inp(px + 'SalesTax', 'Налог с продаж, %', '3,6', 'salestax') + inp(px + 'Broker', 'Брокер, %', '1,5', 'broker') + '</div></details>';
  }
  function readForm(px) {
    var s = {};
    F.forEach(function (f) { var el = $(px + f[0]); if (el) s[f[1]] = el.value; });
    return s;
  }
  function fillForm(px, s) {
    F.forEach(function (f) { var el = $(px + f[0]), v = (s || {})[f[1]]; if (el) el.value = v === null || v === undefined ? '' : String(v).replace('.', ','); });
  }

  // ----- общий помощник для сканера, плана и ведения -----
  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  var X = window.ELW_INDUSTRY;
  X.fold = fold;
  X.show = setView;
  X.help = function (key) { return help(key); };
  X.ico = function (t) { return ico(t); };
  X.form = form; X.readForm = readForm; X.fillForm = fillForm;
  // вид материала: минерал, реакция, планетарка, лёд, газ, компонент… — цветная метка и общее название для фильтра
  var FAMS = { mineral: 'минералы', reaction: 'реакции', moon: 'лунные материалы', pi: 'планетарка', ice: 'лёд', gas: 'газы', datacore: 'датакоры',
    fuel: 'топливо', component: 'компоненты', commodity: 'товары', ship: 'корабли', module: 'модули', charge: 'заряды', drone: 'дроны', ore: 'руда', material: 'материалы', other: 'прочее' };
  X.famName = function (f, label) { return FAMS[f] || label || f; };
  X.fam = function (f, label) { return f ? '<span class="in-fam f-' + esc(f) + '" title="' + esc(label || '') + '">' + esc(label || X.famName(f)) + '</span>' : ''; };
  // настройки по умолчанию (для новых расчётов, сканера и плана): что сохранено на сервере
  X.settings = function () { var s = {}; Object.keys(I.defaults || {}).forEach(function (k) { s[k] = I.defaults[k]; }); return s; };
  X.defaults = function (fn) { if (I.defaults) fn(X.settings()); else I.waiting.push(fn); };
  X.saveDefaults = function (s) {
    return api('/api/industry/settings', { method: 'POST', headers: POST, body: JSON.stringify({ settings: s }) }).then(function (j) {
      if (j.ok) I.defaults = j.settings;
      return j;
    });
  };
  X.online = function () { return I.online !== false; };
  // открыть предмет: расчёт-черновик в «Ведении производства» (раньше — «Калькулятор»)
  X.open = function (name, src, me, te) {
    var over = {};
    if (src === 'inv') { over.me = 2; over.te = 4; }                       // копия после изобретения
    else if (me !== undefined && me !== null) { over.me = me; over.te = te; }
    setView('proj');
    if (X.projects) X.projects.draft(name, over);
  };
  // склад из игры (ESI, «Персонажи EVE»): места с вещами, выбор места, вещи на месте
  var STOCK = { at: 0, d: null, wait: [] };
  X.stockLocs = function (force) {
    if (!force && STOCK.d && Date.now() - STOCK.at < 30000) return Promise.resolve(STOCK.d);
    return api('/api/industry/stock/locations').then(function (j) { STOCK.d = j; STOCK.at = Date.now(); return j; });
  };
  X.stockItems = function (loc) {
    return api('/api/industry/stock?loc=' + encodeURIComponent(loc)).then(function (j) {
      var out = {}; Object.keys((j && j.items) || {}).forEach(function (k) { out[+k] = j.items[k]; }); return out;
    });
  };
  X.stockRefresh = function () { return api('/api/industry/stock/refresh', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' }, body: '{}' }); };
  // <select> складов; d — ответ stockLocs; пустой выбор — «не учитывать склад»
  X.stockSelect = function (id, d, sel, none) {
    var locs = (d && d.locations) || [];
    var h = '<select id="' + id + '" aria-label="Склад из игры"><option value="">' + esc(none || 'склад не учитывать') + '</option>';
    locs.forEach(function (l) { h += '<option value="' + l.id + '"' + (String(l.id) === String(sel) ? ' selected' : '') + '>' + esc(l.name) + ' — ' + L.fmtInt(l.types) + ' поз.</option>'; });
    if (sel && !locs.some(function (l) { return String(l.id) === String(sel); })) h += '<option value="' + esc(sel) + '" selected>место ' + esc(sel) + ' (пусто)</option>';
    return h + '</select>';
  };
  X.stockNote = function (d) {
    if (!d || d.ok === false) return '<span class="in-sub">' + esc((d && d.message) || 'Склад недоступен') + '</span>';
    if (!d.chars.length) return '<span class="in-sub">Подключите персонажа: «Настройки» → «Персонажи EVE» (доступ «склад»).</span>';
    var bad = d.chars.filter(function (c) { return c.error; });
    var at = Math.max.apply(null, d.chars.map(function (c) { return c.at || 0; }));
    return '<span class="in-sub">' + (d.busy ? 'обновляю склад из игры…' : at ? 'склад обновлён ' + esc(L.fmtDateTime(at)) : 'склад ещё не загружен') +
      (bad.length ? ' · ' + bad.map(function (c) { return esc(c.name + ': ' + c.error); }).join('; ') : '') + '</span>';
  };
  // добавить продукт в «План производства» и открыть его (из справочника)
  X.toPlan = function (id, qty) {
    if (X.plan && X.plan.add) X.plan.add(id, qty);
    setView('plan');
  };
  // название предмета: нажатие копирует его (для поиска в игре)
  X.cp = function (name) {
    return '<span class="in-cp" data-copy-name="' + esc(name) + '" tabindex="0" role="button" title="Нажмите — скопировать название">' + esc(name) + '</span>';
  };
  // копирование: через скрытое поле, а если не вышло — буфер обмена браузера (он может ждать разрешения)
  function copyText(text) {
    function legacy() {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      return ok ? Promise.resolve() : Promise.reject(new Error('copy'));
    }
    return legacy().then(null, function () {
      return navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(text) : Promise.reject(new Error('copy'));
    });
  }
  X.copyText = copyText;
  function copyName(el) {
    var name = el.getAttribute('data-copy-name');
    var done = function (ok) { el.classList.add(ok ? 'in-copied' : 'in-bad'); el.setAttribute('title', ok ? 'Скопировано: ' + name : 'Не удалось скопировать');
      setTimeout(function () { el.classList.remove('in-copied', 'in-bad'); el.setAttribute('title', 'Нажмите — скопировать название'); }, 1200); };
    copyText(name).then(function () { done(true); }, function () { done(false); });
  }
  document.addEventListener('click', function (e) { var el = e.target.closest && e.target.closest('[data-copy-name]'); if (el) { e.stopPropagation(); copyName(el); } }, true);
  document.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-copy-name]')) { e.preventDefault(); copyName(e.target); } });

  function init() {
    if (I.inited) return;
    I.inited = true;
    api('/api/industry/settings').then(function (j) {
      if (!j.ok) return;
      I.defaults = j.settings; I.online = !!j.prices;
      var w = I.waiting; I.waiting = [];
      w.forEach(function (fn) { fn(X.settings()); });
    }, function () { });
  }
  // подсказка у края окна не уезжает за экран
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

  // всё готово; сканер, план и ведение подключаются следующими файлами — отрисовать, когда они загрузятся
  I.ready = true;
  setTimeout(function () { if ($('inViewScan') && $('inViewScan').offsetParent) renderTab(); }, 0);
})(window.ELW);
