// Вкладка «Бой» модуля «Флот»: отчёт о бое по киллмейлам zKillboard. Подключается ядром (window.ELW), см. modules/README.md.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, empty = ELW.empty, $ = ELW.$, BASE = ELW.base;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var COL = { A: '#2f8fde', B: '#d4483b', npc: '#7b8a8b' };

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function eve(ts, withDate) {                       // время EVE (UTC) — так бой обсуждают в игре
    var d = new Date(ts * 1000);
    var t = pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
    return withDate ? d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' + t : t;
  }
  function inputTime(ts) { var d = new Date(ts * 1000); return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); }
  function isk(v) { return v === null || v === undefined ? '—' : L.fmtCompact(v); }

  ELW.addTab({ id: 'battle', title: 'Отчёт о бое',
    css: '.bt-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px 14px}\n' +
      '.bt-grid input,.bt-grid select{width:100%;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px}\n' +
      '.bt-sides{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:820px){.bt-sides{grid-template-columns:1fr}}\n' +
      '.bt-side{border-radius:10px;padding:10px 12px;background:var(--panel2);border-top:4px solid var(--c)}\n' +
      '.bt-side h3{margin:0 0 8px;font-size:15px}.bt-kv{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 10px}\n' +
      '.bt-kv div{min-width:0}.bt-kv .k{font-size:11.5px;color:var(--muted)}.bt-kv .v{font-size:17px;font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n' +
      '.bt-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}\n' +
      '.bt-tag{font-size:11px;color:var(--muted)} .bt-fleet{color:var(--good);font-size:11px;margin-left:4px}\n' +
      '.bt-ico{width:20px;height:20px;vertical-align:middle;margin-right:5px;border-radius:3px}\n' +
      '.bt-hi{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}.bt-hi div{background:var(--panel2);border-radius:8px;padding:8px 10px}\n' +
      '.bt-hi .k{font-size:11.5px;color:var(--muted)} .bt-chart svg{width:100%;height:180px}\n' +
      '.bt-filter button.on{outline:2px solid var(--accent)}',
    html: '<section class="panel"><h2>Отчёт о бое <span class="muted small">по киллмейлам zKillboard — как br.evetools</span></h2>' +
      '<p class="small muted" style="margin-top:0">Укажите систему и время боя (время EVE). Или выберите флот из истории — система и время подставятся, а его пилоты будут нашей стороной.</p>' +
      '<div class="bt-grid">' +
      '<label class="small muted">Флот из истории<select id="btFleet"><option value="">—</option></select></label>' +
      '<label class="small muted">Системы (через запятую)<input id="btSys" placeholder="например: 1DQ1-A, T5ZI-S" spellcheck="false"></label>' +
      '<label class="small muted">Начало (время EVE)<input id="btStart" placeholder="2026-10-23 18:00" spellcheck="false"></label>' +
      '<label class="small muted">Конец (время EVE)<input id="btEnd" placeholder="2026-10-23 19:30" spellcheck="false"></label>' +
      '<label class="small muted">Название (необязательно)<input id="btTitle" maxlength="120" placeholder="например: Защита 1DQ"></label>' +
      '</div><div class="controls" style="margin-top:10px"><button type="button" class="btn primary" id="btGo">Собрать отчёт</button>' +
      '<label class="small muted">Сохранённые <select id="btSaved" aria-label="Сохранённые отчёты"><option value="">—</option></select></label>' +
      '<span class="small" id="btMsg" role="status" aria-live="polite"></span></div></section><div id="btReport"></div>',
    render: function () { init(); } });

  var B = { inited: false, rep: null, job: null, side: '', listAt: 0 };

  function init() {
    if (!B.inited) {
      B.inited = true;
      var now = Math.floor(Date.now() / 1000);
      $('btStart').value = inputTime(now - 2 * 3600); $('btEnd').value = inputTime(now);
    }
    if (Date.now() - B.listAt > 20000) {
      B.listAt = Date.now();
      api('/api/fleets').then(function (j) {
        var h = '<option value="">—</option>', cur = $('btFleet').value;
        (j.fleets || []).forEach(function (f) {
          h += '<option value="' + f.id + '">' + esc(eve(f.started_at, true).slice(0, 16) + ' · ' + (f.name || 'флот') + ' · ' + f.pilots + ' пил.') + '</option>';
        });
        $('btFleet').innerHTML = h; $('btFleet').value = cur;
      }, function () { });
      loadSaved();
    }
    draw();
  }
  function loadSaved(select) {
    api('/api/battles').then(function (j) {
      var h = '<option value="">—</option>';
      (j.battles || []).forEach(function (b) {
        h += '<option value="' + esc(b.id) + '">' + esc(eve(b.t0, true).slice(0, 16) + ' · ' + (b.title || b.systems.join(', ')) + ' · ' + b.kms + ' км') + '</option>';
      });
      $('btSaved').innerHTML = h;
      if (select) $('btSaved').value = select; else if (B.rep) $('btSaved').value = B.rep.id;
    }, function () { });
  }

  $('btFleet').addEventListener('change', function () {
    if (!this.value) return;
    var msg = $('btMsg');
    msg.textContent = 'Беру системы и время из флота…';
    api('/api/battle/prefill?fleet_id=' + encodeURIComponent(this.value)).then(function (j) {
      if (!j.ok) { msg.textContent = j.message || 'Не получилось.'; return; }
      $('btSys').value = j.systems.map(function (s) { return s.name; }).join(', ');
      $('btStart').value = j.start; $('btEnd').value = j.end;
      msg.textContent = 'Подставлено. Можно поправить системы и время.';
    });
  });
  $('btSaved').addEventListener('change', function () { if (this.value) open(this.value); });
  $('btGo').addEventListener('click', function () {
    var btn = this, msg = $('btMsg');
    btn.disabled = true; msg.textContent = 'Запускаю…';
    api('/api/battle/build', { method: 'POST', headers: POST, body: JSON.stringify({
      systems: $('btSys').value, start: $('btStart').value, end: $('btEnd').value, title: $('btTitle').value, fleet_id: $('btFleet').value || null }) })
      .then(function (j) {
        if (!j.ok) { btn.disabled = false; msg.innerHTML = '<span style="color:var(--bad)">' + esc(j.message || 'Не получилось.') + '</span>'; return; }
        B.job = j.job; poll(btn);
      }, function () { btn.disabled = false; msg.textContent = 'Нет связи с трекером.'; });
  });
  function poll(btn) {
    api('/api/battle/job?id=' + encodeURIComponent(B.job)).then(function (j) {
      var msg = $('btMsg');
      if (j.state === 'running') { msg.textContent = (j.phase || 'Работаю…') + (j.found ? ' · киллмейлов: ' + j.found : ''); setTimeout(function () { poll(btn); }, 1200); return; }
      btn.disabled = false;
      if (j.state === 'error') { msg.innerHTML = '<span style="color:var(--bad)">' + esc(j.error) + '</span>'; return; }
      msg.textContent = '';
      open(j.battle, true);
    }, function () { setTimeout(function () { poll(btn); }, 2000); });
  }
  function open(id, fresh) {
    api('/api/battle?id=' + encodeURIComponent(id)).then(function (j) {
      if (!j.ok) { $('btMsg').textContent = j.message || 'Отчёт не найден.'; return; }
      B.rep = j; B.side = '';
      if (fresh) loadSaved(id);
      draw();
    });
  }

  // ---------- отчёт ----------
  function nm(id) { var R = B.rep; return id ? (R.lookup.names[String(id)] || String(id)) : '—'; }
  function ent(key) { var e = B.rep.lookup.entities[key]; return e ? (e.ticker ? '[' + e.ticker + '] ' : '') + e.name : key === 'npc' ? 'NPC' : key; }
  function cls(t) { return B.rep.lookup.classes[String(t)] || ''; }
  function sideDot(s) { return '<span class="bt-dot" style="background:' + (COL[s] || COL.npc) + '"></span>'; }
  function ico(t) { return t ? '<img class="bt-ico" src="' + BASE + '/icons/' + t + '.png" alt="" loading="lazy">' : ''; }
  function zk(id) { return '<a href="https://zkillboard.com/kill/' + id + '/" target="_blank" rel="noopener" title="Открыть на zKillboard">↗</a>'; }

  function sideCard(s, R) {
    var d = R.report.sides[s], names = R.report.entities.filter(function (e) { return e.side === s; }).slice(0, 4).map(function (e) { return ent(e.key); });
    var cell = function (k, v, title) { return '<div' + (title ? ' title="' + esc(title) + '"' : '') + '><div class="k">' + k + '</div><div class="v">' + v + '</div></div>'; };
    return '<div class="bt-side" style="--c:' + COL[s] + '"><h3>' + (s === 'A' ? 'Наша сторона' : 'Противник') + '</h3>' +
      '<div class="small muted" style="margin:-4px 0 8px">' + esc(names.join(', ')) + (R.report.entities.filter(function (e) { return e.side === s; }).length > 4 ? ' …' : '') + '</div>' +
      '<div class="bt-kv">' + cell('Пилотов', d.pilots) + cell('Убито', d.kills) + cell('Потеряно', d.ships_lost + (d.pods_lost ? ' + ' + d.pods_lost + ' под' : '')) +
      cell('Уничтожено ISK', isk(d.isk_destroyed)) + cell('Потеряно ISK', isk(d.isk_lost)) +
      cell('Эффективность', d.efficiency === null ? '—' : String(d.efficiency).replace('.', ',') + '%', 'Доля уничтоженного от всего ISK, потерянного обеими сторонами') +
      cell('Урон нанесён', L.fmtCompact(d.damage_done), 'Сумма урона по киллмейлам: только по убитым кораблям') + cell('Урон получен', L.fmtCompact(d.damage_taken)) + '</div></div>';
  }

  function chart(R) {
    var s = R.report.series;
    if (s.length < 2) return '';
    var W = 800, H = 180, P = 30, max = Math.max(1, s[s.length - 1].A, s[s.length - 1].B);
    var x = function (i) { return P + (W - P - 8) * i / (s.length - 1); }, y = function (v) { return H - 20 - (H - 34) * v / max; };
    var line = function (k) { return s.map(function (p, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p[k]).toFixed(1); }).join(' '); };
    return '<div class="bt-chart"><h3 class="small muted" style="margin:14px 0 4px">Потери в ISK нарастающим итогом, по минутам от начала боя</h3>' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="График потерь ISK по минутам">' +
      '<line x1="' + P + '" y1="' + (H - 20) + '" x2="' + W + '" y2="' + (H - 20) + '" stroke="currentColor" stroke-opacity=".25"/>' +
      '<text x="' + P + '" y="12" font-size="11" fill="currentColor" fill-opacity=".6">' + esc(L.fmtCompact(max)) + ' ISK</text>' +
      '<text x="' + P + '" y="' + (H - 4) + '" font-size="11" fill="currentColor" fill-opacity=".6">0 мин</text>' +
      '<text x="' + (W - 8) + '" y="' + (H - 4) + '" font-size="11" text-anchor="end" fill="currentColor" fill-opacity=".6">' + (s.length - 1) + ' мин</text>' +
      '<path d="' + line('A') + '" fill="none" stroke="' + COL.A + '" stroke-width="2.5"/><path d="' + line('B') + '" fill="none" stroke="' + COL.B + '" stroke-width="2.5"/>' +
      '</svg><div class="small muted">' + sideDot('A') + 'потери нашей стороны &nbsp; ' + sideDot('B') + 'потери противника</div></div>';
  }

  function highlights(R) {
    var hi = R.report.highlights, tl = {}, P = {};
    R.report.timeline.forEach(function (t) { tl[t.id] = t; });
    R.report.pilots.forEach(function (p) { P[p.id] = p; });
    var out = [];
    var km = function (id, label) {
      var t = tl[id]; if (!t) return;
      out.push('<div><div class="k">' + label + '</div>' + sideDot(t.side) + ico(t.ship) + esc(nm(t.ship)) + ' — ' + esc(nm(t.victim)) +
        '<div class="small">' + esc(isk(t.value)) + ' ISK · ' + esc(eve(t.t)) + ' ' + zk(t.id) + '</div></div>');
    };
    var pl = function (key, label, fmt) {
      var h = hi[key]; if (!h) return;
      var p = P[h.id] || {};
      out.push('<div><div class="k">' + label + '</div>' + sideDot(p.side) + esc(nm(h.id)) + '<div class="small">' + esc(fmt(h.value)) + '</div></div>');
    };
    km(hi.most_expensive, 'Самый дорогой килл');
    km(hi.first_blood, 'Первая кровь');
    pl('top_damage', 'Больше всех урона', function (v) { return L.fmtInt(v) + ' урона'; });
    pl('top_final_blows', 'Больше всех добиваний', function (v) { return v + ' добиваний'; });
    pl('top_kills', 'Больше всех участий в киллах', function (v) { return v + ' киллов'; });
    pl('top_lost', 'Самые большие потери', function (v) { return isk(v) + ' ISK'; });
    return out.length ? '<h3 class="small muted" style="margin:14px 0 6px">Отличились</h3><div class="bt-hi">' + out.join('') + '</div>' : '';
  }

  function draw() {
    var box = $('btReport'), R = B.rep;
    if (!R) { box.innerHTML = ''; return; }
    var r = R.report;
    var h = '<section class="panel"><h2>' + esc(R.title || R.system_names.join(', ')) + ' <span class="muted small">' + esc(eve(r.t0, true)) + ' — ' + esc(eve(r.t1)) +
      ' (EVE) · ' + esc(L.fmtDur(r.duration)) + ' · киллмейлов ' + r.kms + ' · ' + esc(R.system_names.join(', ')) + '</span></h2>' +
      '<div class="controls" style="margin:-4px 0 10px">' + R.zkill_related.map(function (u, i) { return '<a class="small" href="' + esc(u) + '" target="_blank" rel="noopener">zKillboard: ' + esc(R.system_names[i] || '') + ' ↗</a>'; }).join(' ') +
      '<button type="button" class="btn" id="btCopy">Скопировать итог</button><span class="small muted" id="btCopyMsg" role="status"></span></div>' +
      '<div class="bt-sides">' + sideCard('A', R) + sideCard('B', R) + '</div>' + chart(R) + highlights(R);

    // группы (альянсы и корпорации) с переносом на другую сторону
    h += '<h3 class="small muted" style="margin:16px 0 6px">Альянсы и корпорации <span class="muted">— если кто-то оказался не на той стороне, перенесите</span></h3>' +
      table('btEnt', r.entities.map(function (e) { return Object.assign({ name: ent(e.key) }, e); }), [
        { k: 'side', t: 'Сторона', l: 1, f: function (e) { return sideDot(e.side) + (e.side === 'A' ? 'наша' : 'противник') + (R.overrides[e.key] ? ' <span class="bt-tag">(вручную)</span>' : ''); } },
        { k: 'name', t: 'Группа', l: 1, f: function (e) { return esc(e.name); } },
        { k: 'pilots', t: 'Пилотов' }, { k: 'kills', t: 'Киллов' }, { k: 'losses', t: 'Потерь' },
        { k: 'isk_lost', t: 'Потеряно ISK', f: function (e) { return esc(isk(e.isk_lost)); } },
        { k: 'damage', t: 'Урон', f: function (e) { return esc(L.fmtInt(e.damage)); } },
        { k: '', t: '', f: function (e) { return '<button type="button" class="btn" data-move="' + esc(e.key) + '" data-to="' + (e.side === 'A' ? 'B' : 'A') + '">' + (e.side === 'A' ? 'К противнику' : 'К нашим') + '</button>'; } }
      ], { sort: { k: 'pilots', d: -1 } });

    // корабли сторон
    ['A', 'B'].forEach(function (s) {
      h += '<h3 class="small muted" style="margin:16px 0 6px">' + sideDot(s) + 'Корабли — ' + (s === 'A' ? 'наша сторона' : 'противник') + '</h3>' +
        table('btShips' + s, r.sides[s].ships.map(function (x) { return Object.assign({ name: nm(x.type), cls: cls(x.type) }, x); }), [
          { k: 'name', t: 'Корабль', l: 1, f: function (x) { return ico(x.type) + esc(x.name) + (x.cls ? ' <span class="bt-tag">' + esc(x.cls) + '</span>' : ''); } },
          { k: 'fielded', t: 'Было', title: 'Сколько пилотов были на этом корабле (видно по киллмейлам)' }, { k: 'lost', t: 'Потеряно' },
          { k: 'isk_lost', t: 'Потеряно ISK', f: function (x) { return esc(isk(x.isk_lost)); } },
          { k: 'damage', t: 'Урон', f: function (x) { return esc(L.fmtInt(x.damage)); } }
        ], { sort: { k: 'fielded', d: -1 }, empty: 'Нет данных' });
    });

    // пилоты
    var pilots = r.pilots.filter(function (p) { return !B.side || p.side === B.side; });
    h += '<h3 class="small muted" style="margin:16px 0 6px">Пилоты</h3><div class="controls bt-filter" style="margin-bottom:6px">' +
      ['', 'A', 'B'].map(function (s) { return '<button type="button" class="btn' + (B.side === s ? ' on' : '') + '" data-side="' + s + '">' + (s === '' ? 'Все' : s === 'A' ? 'Наши' : 'Противник') + '</button>'; }).join('') + '</div>' +
      table('btPilots', pilots.map(function (p) { return Object.assign({ name: nm(p.id), group: ent(p.entity), lost: p.isk_lost }, p); }), [
        { k: 'name', t: 'Пилот', l: 1, f: function (p) { return sideDot(p.side) + esc(p.name) + (p.in_fleet ? '<span class="bt-fleet" title="Был в нашем флоте">флот</span>' : '') + '<div class="bt-tag">' + esc(p.group) + '</div>'; } },
        { k: 'ships', t: 'Корабли', l: 1, f: function (p) { return p.ships.slice(0, 3).map(function (t) { return ico(t) + esc(nm(t)); }).join('<br>') || '<span class="muted">—</span>'; } },
        { k: 'damage', t: 'Урон', f: function (p) { return esc(L.fmtInt(p.damage)); } },
        { k: 'kills', t: 'Киллов', title: 'Участие в киллах (был на киллмейле атакующим)' },
        { k: 'final_blows', t: 'Добил' }, { k: 'top_damage', t: 'Топ-урон', title: 'Сколько раз нанёс больше всех урона по цели' },
        { k: 'isk_involved', t: 'ISK в киллах', f: function (p) { return esc(isk(p.isk_involved)); } },
        { k: 'lost', t: 'Потерял', f: function (p) { return p.losses.length ? p.losses.map(function (l) { return ico(l.ship) + esc(isk(l.value)) + ' ' + zk(l.km); }).join('<br>') : '<span class="muted">—</span>'; } }
      ], { sort: { k: 'damage', d: -1 }, limit: 300 });
    if (r.fleet_missing && r.fleet_missing.length) {
      h += '<p class="small muted">Были во флоте, но не попали ни на один киллмейл (' + r.fleet_missing.length + '): ' + esc(r.fleet_missing.map(nm).join(', ')) + '</p>';
    }

    // оружие
    ['A', 'B'].forEach(function (s) {
      if (!r.sides[s].weapons.length) return;
      h += '<h3 class="small muted" style="margin:16px 0 6px">' + sideDot(s) + 'Чем стреляли — ' + (s === 'A' ? 'наша сторона' : 'противник') + '</h3>' +
        table('btW' + s, r.sides[s].weapons.map(function (w) { return Object.assign({ name: nm(w.type) }, w); }), [
          { k: 'name', t: 'Оружие / дроны / модуль', l: 1, f: function (w) { return ico(w.type) + esc(w.name); } },
          { k: 'uses', t: 'На киллмейлах' }, { k: 'damage', t: 'Урон', f: function (w) { return esc(L.fmtInt(w.damage)); } }
        ], { sort: { k: 'damage', d: -1 }, limit: 15 });
    });

    // хронология
    h += '<h3 class="small muted" style="margin:16px 0 6px">Хронология (время EVE)</h3>' +
      table('btTl', r.timeline.map(function (t) { return Object.assign({ vname: nm(t.victim) }, t); }), [
        { k: 't', t: 'Время', f: function (t) { return esc(eve(t.t)); } },
        { k: 'vname', t: 'Жертва', l: 1, f: function (t) { return sideDot(t.side) + ico(t.ship) + esc(nm(t.ship)) + ' — ' + esc(t.vname) + '<div class="bt-tag">' + esc(ent(t.victim_entity)) + (t.npc ? ' · убили NPC' : '') + (t.solo ? ' · соло' : '') + (t.awox ? ' · свои' : '') + '</div>'; } },
        { k: 'value', t: 'ISK', f: function (t) { return esc(isk(t.value)); } },
        { k: 'attackers', t: 'Атакующих' },
        { k: '', t: 'Добил', l: 1, f: function (t) { return t.final_blow ? esc(t.final_blow.c ? nm(t.final_blow.c) : ent(t.final_blow.e)) + '<div class="bt-tag">' + esc(nm(t.final_blow.s)) + '</div>' : '—'; } },
        { k: '', t: 'Больше всех урона', l: 1, f: function (t) { return t.top ? esc(t.top.c ? nm(t.top.c) : ent(t.top.e)) + '<div class="bt-tag">' + esc(nm(t.top.s)) + ' · ' + esc(L.fmtInt(t.top.d)) + '</div>' : '—'; } },
        { k: '', t: '', f: function (t) { return zk(t.id); } }
      ], { sort: { k: 't', d: 1 }, limit: 500 });
    box.innerHTML = h + '</section>';
  }

  $('btReport').addEventListener('click', function (e) {
    var R = B.rep;
    if (!R) return;
    var mv = e.target.closest && e.target.closest('button[data-move]');
    if (mv) {
      mv.disabled = true;
      api('/api/battle/move', { method: 'POST', headers: POST, body: JSON.stringify({ id: R.id, entity: mv.getAttribute('data-move'), side: mv.getAttribute('data-to') }) })
        .then(function (j) { if (j.ok) { B.rep = j; draw(); } else mv.disabled = false; });
      return;
    }
    var sb = e.target.closest && e.target.closest('button[data-side]');
    if (sb) { B.side = sb.getAttribute('data-side'); draw(); return; }
    if (e.target.id === 'btCopy') {
      var r = R.report, a = r.sides.A, b = r.sides.B;
      var text = (R.title || R.system_names.join(', ')) + ' — ' + eve(r.t0, true) + ' EVE, ' + L.fmtDur(r.duration) + '\n' +
        'Наши: ' + a.pilots + ' пилотов, убито ' + a.kills + ', потеряно ' + a.losses + ', ' + isk(a.isk_destroyed) + ' / ' + isk(a.isk_lost) + ' ISK, эффективность ' + (a.efficiency === null ? '—' : a.efficiency + '%') + '\n' +
        'Противник: ' + b.pilots + ' пилотов, убито ' + b.kills + ', потеряно ' + b.losses + ', ' + isk(b.isk_destroyed) + ' / ' + isk(b.isk_lost) + ' ISK\n' +
        R.zkill_related.join('\n');
      var msg = $('btCopyMsg');
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { msg.textContent = 'Скопировано'; }, function () { msg.textContent = 'Не удалось'; });
    }
  });
})(window.ELW);
