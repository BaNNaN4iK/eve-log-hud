// Вкладка модуля «Фиты»: фиты альянса как дерево прокачки — доктрина за доктриной, от фрегатов к капиталам.
// Плашка корабля, под ней полоска «изучено %»; нажатие — окно с подробностями (навыки, модули, описание).
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, $ = ELW.$, BASE = ELW.base;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var TIERS = ['Фрегаты', 'Эсминцы', 'Крейсеры', 'Линейные крейсеры', 'Линкоры', 'Капитальные', 'Прочее'];
  // классы кораблей: столбцы дерева идут по возрастанию — от фрегатов к титанам
  var GROUPS = [['Frigate', 'Фрегаты'], ['Assault Frigate', 'Штурмовые фрегаты'], ['Interceptor', 'Перехватчики'], ['Covert Ops', 'Ковер-опс'],
    ['Stealth Bomber', 'Стелс-бомбардировщики'], ['Electronic Attack Ship', 'Фрегаты РЭБ'], ['Logistics Frigate', 'Фрегаты поддержки'],
    ['Expedition Frigate', 'Экспедиционные фрегаты'], ['Destroyer', 'Эсминцы'], ['Interdictor', 'Интердикторы'], ['Tactical Destroyer', 'Тактические эсминцы'],
    ['Command Destroyer', 'Командные эсминцы'], ['Cruiser', 'Крейсеры'], ['Heavy Assault Cruiser', 'Тяжёлые штурмовые крейсеры'],
    ['Logistics', 'Крейсеры поддержки'], ['Force Recon Ship', 'Разведчики'], ['Combat Recon Ship', 'Боевые разведчики'],
    ['Heavy Interdiction Cruiser', 'Тяжёлые интердикторы'], ['Strategic Cruiser', 'Стратегические крейсеры'], ['Flag Cruiser', 'Флагманские крейсеры'],
    ['Combat Battlecruiser', 'Линейные крейсеры'], ['Attack Battlecruiser', 'Атакующие линейные крейсеры'], ['Command Ship', 'Командные корабли'],
    ['Battleship', 'Линкоры'], ['Black Ops', 'Линкоры Black Ops'], ['Marauder', 'Мародёры'], ['Carrier', 'Носители'], ['Dreadnought', 'Дредноуты'],
    ['Lancer Dreadnought', 'Дредноуты-копейщики'], ['Force Auxiliary', 'Вспомогательные (FAX)'], ['Supercarrier', 'Суперносители'], ['Titan', 'Титаны']];
  var GROUP_IX = {};
  GROUPS.forEach(function (g, i) { GROUP_IX[g[0]] = i; });
  function groupName(g) { var i = GROUP_IX[g]; return i === undefined ? (g || 'Прочее') : GROUPS[i][1]; }
  var SLOTS = [['high', 'Верхние слоты'], ['mid', 'Средние слоты'], ['low', 'Нижние слоты'], ['rig', 'Риги'], ['subsystem', 'Подсистемы'],
    ['drone', 'Дроны'], ['charge', 'Заряды'], ['cargo', 'Груз']];
  var F = { data: null, loading: false, char: '', doc: '', q: '', open: null, msg: '', key: null, view: 'skills' };
  try { var sv = JSON.parse(localStorage.getItem('elw.fits') || '{}'); F.char = sv.char || ''; F.doc = sv.doc || ''; F.view = sv.view === 'class' ? 'class' : 'skills'; } catch (e) { }
  function remember() { try { localStorage.setItem('elw.fits', JSON.stringify({ char: F.char, doc: F.doc, view: F.view })); } catch (e) { } }
  var CW = 224, CH = 122, GX = 52, GY = 14, PAD = 8;                 // дерево: плашка, отступы между столбцами и строками
  function ico(t, cls) { return t ? '<img class="' + (cls || 'ft-ico') + '" src="' + BASE + '/icons/' + t + '.png" alt="" loading="lazy">' : ''; }
  function tier(g) {
    g = String(g || '').toLowerCase();
    if (/carrier|dreadnought|force auxiliary|titan|lancer|capital/.test(g)) return 5;
    if (/battleship|black ops|marauder/.test(g)) return 4;
    if (/battlecruiser|command ship/.test(g)) return 3;
    if (/frigate|interceptor|covert|bomber|electronic attack|expedition|shuttle/.test(g)) return 0;
    if (/destroyer|interdictor$/.test(g)) return 1;
    if (/cruiser|logistics|recon|interdiction/.test(g)) return 2;
    return 6;
  }
  function state(r) { return !r || !r.known ? 'unk' : r.ok ? 'ok' : r.pct >= 80 ? 'near' : 'far'; }
  function pct(r) { return r && r.known ? r.pct + '%' : '?'; }
  function dur(min) { return min ? L.fmtDur(min * 60) : '—'; }
  function copy(text) {
    if (window.ELW_INDUSTRY && ELW_INDUSTRY.copyText) return ELW_INDUSTRY.copyText(text);
    var ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(ta); ta.select(); var ok = false; try { ok = document.execCommand('copy'); } catch (e) { }
    document.body.removeChild(ta); return ok ? Promise.resolve() : Promise.reject(new Error('copy'));
  }

  ELW.addTab({ id: 'fits', title: 'Фиты',
    css: '.ft-bar0{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.ft-bar0 select,.ft-bar0 input[type=search]{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit;font-size:13px}' +
      '.ft-lane{margin-top:14px;border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg,color-mix(in srgb,var(--panel2) 70%,transparent),var(--panel));padding:10px 12px}' +
      '.ft-lh{display:flex;align-items:baseline;gap:8px;margin-bottom:8px}.ft-lh b{font-size:14px}.ft-lh .s{font-size:12px;color:var(--muted)}' +
      '.ft-row{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding-bottom:4px}.ft-col{display:flex;flex-direction:column;gap:10px;min-width:200px}' +
      '.ft-colh{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);text-align:center}' +
      '.ft-arrow{display:flex;align-items:center;justify-content:center;min-width:34px;color:var(--line);font-size:18px;padding-top:16px}' +
      '.ft-arrow:before{content:"";display:block;width:22px;height:2px;background:var(--line);margin-right:-4px}.ft-arrow:after{content:"▶";font-size:10px}' +
      '.ft-card{width:200px;box-sizing:border-box;border-radius:10px;background:var(--panel2);border:1px solid var(--line);border-left:4px solid var(--muted);padding:8px 9px;cursor:pointer;display:flex;flex-direction:column;gap:6px;text-align:left;font:inherit;color:inherit;box-shadow:0 2px 10px rgba(0,0,0,.25);transition:transform .12s,border-color .12s}' +
      '.ft-card:hover,.ft-card:focus{transform:translateY(-2px);border-color:var(--accent);outline:none}' +
      '.ft-card.ok{border-left-color:var(--good)}.ft-card.near{border-left-color:var(--warn)}.ft-card.far{border-left-color:var(--bad)}' +
      '.ft-top{display:flex;gap:8px;align-items:center;min-width:0}.ft-ico{width:44px;height:44px;border-radius:7px;background:var(--panel);flex:none}' +
      '.ft-nm{font-weight:650;font-size:13px;line-height:1.2;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}.ft-sh{font-size:11.5px;color:var(--muted)}' +
      '.ft-pb{height:8px;background:var(--panel);border-radius:4px;overflow:hidden}.ft-pb>div{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent),var(--good))}' +
      '.ft-card.far .ft-pb>div{background:linear-gradient(90deg,#8a3b33,var(--bad))}.ft-card.near .ft-pb>div{background:linear-gradient(90deg,#9a6a1f,var(--warn))}' +
      '.ft-pl{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted)}.ft-pl b{color:var(--text)}' +
      '.ft-modal{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto}' +
      '.ft-dlg{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:880px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.5);padding:16px 18px}' +
      '.ft-dh{display:flex;gap:12px;align-items:center}.ft-dh .ft-ico{width:64px;height:64px}.ft-dt{font-size:18px;font-weight:700}.ft-x{margin-left:auto;font-size:20px;background:none;border:0;color:var(--muted);cursor:pointer}' +
      '.ft-dlg h3{font-size:13px;margin:14px 0 6px;color:var(--muted);letter-spacing:.03em;text-transform:uppercase}' +
      '.ft-sk{display:grid;grid-template-columns:1fr auto auto;gap:4px 12px;align-items:center;font-size:13px}.ft-dots{display:inline-flex;gap:3px}' +
      '.ft-dots i{width:9px;height:9px;border-radius:2px;background:var(--panel2);border:1px solid var(--line)}.ft-dots i.have{background:var(--good);border-color:var(--good)}' +
      '.ft-dots i.queue{background:var(--accent);border-color:var(--accent)}.ft-dots i.missing{background:transparent;border-color:var(--bad)}' +
      '.ft-mods{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:4px 16px;font-size:12.5px}.ft-mods div{display:flex;align-items:center;gap:6px}.ft-mods img{width:20px;height:20px;border-radius:3px}' +
      '.ft-chip{display:inline-block;font-size:11px;border-radius:6px;padding:1px 7px;border:1px solid var(--line);color:var(--muted);margin-right:4px}' +
      '.ft-tag{display:inline-block;font-size:10.5px;border-radius:4px;padding:0 5px;margin-left:4px;border:1px solid currentColor}.ft-tag.min{color:var(--bad)}.ft-tag.plan{color:var(--muted)}' +
      '.ft-tw{overflow-x:auto;padding-bottom:4px}.ft-canvas{position:relative}.ft-canvas svg{position:absolute;left:0;top:0;pointer-events:none}' +
      '.ft-node{position:absolute}.ft-node .ft-card{width:' + CW + 'px;height:' + CH + 'px}.ft-node.dim{opacity:.35}' +
      '.ft-ln{fill:none;stroke:var(--line);stroke-width:2}.ft-ln.ok{stroke:var(--good)}.ft-ln.near{stroke:var(--warn)}' +
      '.ft-inc{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.ft-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:8px}.ft-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}',
    html: '<div id="ftBox"></div>',
    render: function () { if (F.ready) draw(); } });

  function load(force) {
    if (F.loading && !force) return;
    F.loading = true;
    api('/api/fits?char=' + encodeURIComponent(F.char || '')).then(function (j) {
      F.loading = false;
      if (j.ok) {
        var first = !F.data;
        F.data = j; if (!F.char && j.char) F.char = String(j.char); F.key = null; draw();
        if (first) setTimeout(function () { F.tick = (F.tick || 0) + 1; F.key = null; draw(); }, 6000);   // иконки кораблей догружаются
      }
    }, function () { F.loading = false; $('ftBox').innerHTML = '<section class="panel"><p class="in-bad">Нет связи с трекером.</p></section>'; });
  }

  function draw() {
    var d = F.data;
    if (!d) { if (!F.loading) load(); if (!$('ftBox').innerHTML) $('ftBox').innerHTML = '<section class="panel"><p class="muted">Загружаю фиты…</p></section>'; return; }
    var key = JSON.stringify([F.view, F.char, F.doc, F.q, F.msg, d.built, d.char, d.busy, d.characters.map(function (c) { return c.synced + c.error; }), F.tick || 0]);
    if (key === F.key) return;
    F.key = key;
    var h = '<section class="panel"><h2>Фиты альянса <span class="muted small">дерево прокачки: доктрина за доктриной, от фрегатов к капиталам</span></h2>';
    if (!d.has_data) {
      h += '<p>Фитов пока нет. Загрузите файл фитов <code>fits_data.json</code> — его выгружает из Alliance Auth (плагин «Фиты и навыки») скрипт модуля <code>build_fits_data.py</code>; ' +
        'файл можно получить у командования альянса. Это внутренние доктрины альянса — они хранятся только на этом компьютере.</p>';
    }
    var chars = d.characters || [];
    h += '<div class="ft-bar0">' + (chars.length ? '<label class="small muted" for="ftChar">Персонаж</label><select id="ftChar">' + chars.map(function (c) {
      return '<option value="' + c.id + '"' + (String(c.id) === String(d.char) ? ' selected' : '') + '>' + esc(c.name) + '</option>'; }).join('') + '</select>' : '') +
      (d.has_data ? '<input id="ftQ" type="search" placeholder="Поиск: корабль, фит…" value="' + esc(F.q) + '" aria-label="Поиск фита">' : '') +
      '<span style="flex:1"></span>' + (chars.length ? '<button type="button" class="btn" id="ftSync"' + (d.busy ? ' disabled' : '') + '>' + (d.busy ? 'Обновляю…' : 'Обновить навыки') + '</button>' : '') +
      '<label class="btn" style="cursor:pointer">Загрузить файл фитов<input type="file" id="ftFile" accept=".json,application/json" hidden></label></div>';
    var me = chars.filter(function (c) { return String(c.id) === String(d.char); })[0];
    if (!chars.length) h += '<p class="small" style="margin:8px 0 0">Чтобы видеть, насколько выучены навыки, подключите персонажа: <a href="#" data-goto="modules">«Настройки» → «Персонажи EVE»</a> (нужны доступы «навыки» и «очередь навыков»).</p>';
    else if (me && me.error) h += '<p class="small" style="margin:8px 0 0;color:var(--warn)">' + esc(me.name) + ': ' + esc(me.error) + '. <a href="#" data-goto="modules">«Персонажи EVE»</a></p>';
    else if (me) h += '<p class="small muted" style="margin:8px 0 0">' + esc(me.name) + (me.total_sp ? ' · ' + L.fmtCompact(me.total_sp) + ' SP' : '') + (me.synced ? ' · навыки обновлены ' + esc(L.fmtDateTime(me.synced)) : ' · навыки ещё не загружены') + '</p>';
    if (F.msg) h += '<div class="small" role="status" style="margin-top:6px">' + esc(F.msg) + '</div>';
    if (d.has_data) {
      var docs = d.doctrines.filter(function (x) { return d.fits.some(function (f) { return f.doctrines.indexOf(x.id) >= 0; }); });
      h += '<div class="ft-bar0" style="margin-top:8px"><span class="small muted">Вид</span>' +
        '<button type="button" class="in-chip' + (F.view === 'skills' ? ' on' : '') + '" data-ft-view="skills" title="Следом — фит, который проще всего докачать после предыдущего">дерево по навыкам</button>' +
        '<button type="button" class="in-chip' + (F.view === 'class' ? ' on' : '') + '" data-ft-view="class">по классам кораблей</button></div>' +
        '<div class="ft-bar0" style="margin-top:6px"><span class="small muted">Доктрина</span><button type="button" class="in-chip' + (!F.doc ? ' on' : '') + '" data-ft-doc="">все</button>' +
        docs.map(function (x) { return '<button type="button" class="in-chip' + (String(x.id) === F.doc ? ' on' : '') + '" data-ft-doc="' + x.id + '">' + esc(x.name) + '</button>'; }).join('') + '</div>' +
        '<div class="ft-legend"><span><i style="background:var(--good)"></i>готов</span><span><i style="background:var(--warn)"></i>от 80%</span><span><i style="background:var(--bad)"></i>меньше 80%</span>' +
        '<span><i style="background:var(--muted)"></i>навыки неизвестны</span><span>процент — в очках навыков (уровень V весит больше I); учтён минимум и план «летать хорошо»</span></div>' +
        (F.view === 'skills' ? '<div class="small muted" style="margin-top:4px">Дерево по навыкам: первым — фит, который дешевле всего выучить с нуля; дальше по линиям — фиты, которые проще всего докачать после предыдущего ' +
          '(часть навыков уже выучена). На плашке — сколько ещё SP доучить после предыдущего.</div>' : '') +
        '<div class="small muted" style="margin-top:4px">Фиты выгружены из AA' + (d.built ? ' ' + esc(d.built) : '') + '.</div>';
    }
    h += '</section>';
    if (d.has_data) h += F.view === 'skills' ? treeLanes(d) : lanes(d);
    $('ftBox').innerHTML = h;
    if (F.open) modal(F.open);
  }

  function lanes(d) {
    var q = F.q.trim().toLowerCase(), byDoc = {}, order = [];
    var pass = function (f) { return !q || f.name.toLowerCase().indexOf(q) >= 0 || f.ship_name.toLowerCase().indexOf(q) >= 0 || (f.ship_group || '').toLowerCase().indexOf(q) >= 0; };
    d.doctrines.forEach(function (x) { byDoc[x.id] = { d: x, fits: [] }; order.push(x.id); });
    byDoc.none = { d: { id: 'none', name: 'Без доктрины', description: '' }, fits: [] }; order.push('none');
    d.fits.forEach(function (f) {
      if (!pass(f)) return;
      (f.doctrines.length ? f.doctrines : ['none']).forEach(function (id) { if (byDoc[id]) byDoc[id].fits.push(f); });
    });
    var h = '';
    order.forEach(function (id) {
      var lane = byDoc[id];
      if (!lane.fits.length || (F.doc && String(id) !== F.doc)) return;
      var cols = {};                                           // столбец — класс корабля, по порядку прокачки
      lane.fits.forEach(function (f) { var g = f.ship_group || ''; (cols[g] = cols[g] || []).push(f); });
      var ts = Object.keys(cols).sort(function (a, b) {
        return tier(a) - tier(b) || (GROUP_IX[a] === undefined ? 99 : GROUP_IX[a]) - (GROUP_IX[b] === undefined ? 99 : GROUP_IX[b]) || a.localeCompare(b);
      });
      var ok = lane.fits.filter(function (f) { var r = d.ready[f.id]; return r && r.ok; }).length;
      h += '<section class="ft-lane"><div class="ft-lh"><b>' + esc(lane.d.name) + '</b><span class="s">' + lane.fits.length + ' фит.' + (d.char ? ' · готов к ' + ok + ' из ' + lane.fits.length : '') + '</span>' +
        (lane.d.description ? '<span class="s" style="flex:1;text-align:right">' + esc(lane.d.description.slice(0, 120)) + '</span>' : '') + '</div><div class="ft-row">';
      ts.forEach(function (t, i) {
        if (i) h += '<div class="ft-arrow" aria-hidden="true"></div>';
        h += '<div class="ft-col"><div class="ft-colh" title="' + esc(TIERS[tier(t)]) + '">' + esc(groupName(t)) + '</div>' +
          cols[t].sort(function (a, b) { return a.ship_name.localeCompare(b.ship_name) || a.name.localeCompare(b.name); }).map(function (f) { return card(f, d.ready[f.id]); }).join('') + '</div>';
      });
      h += '</div></section>';
    });
    return h || '<section class="panel"><p class="muted">Ничего не нашлось.</p></section>';
  }
  // ----- дерево по навыкам: каждый фит висит на том, после которого его проще всего докачать -----
  function sp(v) { return v >= 1e6 ? String(Math.round(v / 1e5) / 10).replace('.', ',') + ' млн' : v >= 1e3 ? Math.round(v / 1e3) + ' тыс.' : String(v); }
  function treeLanes(d) {
    var q = F.q.trim().toLowerCase(), byId = {}, h = '';
    d.fits.forEach(function (f) { byId[f.id] = f; });
    var pass = function (f) { return !q || f.name.toLowerCase().indexOf(q) >= 0 || f.ship_name.toLowerCase().indexOf(q) >= 0; };
    d.doctrines.concat([{ id: 'none', name: 'Без доктрины', description: '' }]).forEach(function (doc) {
      if (F.doc && String(doc.id) !== F.doc) return;
      var nodes = (d.trees[String(doc.id)] || []).filter(function (n) { return byId[n.id]; });
      if (!nodes.length || (q && !nodes.some(function (n) { return pass(byId[n.id]); }))) return;
      var kids = {}, row = 0, maxDepth = 0, pos = {};
      nodes.forEach(function (n) { (kids[n.parent === null ? 'root' : n.parent] = kids[n.parent === null ? 'root' : n.parent] || []).push(n); maxDepth = Math.max(maxDepth, n.depth); });
      function place(n) {                                     // листья — по строкам, родитель — посередине своих детей
        var ch = kids[n.id] || [];
        ch.forEach(place);
        var y = ch.length ? (pos[ch[0].id].y + pos[ch[ch.length - 1].id].y) / 2 : row++;
        pos[n.id] = { x: n.depth, y: y, n: n };
      }
      (kids.root || []).forEach(place);
      var W = (maxDepth + 1) * (CW + GX) - GX + PAD * 2, H = row * (CH + GY) - GY + PAD * 2, lines = '';
      nodes.forEach(function (n) {
        if (n.parent === null || !pos[n.parent]) return;
        var a = pos[n.parent], b = pos[n.id], x1 = PAD + a.x * (CW + GX) + CW, y1 = PAD + a.y * (CH + GY) + CH / 2, x2 = PAD + b.x * (CW + GX), y2 = PAD + b.y * (CH + GY) + CH / 2, mx = x1 + GX / 2;
        var r = d.ready[n.id];
        lines += '<path d="M' + x1 + ',' + y1 + ' H' + mx + ' V' + y2 + ' H' + x2 + '" class="ft-ln ' + state(r) + '"/>';
      });
      var ok = nodes.filter(function (n) { var r = d.ready[n.id]; return r && r.ok; }).length;
      h += '<section class="ft-lane"><div class="ft-lh"><b>' + esc(doc.name) + '</b><span class="s">' + nodes.length + ' фит.' + (d.char ? ' · готов к ' + ok + ' из ' + nodes.length : '') + '</span>' +
        (doc.description ? '<span class="s" style="flex:1;text-align:right">' + esc(doc.description.slice(0, 120)) + '</span>' : '') + '</div>' +
        '<div class="ft-tw"><div class="ft-canvas" style="width:' + W + 'px;height:' + H + 'px"><svg width="' + W + '" height="' + H + '" aria-hidden="true">' + lines + '</svg>' +
        nodes.map(function (n) {
          var p = pos[n.id], f = byId[n.id], dim = q && !pass(f);
          return '<div class="ft-node' + (dim ? ' dim' : '') + '" style="left:' + (PAD + p.x * (CW + GX)) + 'px;top:' + (PAD + p.y * (CH + GY)) + 'px">' + card(f, d.ready[n.id], n, byId[n.parent]) + '</div>';
        }).join('') + '</div></div></section>';
    });
    return h || '<section class="panel"><p class="muted">Ничего не нашлось.</p></section>';
  }
  function card(f, r, n, parent) {
    return '<button type="button" class="ft-card ' + state(r) + '" data-ft-open="' + f.id + '" title="' + esc(f.ship_name + ' — ' + f.name) + '">' +
      '<div class="ft-top">' + ico(f.ship_type_id) + '<div style="min-width:0"><div class="ft-nm">' + esc(f.name) + '</div><div class="ft-sh">' + esc(f.ship_name) + '</div></div></div>' +
      (n ? '<div class="ft-inc" title="' + esc(parent ? 'если навыки «' + parent.name + '» уже выучены' : 'всего навыков фита') + '">' +
        (parent ? '+' + sp(n.extra) + ' SP после «' + esc(parent.ship_name) + '»' : 'с нуля: ' + sp(n.total) + ' SP') + '</div>' : '') +
      '<div class="ft-pb"><div style="width:' + (r && r.known ? r.pct : 0) + '%"></div></div>' +
      '<div class="ft-pl"><span>' + (r && r.known ? (r.ok ? '<b>готов</b>' : r.can_fly ? 'можно сесть' : 'не хватает минимума') : 'навыки неизвестны') + '</span><b>' + pct(r) + '</b></div></button>';
  }

  function modal(id) {
    var d = F.data, f = d.fits.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!f) { F.open = null; return; }
    var r = d.ready[f.id], S = d.skills;
    var docs = d.doctrines.filter(function (x) { return f.doctrines.indexOf(x.id) >= 0; });
    var dots = function (m) {
      var o = '';
      for (var lv = 1; lv <= 5; lv++) o += '<i class="' + (lv <= m.have ? 'have' : lv <= m.need ? (lv <= m.queued ? 'queue' : 'missing') : '') + '"></i>';
      return '<span class="ft-dots" title="выучено ' + m.have + ', нужно ' + m.need + (m.queued > m.have ? ', в очереди до ' + m.queued : '') + '">' + o + '</span>';
    };
    var h = '<div class="ft-modal" id="ftModal" role="dialog" aria-modal="true" aria-label="' + esc(f.name) + '"><div class="ft-dlg">' +
      '<div class="ft-dh">' + ico(f.ship_type_id) + '<div><div class="ft-dt">' + esc(f.name) + '</div><div class="muted">' + esc(f.ship_name) + (f.ship_group ? ' · ' + esc(f.ship_group) : '') + '</div>' +
      '<div style="margin-top:4px">' + docs.map(function (x) { return '<span class="ft-chip">' + esc(x.name) + '</span>'; }).join('') + '</div></div>' +
      '<button type="button" class="ft-x" data-ft-close aria-label="Закрыть">✕</button></div>';
    h += '<div class="tiles" style="margin-top:12px">' + ELW.tile('Изучено', pct(r), r && r.known ? (r.ok ? 'всё выучено' : r.can_fly ? 'минимум есть — можно сесть' : 'не хватает минимума') : (d.characters.length ? 'навыки персонажа не загружены — «Персонажи EVE»' : 'подключите персонажа'), r && r.ok ? 'bounty' : '') +
      ELW.tile('Осталось учить', r && r.known ? dur(r.minutes_left) : '—', r && r.known && r.sp_left ? L.fmtCompact(r.sp_left) + ' SP, ~30 SP/мин' : '') +
      ELW.tile('Не хватает навыков', r && r.known ? String(r.missing.length) : '—', r && r.known ? r.missing.filter(function (m) { return m.minimum; }).length + ' из минимума' : '') + '</div>';
    var path = [];                                               // путь прокачки в первой доктрине фита
    var tr = d.trees[String((f.doctrines[0] !== undefined ? f.doctrines[0] : 'none'))] || [], tn = {};
    tr.forEach(function (n) { tn[n.id] = n; });
    for (var cur = tn[f.id]; cur; cur = cur.parent !== null ? tn[cur.parent] : null) path.unshift(cur);
    if (path.length > 1) {
      var byId = {}; d.fits.forEach(function (x) { byId[x.id] = x; });
      h += '<h3>Путь прокачки</h3><div style="font-size:13px">' + path.map(function (n, i) {
        var x = byId[n.id];
        return (i ? ' → ' : '') + '<b' + (n.id === f.id ? ' style="color:var(--accent)"' : '') + '>' + esc(x.name) + '</b> <span class="muted">(' + (i ? '+' + sp(n.extra) : sp(n.total)) + ' SP)</span>';
      }).join('') + '</div>';
    }
    if (f.description) h += '<h3>Описание</h3><div style="white-space:pre-wrap;font-size:13px">' + esc(f.description) + '</div>';
    if (r && r.known && r.missing.length) {
      h += '<h3>Чего не хватает <span class="muted" style="text-transform:none">— сначала минимум, короткие раньше</span></h3><div class="ft-sk">' + r.missing.map(function (m) {
        return '<span>' + esc(m.name) + (m.minimum ? '<span class="ft-tag min">минимум</span>' : '<span class="ft-tag plan">план</span>') + '</span>' + dots(m) + '<span class="muted small">' + L.fmtCompact(m.sp_left) + ' SP</span>';
      }).join('') + '</div>';
    }
    var all = [];
    Object.keys(f.required || {}).forEach(function (k) { all.push([k, f.required[k], true]); });
    Object.keys(f.plan || {}).forEach(function (k) { if (!(k in (f.required || {})) || f.plan[k] > f.required[k]) all.push([k, f.plan[k], false]); });
    all.sort(function (a, b) { return ((S[a[0]] || [''])[0]).localeCompare((S[b[0]] || [''])[0]); });
    h += '<details style="margin-top:12px"><summary class="small" style="cursor:pointer">Все навыки фита (' + all.length + ')</summary><div class="ft-sk" style="margin-top:6px">' + all.map(function (x) {
      return '<span>' + esc((S[x[0]] || [x[0]])[0]) + (x[2] ? '' : '<span class="ft-tag plan">план</span>') + '</span><span>' + ['', 'I', 'II', 'III', 'IV', 'V'][x[1]] + '</span><span></span>';
    }).join('') + '</div></details>';
    h += '<h3>Модули</h3>';
    SLOTS.forEach(function (s) {
      var items = (f.items || []).filter(function (i) { return i.slot === s[0]; });
      if (!items.length) return;
      h += '<div class="small muted" style="margin:6px 0 2px">' + s[1] + '</div><div class="ft-mods">' + items.map(function (i) {
        return '<div>' + ico(i.type_id, '') + '<span>' + esc(i.name) + (i.qty > 1 ? ' <b>×' + L.fmtInt(i.qty) + '</b>' : '') + '</span></div>'; }).join('') + '</div>';
    });
    h += '<div class="controls" style="margin-top:14px"><button type="button" class="btn primary" data-ft-copy="eft">Копировать фит (EFT)</button>' +
      '<button type="button" class="btn" data-ft-copy="buy">Копировать «Купить всё»</button><span class="small" id="ftCopyMsg" role="status"></span></div></div></div>';
    var old = $('ftModal'); if (old) old.remove();
    document.body.insertAdjacentHTML('beforeend', h);
  }
  function close() { F.open = null; var m = $('ftModal'); if (m) m.remove(); }

  document.addEventListener('click', function (e) {
    var t = e.target;
    var m = $('ftModal');
    if (m && (t === m || t.closest('[data-ft-close]'))) { close(); return; }
    var cp = t.closest && t.closest('[data-ft-copy]');
    if (cp && F.open) {
      var f = F.data.fits.filter(function (x) { return String(x.id) === String(F.open); })[0], kind = cp.getAttribute('data-ft-copy');
      var text = kind === 'eft' ? f.eft : (function () {
        var sum = {}; sum[f.ship_name] = 1;
        (f.items || []).forEach(function (i) { sum[i.name] = (sum[i.name] || 0) + (i.qty || 1); });
        return Object.keys(sum).map(function (n) { return n + ' ' + sum[n]; }).join('\n');
      })();
      copy(text).then(function () { $('ftCopyMsg').textContent = kind === 'eft' ? 'Скопировано — в игре: фитинг → «Импорт из буфера».' : 'Скопировано — вставьте в «Купить несколько» на рынке игры.'; },
        function () { $('ftCopyMsg').textContent = 'Не удалось скопировать.'; });
      return;
    }
    var box = $('ftBox');
    if (!box || !box.contains(t)) return;
    var o = t.closest('[data-ft-open]');
    if (o) { F.open = o.getAttribute('data-ft-open'); modal(F.open); return; }
    var vw = t.closest('[data-ft-view]');
    if (vw) { F.view = vw.getAttribute('data-ft-view'); remember(); F.key = null; draw(); return; }
    var dc = t.closest('[data-ft-doc]');
    if (dc) { F.doc = dc.getAttribute('data-ft-doc'); remember(); F.key = null; draw(); return; }
    if (t.id === 'ftSync') {
      F.msg = 'Обновляю навыки…'; F.key = null; draw();
      api('/api/fits/refresh', { method: 'POST', headers: POST, body: '{}' }).then(function (j) {
        F.msg = j.message || ''; setTimeout(function () { F.msg = ''; load(true); }, 6000);
      });
    }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && $('ftModal')) close(); });
  document.addEventListener('change', function (e) {
    if (e.target && e.target.id === 'ftChar') { F.char = e.target.value; remember(); load(true); }
    if (e.target && e.target.id === 'ftFile' && e.target.files[0]) {
      var rd = new FileReader();
      rd.onload = function () {
        var data;
        try { data = JSON.parse(rd.result); } catch (err) { F.msg = 'Это не JSON-файл.'; F.key = null; draw(); return; }
        api('/api/fits/import', { method: 'POST', headers: POST, body: JSON.stringify({ data: data }) }).then(function (j) { F.msg = j.message || ''; load(true); },
          function () { F.msg = 'Нет связи с трекером.'; F.key = null; draw(); });
      };
      rd.readAsText(e.target.files[0]);
    }
  });
  var tq = null;
  document.addEventListener('input', function (e) { if (e.target && e.target.id === 'ftQ') { var v = e.target.value; clearTimeout(tq); tq = setTimeout(function () { F.q = v; F.key = null; draw(); var qi = $('ftQ'); if (qi) { qi.focus(); qi.setSelectionRange(v.length, v.length); } }, 200); } });
  setInterval(function () { if (F.data && $('ftBox') && $('ftBox').offsetParent && !F.loading) load(true); }, 60000);   // навыки обновляются в фоне
  F.ready = true;
  setTimeout(function () { if ($('ftBox') && $('ftBox').offsetParent) draw(); }, 0);
})(window.ELW);
