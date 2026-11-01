// «Планетарка» в «Производстве»: калькулятор цепочки P4 → P0 — циклы и фабрики на каждом шаге, сырьё и типы планет.
// Что строить — выбрать слева или перенести планетарку из «Плана производства» (закупка плана).
(function (ELW) {
  'use strict';
  if (!ELW) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var LV = { 0: 'P0 сырьё', 1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4' };
  var PL_COL = { barren: '#b39a7a', gas: '#d9c56b', ice: '#9fd4ee', lava: '#e0654a', oceanic: '#4a8fd9', plasma: '#c86ad9', storm: '#7f8fb0', temperate: '#5fb85f' };
  var Q = { built: false, cat: null, planets: {}, piIds: {}, items: [], days: 7, lv: '', q: '', res: null, busy: false, msg: '', cc: 5, head: 500, margin: 10, mode: 'factory', reserve: 4 };
  try {
    var sv = JSON.parse(localStorage.getItem('elw.industry.pi') || '{}');
    Q.items = Array.isArray(sv.items) ? sv.items : []; Q.days = +sv.days || 7; Q.mode = sv.mode === 'local' ? 'local' : 'factory';
    Q.cc = sv.cc >= 0 && sv.cc <= 5 ? +sv.cc : 5; Q.head = +sv.head || 500; Q.margin = sv.margin >= 0 ? +sv.margin : 10; Q.reserve = sv.reserve >= 0 ? +sv.reserve : 4;
  } catch (e) { }
  function remember() { try { localStorage.setItem('elw.industry.pi', JSON.stringify({ items: Q.items, days: Q.days, cc: Q.cc, head: Q.head, margin: Q.margin, mode: Q.mode, reserve: Q.reserve })); } catch (e) { } }
  function ico(t) { return ELW_INDUSTRY.ico ? ELW_INDUSTRY.ico(t) : ''; }
  function cp(n) { return ELW_INDUSTRY.cp ? ELW_INDUSTRY.cp(n) : esc(n); }
  function vol(v) { return L.fmtInt(Math.round(v)) + ' м³'; }
  function lvBadge(l) { return '<span class="pi-lv l' + l + '">' + (l ? 'P' + l : 'P0') + '</span>'; }
  function planet(k) { return '<span class="pi-pl" style="--c:' + (PL_COL[k] || 'var(--muted)') + '">' + esc(Q.planets[k] || k) + '</span>'; }

  var st = document.createElement('style');
  st.textContent = '.pi-layout{display:grid;grid-template-columns:minmax(240px,300px) minmax(0,1fr);gap:14px;align-items:start}' +
    '.pi-side{position:sticky;top:10px;max-height:calc(100vh - 20px);display:flex;flex-direction:column;padding:10px}.pi-list{overflow:auto;flex:1;min-height:200px;margin-top:6px}' +
    '.pi-q{width:100%;box-sizing:border-box;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px}' +
    '.pi-h{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin:10px 0 4px}' +
    '.pi-i{display:flex;align-items:center;gap:6px;font-size:12.5px;padding:3px 4px;border-radius:6px}.pi-i:hover{background:var(--panel2)}.pi-i .in-ico{width:18px;height:18px;margin:0}' +
    '.pi-i .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pi-i .btn{padding:0 8px;line-height:1.5}' +
    '.pi-lv{display:inline-block;font-size:10.5px;font-weight:700;border-radius:4px;padding:0 5px;color:#0f1115;background:#8a94a3}' +
    '.pi-lv.l1{background:#9fb3c8}.pi-lv.l2{background:#6fcf5f}.pi-lv.l3{background:#e8c840}.pi-lv.l4{background:#f0a050}' +
    '.pi-pl{display:inline-block;font-size:11px;border-radius:5px;padding:0 6px;margin:1px 3px 1px 0;border:1px solid var(--c);color:var(--c)}' +
    '.pi-items{display:flex;flex-direction:column;gap:6px;margin-top:8px}.pi-it{display:flex;align-items:center;gap:8px;background:var(--panel2);border-radius:8px;padding:6px 8px}' +
    '.pi-it .n{flex:1;min-width:0}.pi-it input,.pi-days{width:100px;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:4px 6px;text-align:right;font:inherit}' +
    '.pi-x{background:none;border:0;color:var(--muted);cursor:pointer;font-size:16px}.pi-x:hover{color:var(--bad)}' +
    '.pi-cover{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}.pi-cover .pi-pl{font-size:13px;padding:2px 10px}' +
    '.pi-t{width:100%;border-collapse:collapse;font-size:13px}.pi-t th{font-size:11.5px;color:var(--muted);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}' +
    '.pi-t td{padding:6px 8px;border-top:1px solid var(--line);vertical-align:middle}.pi-t .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.pi-t .in-ico{margin-right:6px}' +
    '.pi-m{display:inline-flex;align-items:center;white-space:nowrap;margin:1px 10px 1px 0;font-size:12.5px}.pi-m b{font-weight:600;margin-left:3px}.pi-m .in-ico{width:16px;height:16px;margin-right:3px}' +
    '.pi-planets{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin-top:10px}' +
    '.pi-card{background:var(--panel2);border:1px solid var(--line);border-top:4px solid var(--c);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;font-size:12.5px}' +
    '.pi-card h3{margin:0;font-size:14px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}.pi-card .k{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-top:2px}' +
    '.pi-row{display:flex;align-items:center;gap:6px;justify-content:space-between}.pi-row .in-ico{width:16px;height:16px;margin-right:4px}.pi-row b{font-variant-numeric:tabular-nums;white-space:nowrap}' +
    '.pi-load{height:6px;background:var(--panel);border-radius:3px;overflow:hidden}.pi-load>div{height:100%;background:var(--c)}' +
    '.pi-num{width:90px;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:4px 6px;text-align:right;font:inherit}' +
    '.pi-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;display:flex;align-items:flex-start;justify-content:center;padding:30px 12px;overflow:auto}' +
    '.pi-dlg{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:1240px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.5);padding:14px 16px}' +
    '.pi-dh{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.pi-dh h2{margin:0;font-size:17px}.pi-dx{margin-left:auto;font-size:20px;background:none;border:0;color:var(--muted);cursor:pointer}' +
    '.pi-sv{overflow:auto;margin-top:10px;background:var(--panel2);border-radius:10px;padding:8px}.pi-sv svg{display:block}' +
    '.pi-sv .bx{fill:var(--panel);stroke:var(--line);stroke-width:1.2}.pi-sv .bx.hub{stroke:var(--accent);stroke-width:2}.pi-sv .bx.io{stroke-dasharray:4 3}' +
    '.pi-sv text{fill:var(--text);font:12px system-ui,Segoe UI,sans-serif}.pi-sv text.m{fill:var(--muted);font-size:11px}.pi-sv text.t{font-weight:700;font-size:12.5px}' +
    '.pi-sv .ar{fill:none;stroke:var(--muted);stroke-width:1.4}.pi-sv .ar.in{stroke:var(--good)}.pi-sv .ar.out{stroke:var(--accent)}.pi-sv .hd{fill:var(--c)}' +
    '.pi-steps{margin:10px 0 0;padding-left:20px;font-size:13px;line-height:1.55}' +
    '@media(max-width:900px){.pi-layout{grid-template-columns:1fr}.pi-side{position:static;max-height:420px}}';
  document.head.appendChild(st);

  function shell() {
    if (Q.built) return;
    Q.built = true;
    $('inPiView').innerHTML = '<div class="pi-layout"><aside class="panel pi-side"><input type="search" class="pi-q" id="piQ" placeholder="Поиск: Coolant, Robotics…" aria-label="Поиск планетарки">' +
      '<div class="in-chips" id="piLv" style="margin-top:6px"></div><div class="pi-list" id="piList"><p class="small muted">Загружаю…</p></div></aside>' +
      '<div><section class="panel" style="margin-top:0"><h2>Планетарка <span class="muted small">цепочка P4 → P0: циклы, фабрики, сырьё и планеты</span></h2>' +
      '<div class="controls" style="flex-wrap:wrap;gap:8px"><button type="button" class="btn primary" id="piFromPlan" title="Взять P1–P4 из закупки «Плана производства»">Перенести из плана производства</button>' +
      '<label class="small">Успеть за <input type="number" class="pi-days" id="piDays" min="0.1" max="365" step="0.5" value="' + esc(Q.days) + '" aria-label="Срок, суток"> сут.</label>' +
      '<button type="button" class="btn" id="piClear">Очистить</button><span class="small" id="piMsg" role="status"></span></div>' +
      '<div class="pi-items" id="piItems"></div></section><div id="piRes"></div></div></div>';
    $('piQ').addEventListener('input', function () { Q.q = this.value; drawList(); });
    $('piDays').addEventListener('change', function () { Q.days = Math.max(0.1, Math.min(365, +this.value || 7)); this.value = Q.days; remember(); calc(); });
    api('/api/industry/pi/catalog').then(function (j) {
      if (!j.ok) return;
      Q.cat = j.items; Q.planets = j.planets || {}; Q.piIds = {};
      (j.pi_ids || []).forEach(function (t) { Q.piIds[t] = true; });
      drawList(); drawItems(); if (Q.items.length) calc();
    });
  }
  function info(id) { var r = (Q.cat || []).filter(function (x) { return x[0] === id; })[0]; return r ? { name: r[1], level: r[2] } : { name: String(id), level: 0 }; }
  function drawList() {
    if (!Q.cat) return;
    $('piLv').innerHTML = ['', '1', '2', '3', '4'].map(function (l) { return '<button type="button" class="in-chip' + (Q.lv === l ? ' on' : '') + '" data-pi-lv="' + l + '" style="padding:3px 9px;font-size:12px">' + (l ? 'P' + l : 'все') + '</button>'; }).join('');
    var q = Q.q.trim().toLowerCase(), h = '', last = null, have = {};
    Q.items.forEach(function (i) { have[i.id] = true; });
    Q.cat.forEach(function (r) {
      if ((Q.lv && String(r[2]) !== Q.lv) || (q && r[1].toLowerCase().indexOf(q) < 0)) return;
      if (r[2] !== last) { last = r[2]; h += '<div class="pi-h">' + LV[r[2]] + '</div>'; }
      h += '<div class="pi-i">' + ico(r[0]) + '<span class="n" title="' + esc(r[1]) + '">' + esc(r[1]) + '</span>' +
        (have[r[0]] ? '<span class="small muted">в расчёте</span>' : '<button type="button" class="btn" data-pi-add="' + r[0] + '" aria-label="' + esc('Добавить ' + r[1]) + '">+</button>') + '</div>';
    });
    $('piList').innerHTML = h || '<p class="small muted">Ничего не нашлось.</p>';
  }
  function drawItems() {
    $('piItems').innerHTML = Q.items.length ? Q.items.map(function (it) {
      var x = info(it.id);
      return '<div class="pi-it">' + lvBadge(x.level) + ico(it.id) + '<span class="n">' + cp(x.name) + '</span>' +
        '<input type="number" min="1" step="1" value="' + it.qty + '" data-pi-qty="' + it.id + '" aria-label="' + esc('Сколько: ' + x.name) + '"> шт.' +
        '<button type="button" class="pi-x" data-pi-del="' + it.id + '" aria-label="' + esc('Убрать ' + x.name) + '">✕</button></div>';
    }).join('') : '<p class="small muted" style="margin:0">Пока пусто. Добавьте продукт слева или перенесите планетарку из «Плана производства».</p>';
    var m = $('piMsg'); if (m) m.textContent = Q.msg;
  }
  var timer = null;
  function calc() {
    clearTimeout(timer);
    if (!Q.items.length) { Q.res = null; drawRes(); return; }
    timer = setTimeout(function () {
      api('/api/industry/pi/calc', { method: 'POST', headers: POST, body: JSON.stringify({ items: Q.items, days: Q.days, cc: Q.cc, head_h: Q.head, margin: Q.margin, mode: Q.mode, reserve: Q.reserve }) }).then(function (j) {
        if (j.ok) { Q.res = j; drawRes(); setTimeout(drawRes, 3000); }                       // иконки догружаются
      });
    }, 150);
  }
  function drawRes() {
    var r = Q.res, box = $('piRes');
    if (!box) return;
    if (!r) { box.innerHTML = ''; return; }
    var dur = function (s) { return L.fmtDur(Math.round(s)); };
    var h = '<section class="panel"><div class="tiles">' +
      ELW.tile('Сырьё P0', L.fmtCompact(r.raw.reduce(function (a, x) { return a + x.qty; }, 0)) + ' ед.', r.raw.length + ' видов · ' + vol(r.raw_volume)) +
      ELW.tile('Циклов', L.fmtInt(r.cycles), 'всех фабрик вместе') +
      ELW.tile('Фабрик', L.fmtInt(r.factories), 'чтобы успеть за ' + String(r.days).replace('.', ',') + ' сут.') +
      ELW.tile('Типов планет', String(r.cover.length), 'минимум, чтобы добыть всё сырьё') + '</div>' +
      '<h3 class="small muted" style="margin:12px 0 4px">Где добывать — наименьший набор планет:</h3><div class="pi-cover">' + r.cover.map(planet).join('') + '</div>' +
      (r.high_tech ? '<p class="small" style="margin:4px 0 0;color:var(--warn)">P4 строится на High-Tech Production Plant — его можно поставить только на Barren или Temperate.</p>' : '') + '</section>';
    h += layout(r.layout);
    // сырьё
    h += '<section class="panel"><h2>Сырьё P0 <span class="muted small">добыча экстракторами; «в час» — сколько нужно добывать, чтобы успеть</span></h2><div class="tw"><table class="pi-t"><thead><tr>' +
      '<th class="l">Сырьё</th><th class="r">Нужно</th><th class="r">В час</th><th class="r">Объём</th><th class="l">На каких планетах</th></tr></thead><tbody>' +
      r.raw.map(function (x) {
        return '<tr><td class="l">' + ico(x.type_id) + cp(x.name) + '</td><td class="r">' + L.fmtInt(x.qty) + '</td><td class="r">' + L.fmtInt(x.per_hour) + '</td>' +
          '<td class="r">' + vol(x.volume) + '</td><td class="l">' + x.planets.map(function (k) { return r.cover.indexOf(k) >= 0 ? planet(k) : '<span class="pi-pl" style="--c:var(--muted);opacity:.6">' + esc(Q.planets[k] || k) + '</span>'; }).join('') + '</td></tr>';
      }).join('') + '</tbody></table></div></section>';
    // шаги по уровням
    [4, 3, 2, 1].forEach(function (lv) {
      var rows = r.steps.filter(function (s) { return s.level === lv; });
      if (!rows.length) return;
      h += '<section class="panel"><h2>' + lvBadge(lv) + ' ' + esc(rows[0].factory) + ' <span class="muted small">цикл ' + dur(rows[0].cycle) + ' · произведёте ' + vol(r.volume[lv] || 0) + '</span></h2>' +
        '<div class="tw"><table class="pi-t"><thead><tr><th class="l">Продукт</th><th class="r">Нужно</th><th class="r">Выйдет</th><th class="r">Циклов</th><th class="r">Фабрик</th><th class="l">На все циклы нужно</th></tr></thead><tbody>' +
        rows.map(function (s) {
          return '<tr><td class="l">' + ico(s.type_id) + cp(s.name) + (s.target ? ' <span class="pi-lv" style="background:var(--accent)">заказ ' + L.fmtInt(s.target) + '</span>' : '') + '</td>' +
            '<td class="r">' + L.fmtInt(s.need) + '</td><td class="r">' + L.fmtInt(s.produced) + (s.left ? ' <span class="small muted">+' + L.fmtInt(s.left) + ' остаток</span>' : '') + '</td>' +
            '<td class="r" title="' + esc(s.out + ' шт. за цикл ' + dur(s.cycle)) + '">' + L.fmtInt(s.runs) + '</td><td class="r" title="' + esc('загрузка: ' + dur(s.busy) + ' работы фабрик') + '">' + L.fmtInt(s.factories) + '</td>' +
            '<td class="l">' + s.inputs.map(function (i) { return '<span class="pi-m" title="' + esc(i.per_cycle + ' за цикл') + '">' + ico(i.type_id) + esc(i.name) + ' <b>×' + L.fmtInt(i.qty) + '</b></span>'; }).join(' ') + '</td></tr>';
        }).join('') + '</tbody></table></div></section>';
    });
    box.innerHTML = h;
  }
  var STRUCT = { pad: 'космопорт', ecu: 'экстракторы', head: 'головки', basic: 'базовые фабрики', '2': 'продвинутые P2', '3': 'продвинутые P3', '4': 'High-Tech P4' };
  function layout(lay) {
    if (!lay) return '';
    var row = function (x, v, unit) { return '<div class="pi-row"><span>' + ico(x.type_id) + esc(x.name) + '</span><b>' + L.fmtInt(v) + ' ' + unit + '</b></div>'; };
    var bar = function (v, max, unit, what) {
      var pct = Math.min(100, v * 100 / max);
      return '<div class="pi-row" title="' + esc(what + ': ' + L.fmtInt(v) + ' из ' + L.fmtInt(max) + ' ' + unit) + '"><span class="small muted" style="width:76px">' + what + '</span>' +
        '<div class="pi-load" style="flex:1"><div style="width:' + pct + '%;' + (pct > 95 ? 'background:var(--warn)' : '') + '"></div></div><b class="small">' + L.fmtInt(v) + ' / ' + L.fmtInt(max) + '</b></div>';
    };
    var makes = function (p) { return p.make.map(function (m) { return '<div class="pi-row"><span>' + lvBadge(m.level) + ' ' + ico(m.type_id) + esc(m.name) + '</span><b>×' + m.factories + '</b></div>'; }).join(''); };
    var io = function (p) {
      return (p.import.length ? '<div class="k">Ввозить в сутки</div>' + p.import.map(function (e) { return row(e, e.per_day, 'шт.'); }).join('') : '') +
        (p.export.length ? '<div class="k">Вывозить в сутки</div>' + p.export.map(function (e) { return row(e, e.per_day, 'шт.'); }).join('') : '');
    };
    var n = 0, h = '<section class="panel"><h2>По планетам <span class="muted small">' + lay.count + ' планет · ' + lay.characters + ' перс. (до 6 планет на персонажа)</span></h2>' +
      '<div class="controls" style="flex-wrap:wrap;gap:6px;margin-bottom:6px"><span class="small muted">Сборка P2–P4</span>' +
      '<button type="button" class="in-chip' + (lay.mode === 'factory' ? ' on' : '') + '" data-pi-mode="factory" title="Добывающие только добывают и делают P1, всё остальное — на заводских планетах">на отдельных заводских планетах</button>' +
      '<button type="button" class="in-chip' + (lay.mode === 'local' ? ' on' : '') + '" data-pi-mode="local" title="P2–P4 ставятся прямо на добывающие планеты, где больше всего входов уже есть">без сборочных планет (по возможности)</button></div>' +
      '<div class="controls" style="flex-wrap:wrap;gap:12px"><label class="small">Командный центр <select id="piCc" aria-label="Уровень командного центра">' +
      [0, 1, 2, 3, 4, 5].map(function (l) { return '<option value="' + l + '"' + (Q.cc === l ? ' selected' : '') + '>уровень ' + l + '</option>'; }).join('') + '</select></label>' +
      '<label class="small">Добыча одной головки <input type="number" class="pi-num" id="piHead" min="1" step="50" value="' + esc(Q.head) + '"> P0/ч</label>' +
      '<label class="small">Запас мощности <input type="number" class="pi-num" id="piMargin" min="0" max="50" step="1" value="' + esc(Q.margin) + '" style="width:64px"> %</label>' +
      (lay.mode === 'local' ? '<label class="small">Резерв под сборку на добывающей <input type="number" class="pi-num" id="piReserve" min="0" max="20" step="1" value="' + esc(Q.reserve) + '" style="width:64px"> фабр.</label>' : '') + '</div>' +
      '<p class="small muted" style="margin:6px 0 0">Центр уровня ' + lay.cc + ': энергия <b>' + L.fmtInt(lay.pg) + ' МВт</b>, процессор <b>' + L.fmtInt(lay.cpu) + ' tf</b>' +
      (lay.pg_max ? ' (с запасом ' + lay.margin + '% под линки — ' + L.fmtInt(lay.pg_max) + ' / ' + L.fmtInt(lay.cpu_max) + ')' : '') + '. Уровень = навык Command Center Upgrades. ' +
      'На планету ставится, сколько влезет: космопорт, экстракторы (на каждое сырьё свой, до 10 головок), головки, фабрики. ' +
      'Добыча головки сильно зависит от планеты и длины цикла — впишите свою' + (lay.solo_h ? '; одно сырьё на пустой планете — до ' + L.fmtInt(lay.solo_h) + ' P0/ч' : '') + '.' +
      (lay.mode === 'local' && lay.reserve !== Q.reserve ? ' Резерв под сборку уменьшен до ' + lay.reserve + ' — больше не влезает без сильного урезания добычи.' : '') + '</p>' +
      (lay.error ? '<p class="small" style="margin:6px 0 0;color:var(--bad)">' + esc(lay.error) + '</p>' : '') +
      (lay.mode === 'local' && lay.spilled ? '<p class="small" style="margin:6px 0 0;color:var(--warn)">На добывающих не поместилось фабрик: ' + lay.spilled +
        ' — для них добавлена заводская планета. Поднимите уровень центра или «Резерв под сборку».</p>' : '') +
      (lay.mode === 'local' && !lay.spilled && !lay.error ? '<p class="small" style="margin:6px 0 0;color:var(--good)">Всё собирается на добывающих планетах — отдельные заводы не нужны.</p>' : '') +
      '<div class="pi-planets">';
    lay.planets.forEach(function (p) {
      n++;
      var c = p.role === 'extract' ? (PL_COL[p.kind] || 'var(--muted)') : 'var(--accent)';
      h += '<div class="pi-card" style="--c:' + c + '"><h3>Планета ' + n + ' · ' + (p.role === 'extract' ? 'добыча ' + planet(p.kind) : 'завод' + (p.kind ? ' <span class="pi-pl" style="--c:#b39a7a">Barren</span><span class="pi-pl" style="--c:#5fb85f">Temperate</span>' : ' <span class="small muted">любой тип</span>')) + '</h3>' +
        bar(p.pg, lay.pg, 'МВт', 'энергия') + bar(p.cpu, lay.cpu, 'tf', 'процессор') +
        '<button type="button" class="btn" data-pi-scheme="' + (n - 1) + '" style="align-self:flex-start;padding:3px 10px;font-size:12px">Показать шаблон</button>' +
        '<div class="small muted">' + Object.keys(p.structures).map(function (k) { return esc(STRUCT[k] || k) + ' ' + p.structures[k]; }).join(' · ') + '</div>';
      if (p.role === 'extract') {
        h += '<div class="k">Добывать</div>' + p.extract.map(function (e) {
          return '<div class="pi-row"><span>' + ico(e.type_id) + esc(e.name) + ' <span class="small muted">' + e.ecu + ' ECU · ' + e.heads + ' гол.</span></span><b>' + L.fmtInt(e.per_hour) + ' в час</b></div>';
        }).join('') +
          (p.make.length ? '<div class="k">Сборка здесь же: ' + p.used + ' фабр.</div>' + makes(p) : '') + io(p) +
          (p.local_p2.length ? '<div class="small" style="color:var(--good)">Можно делать здесь же P2: ' + esc(p.local_p2.join(', ')) + ' — оба P1 добываются на этой планете.</div>' : '');
      } else {
        h += '<div class="k">Фабрики: ' + p.used + '</div>' + makes(p) + io(p);
      }
      h += '</div>';
    });
    return h + '</div></section>';
  }
  // ----- шаблон планеты: схема построек и маршрутов (по ней строится колония в игре) -----
  var BW = 230, BH = 46, GY = 12, CX = [16, 300, 584, 868], PAD = 16;
  function svgEsc(t) { return esc(t); }
  function box(x, y, h, title, sub, cls, icon) {
    return '<rect class="bx ' + (cls || '') + '" x="' + x + '" y="' + y + '" width="' + BW + '" height="' + h + '" rx="8"/>' +
      (icon ? '<image href="' + ELW.base + '/icons/' + icon + '.png" x="' + (x + 8) + '" y="' + (y + (h - 26) / 2) + '" width="26" height="26"/>' : '') +
      '<text class="t" x="' + (x + (icon ? 42 : 10)) + '" y="' + (y + 19) + '">' + svgEsc(title) + '</text>' +
      (sub ? '<text class="m" x="' + (x + (icon ? 42 : 10)) + '" y="' + (y + 35) + '">' + svgEsc(sub) + '</text>' : '');
  }
  function arrow(x1, y1, x2, y2, cls, label) {
    var mx = (x1 + x2) / 2;
    return '<path class="ar ' + (cls || '') + '" d="M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' + x2 + ',' + y2 + '" marker-end="url(#piArr)"/>' +
      (label ? '<text class="m" x="' + (mx + 4) + '" y="' + ((y1 + y2) / 2 - 4) + '">' + svgEsc(label) + '</text>' : '');
  }
  function scheme(p, idx, lay) {
    var col = [[], [], [], []], arrows = [], hubY, hubH;
    var c = p.role === 'extract' ? (PL_COL[p.kind] || '#8a94a3') : 'var(--accent)';
    // колонка 1 — экстракторы (каждый ECU — свой блок с головками), колонка 2 — базовые фабрики
    (p.extract || []).forEach(function (e) {
      var heads = e.heads, ecus = [];
      for (var i = 0; i < e.ecu; i++) { var hn = Math.min(10, heads); heads -= hn; ecus.push(hn); }
      var first = col[0].length;
      ecus.forEach(function (hn, i) { col[0].push({ kind: 'ecu', e: e, heads: hn, n: i + 1, of: ecus.length }); });
      col[1].push({ kind: 'basic', e: e, from: [first, col[0].length - 1] });
    });
    (p.make || []).forEach(function (m) { col[3].push({ kind: 'make', m: m }); });
    var rows = Math.max(col[0].length, col[1].length, col[3].length, 3);
    var height = PAD * 2 + rows * (BH + GY) - GY + 150;
    var yOf = function (i, n) { var total = n * (BH + GY) - GY, top = PAD + (rows * (BH + GY) - GY - total) / 2; return top + i * (BH + GY); };
    var h = '';
    col[0].forEach(function (it, i) {
      var y = yOf(i, col[0].length);
      it.y = y;
      h += box(CX[0], y, BH, 'Экстрактор: ' + it.e.name, it.heads + ' головок' + (it.of > 1 ? ' · ' + it.n + ' из ' + it.of : '') + ' · ≈' + L.fmtInt(Math.round(it.heads * lay.head_h)) + '/ч', '', it.e.type_id);
      for (var k = 0; k < it.heads; k++) h += '<circle class="hd" style="--c:' + c + '" cx="' + (CX[0] + BW - 12 - k * 9) + '" cy="' + (y + BH - 8) + '" r="3"/>';
    });
    col[1].forEach(function (it, i) {
      var y = yOf(i, col[1].length);
      it.y = y;
      h += box(CX[1], y, BH, 'Базовая фабрика ×' + it.e.basic, (it.e.p1 ? '→ ' + it.e.p1.name : ''), '', it.e.p1 ? it.e.p1.type_id : 0);
      for (var j = it.from[0]; j <= it.from[1]; j++) arrows.push(arrow(CX[0] + BW, col[0][j].y + BH / 2, CX[1], y + BH / 2, '', j === it.from[0] ? L.fmtInt(it.e.per_hour) + ' P0/ч' : ''));
    });
    // колонка 3 — космопорт (через него все маршруты), ниже — командный центр
    hubH = Math.max(BH * 2, Math.min(rows, 4) * (BH + GY) - GY);
    hubY = PAD + (rows * (BH + GY) - GY - hubH) / 2;
    h += '<rect class="bx hub" x="' + CX[2] + '" y="' + hubY + '" width="' + BW + '" height="' + hubH + '" rx="10"/>' +
      '<text class="t" x="' + (CX[2] + 12) + '" y="' + (hubY + 22) + '">Космопорт (Launchpad)</text>' +
      '<text class="m" x="' + (CX[2] + 12) + '" y="' + (hubY + 40) + '">хранилище: всё приходит сюда</text>' +
      '<text class="m" x="' + (CX[2] + 12) + '" y="' + (hubY + 56) + '">и отсюда раздаётся по фабрикам</text>';
    var hubMid = hubY + hubH / 2;
    col[1].forEach(function (it) { arrows.push(arrow(CX[1] + BW, it.y + BH / 2, CX[2], hubMid, 'out', it.e.p1 ? L.fmtInt(it.e.p1.per_day) + '/сут' : '')); });
    // колонка 4 — продвинутые фабрики: входы с космопорта, выход обратно
    col[3].forEach(function (it, i) {
      var y = yOf(i, col[3].length), m = it.m;
      h += box(CX[3], y, BH, 'P' + m.level + ' ×' + m.factories + ' ' + m.name, m.inputs.map(function (x) { return x.name; }).join(' + '), '', m.type_id);
      arrows.push(arrow(CX[2] + BW, hubMid - 6, CX[3], y + BH / 2 - 6, 'in', ''));
      arrows.push(arrow(CX[3], y + BH / 2 + 6, CX[2] + BW, hubMid + 6, 'out', ''));
    });
    // ввоз / вывоз — снизу, через космопорт
    var ioY = PAD + rows * (BH + GY) - GY + 40, ioH = 90;
    var imp = (p.import || []).map(function (x) { return x.name + ' ' + L.fmtInt(x.per_day); }).join(', ');
    var exp = (p.export || []).map(function (x) { return x.name + ' ' + L.fmtInt(x.per_day); }).join(', ');
    var wrap = function (t, x, y) {
      var out = '', line = '', parts = t.split(', '), ly = y;
      parts.forEach(function (w) { if ((line + w).length > 34) { out += '<text class="m" x="' + x + '" y="' + ly + '">' + svgEsc(line) + '</text>'; ly += 15; line = ''; } line += (line ? ', ' : '') + w; });
      return out + (line ? '<text class="m" x="' + x + '" y="' + ly + '">' + svgEsc(line) + '</text>' : '');
    };
    h += '<rect class="bx io" x="' + CX[1] + '" y="' + ioY + '" width="' + BW + '" height="' + ioH + '" rx="8"/><text class="t" x="' + (CX[1] + 10) + '" y="' + (ioY + 19) + '">Ввоз в сутки</text>' +
      (imp ? wrap(imp, CX[1] + 10, ioY + 37) : '<text class="m" x="' + (CX[1] + 10) + '" y="' + (ioY + 37) + '">ничего</text>');
    h += '<rect class="bx io" x="' + CX[3] + '" y="' + ioY + '" width="' + BW + '" height="' + ioH + '" rx="8"/><text class="t" x="' + (CX[3] + 10) + '" y="' + (ioY + 19) + '">Вывоз в сутки</text>' +
      (exp ? wrap(exp, CX[3] + 10, ioY + 37) : '<text class="m" x="' + (CX[3] + 10) + '" y="' + (ioY + 37) + '">ничего</text>');
    if (imp) arrows.push(arrow(CX[1] + BW, ioY + 30, CX[2] + 30, hubY + hubH, 'in', ''));
    if (exp) arrows.push(arrow(CX[2] + BW - 30, hubY + hubH, CX[3], ioY + 30, 'out', ''));
    var W = CX[3] + BW + PAD;
    var svg = '<svg viewBox="0 0 ' + W + ' ' + height + '" style="width:100%;max-width:' + W + 'px;height:auto;min-width:640px" role="img" aria-label="Схема планеты">' +
      '<defs><marker id="piArr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>' +
      arrows.join('') + h + '</svg>';
    // по шагам — что ставить в игре
    var st = p.structures || {}, steps = [];
    steps.push('Командный центр уровня ' + lay.cc + (p.role === 'extract' ? ' на планете ' + (Q.planets[p.kind] || p.kind) : p.kind ? ' на Barren или Temperate' : '') + '; рядом — космопорт (Launchpad).');
    (p.extract || []).forEach(function (e) {
      steps.push('Экстракторы на ' + e.name + ': ' + e.ecu + ' шт., всего ' + e.heads + ' головок (≈' + L.fmtInt(e.per_hour) + ' P0/ч); маршрут — в базовые фабрики.');
      if (e.p1) steps.push('Базовые фабрики ×' + e.basic + ' со схемой ' + e.p1.name + '; выход — маршрутом в космопорт.');
    });
    (p.make || []).forEach(function (m) {
      steps.push((m.level === 4 ? 'High-Tech Production Plant' : 'Advanced Industry Facility') + ' ×' + m.factories + ' со схемой ' + m.name + ' (' + m.inputs.map(function (x) { return x.name; }).join(' + ') +
        '); входы — маршрутами из космопорта, выход — в космопорт.');
    });
    if ((p.import || []).length) steps.push('Ввоз через таможню или космопорт: ' + imp + ' в сутки.');
    if ((p.export || []).length) steps.push('Вывоз из космопорта: ' + exp + ' в сутки.');
    steps.push('Все постройки соединить линками с космопортом (звездой). Энергия ' + L.fmtInt(p.pg) + ' / ' + L.fmtInt(lay.pg) + ' МВт, процессор ' + L.fmtInt(p.cpu) + ' / ' + L.fmtInt(lay.cpu) + ' tf — без учёта линков.');
    return '<div class="pi-modal" id="piModal" role="dialog" aria-modal="true" aria-label="Шаблон планеты ' + (idx + 1) + '"><div class="pi-dlg">' +
      '<div class="pi-dh"><h2>Шаблон: планета ' + (idx + 1) + ' · ' + (p.role === 'extract' ? 'добыча ' + planet(p.kind) : 'завод') + '</h2>' +
      '<span class="small muted">' + Object.keys(st).map(function (k) { return esc(STRUCT[k] || k) + ' ' + st[k]; }).join(' · ') + '</span>' +
      '<button type="button" class="pi-dx" data-pi-close aria-label="Закрыть">✕</button></div>' +
      '<div class="pi-sv">' + svg + '</div><ol class="pi-steps">' + steps.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ol>' +
      '<p class="small muted" style="margin:6px 0 0">Схема логическая: расположение на планете выбирайте по горячим точкам сырья; стрелки — маршруты (Routes). Зелёные — из космопорта в фабрику, синие — в космопорт.</p></div></div>';
  }
  function openScheme(i) {
    var lay = Q.res && Q.res.layout, p = lay && lay.planets[i];
    if (!p) return;
    var old = $('piModal'); if (old) old.remove();
    document.body.insertAdjacentHTML('beforeend', scheme(p, i, lay));
  }
  document.addEventListener('click', function (e) {
    var m = $('piModal');
    if (m && (e.target === m || e.target.closest('[data-pi-close]'))) { m.remove(); return; }
    var b = e.target.closest && e.target.closest('[data-pi-scheme]');
    if (b) openScheme(+b.getAttribute('data-pi-scheme'));
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && $('piModal')) $('piModal').remove(); });
  function add(id, qty) {
    var cur = Q.items.filter(function (i) { return i.id === id; })[0];
    if (cur) cur.qty = qty !== undefined ? qty : cur.qty;
    else Q.items.push({ id: id, qty: qty || 1 });
  }
  function fromPlan() {
    var need = ELW_INDUSTRY.plan && ELW_INDUSTRY.plan.needs ? ELW_INDUSTRY.plan.needs() : null;
    if (need === null) { Q.msg = 'Сначала посчитайте «План производства».'; drawItems(); return; }
    var n = 0;
    need.forEach(function (x) { var lv = info(x.id).level; if (Q.piIds[x.id] && lv >= 1) { add(x.id, x.qty); n++; } });
    Q.msg = n ? 'Перенесено из плана: ' + n + ' поз.' : 'В закупке плана нет планетарки (P1–P4).';
    remember(); drawItems(); drawList(); calc();
  }
  document.addEventListener('click', function (e) {
    var root = $('inPiView');
    if (!root || !root.contains(e.target)) return;
    var t = e.target, b = t.closest('[data-pi-add],[data-pi-del],[data-pi-lv],[data-pi-mode]');
    if (t.id === 'piFromPlan') { fromPlan(); return; }
    if (t.id === 'piClear') { Q.items = []; Q.msg = ''; remember(); drawItems(); drawList(); calc(); return; }
    if (!b) return;
    if (b.hasAttribute('data-pi-add')) { add(+b.getAttribute('data-pi-add')); Q.msg = ''; remember(); drawItems(); drawList(); calc(); }
    else if (b.hasAttribute('data-pi-del')) { var d = +b.getAttribute('data-pi-del'); Q.items = Q.items.filter(function (i) { return i.id !== d; }); remember(); drawItems(); drawList(); calc(); }
    else if (b.hasAttribute('data-pi-mode')) { Q.mode = b.getAttribute('data-pi-mode'); remember(); calc(); }
    else { Q.lv = b.getAttribute('data-pi-lv'); drawList(); }
  });
  document.addEventListener('change', function (e) {
    var pid = e.target && e.target.id;
    if (pid === 'piCc' || pid === 'piHead' || pid === 'piMargin' || pid === 'piReserve') {
      var v = +e.target.value;
      if (pid === 'piCc') Q.cc = Math.max(0, Math.min(5, Math.round(v)));
      else if (pid === 'piHead') Q.head = Math.max(1, v || 500);
      else if (pid === 'piMargin') Q.margin = Math.max(0, Math.min(50, v || 0));
      else Q.reserve = Math.max(0, Math.min(20, Math.round(v || 0)));
      remember(); calc(); return;
    }
    var id = e.target && e.target.getAttribute && e.target.getAttribute('data-pi-qty');
    if (!id) return;
    var q = Math.max(1, Math.round(+e.target.value || 1));
    e.target.value = q;
    Q.items.forEach(function (i) { if (i.id === +id) i.qty = q; });
    remember(); calc();
  });

  window.ELW_INDUSTRY = window.ELW_INDUSTRY || {};
  ELW_INDUSTRY.pi = { render: function () { shell(); } };
})(window.ELW);
