// Вкладка модуля «Флот» для страницы EVE Log HUD. Подключается ядром (window.ELW), см. modules/README.md.
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.addTab) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, table = ELW.table, empty = ELW.empty, icon = ELW.icon, $ = ELW.$, S = ELW.S;
  var BASE = ELW.base;
  ELW.addTab({ id: "fleet", title: "\u0424\u043b\u043e\u0442",
    css: "button.tile{border:1px solid transparent;text-align:left;font:inherit;color:inherit;cursor:pointer}\nbutton.tile:hover{border-color:var(--accent)}\n#fdlg{width:min(560px,calc(100vw - 16px))}\n.mk{display:inline-flex;gap:4px;vertical-align:middle}\n.mk button{width:22px;height:22px;border-radius:50%;border:2px solid var(--line);background:transparent;cursor:pointer;padding:0}\n.mk button[data-mark=\"good\"]{border-color:#2f8f4e} .mk button[data-mark=\"warn\"]{border-color:#d9a400} .mk button[data-mark=\"bad\"]{border-color:#d4483b}\n.mk button[data-mark=\"good\"][aria-pressed=\"true\"]{background:#2f8f4e} .mk button[data-mark=\"warn\"][aria-pressed=\"true\"]{background:#d9a400}\n.mk button[data-mark=\"bad\"][aria-pressed=\"true\"]{background:#d4483b}\n.mk button:focus-visible{outline:2px solid var(--focus);outline-offset:2px}\n.awaytag{display:inline-block;padding:1px 8px;border-radius:999px;background:#d4483b;color:#fff;font-size:12px;font-weight:600}\ntd.cmt{max-width:260px;overflow:hidden;text-overflow:ellipsis;text-align:left}\n#fdlg textarea{width:100%;min-height:90px;box-sizing:border-box;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}\n#fdlg .tw{overflow-x:visible}",
    html: "      <section class=\"panel\" id=\"fleetSource\"></section>\n      <section class=\"panel\"><h2>Мой флот <span class=\"muted small\" id=\"fleetUpdated\"></span></h2>\n        <div class=\"controls\">\n          <label class=\"small muted\">Флот\n            <select id=\"fleetSel\" aria-label=\"Какой флот показать\"><option value=\"\">Текущий</option></select></label>\n          <button type=\"button\" class=\"btn primary\" id=\"fleetTrack\">Отслеживать мой флот</button>\n          <button type=\"button\" class=\"btn hidden\" id=\"fleetStop\">Остановить отслеживание</button>\n          <button type=\"button\" class=\"btn\" id=\"fleetReload\">Обновить</button>\n          <label class=\"small muted\">Помечать, если не с боссом дольше\n            <select id=\"fleetAway\" aria-label=\"Порог отсутствия\">\n              <option value=\"3\">3 минут</option><option value=\"5\">5 минут</option><option value=\"10\">10 минут</option>\n            </select></label>\n          <span class=\"small muted\" id=\"fleetMsg\" role=\"status\" aria-live=\"polite\"></span>\n        </div>\n        <div id=\"fleetBody\"></div>\n      </section>\n    \n<dialog id=\"fdlg\" aria-labelledby=\"fdlgTitle\">\n  <div class=\"dlg-head\"><h2 id=\"fdlgTitle\">Пилоты</h2><button type=\"button\" class=\"btn\" id=\"fdlgClose\">Закрыть</button></div>\n  <div class=\"dlg-body\" id=\"fdlgBody\"></div>\n</dialog>",
    render: function () { renderFleet(); } });

  // ---------- флот: состав из Fleet Watch (Alliance Auth) через трекер ----------
  var FLEET = { data: null, at: 0, busy: false, epoch: 0, again: false, sel: '', list: [], listAt: 0 };
  // история: список своих флотов; выбранный прошлый флот показывается тем же экраном
  function loadFleetList(force) {
    if (!force && Date.now() - FLEET.listAt < 30000) return;
    FLEET.listAt = Date.now();
    api('/api/fleets').then(function (j) {
      if (j._status !== 200 || !j.ok) return;
      FLEET.list = j.fleets || [];
      var sel = $('fleetSel'), h = '<option value="">Текущий</option>';
      FLEET.list.forEach(function (x) {
        h += '<option value="' + esc(x.id) + '">' + esc(L.fmtDateTime(x.started_at) + ' · ' + (x.name || x.boss || 'флот') +
          ' · пилотов ' + x.pilots + ' · ' + (x.is_active ? 'идёт' : L.fmtDur(x.duration))) + '</option>';
      });
      sel.innerHTML = h;
      sel.value = FLEET.sel;
      if (sel.value !== FLEET.sel) { FLEET.sel = ''; sel.value = ''; }
    }, function () { });
  }
  function loadFleet(force) {
    if (FLEET.busy) { if (force) FLEET.again = true; return; }
    if (!force && Date.now() - FLEET.at < 3000) return;
    FLEET.busy = true;
    var epoch = FLEET.epoch;                               // ответ, запрошенный до сохранения отметки, уже устарел
    api('/api/fleet' + (FLEET.sel ? '?id=' + encodeURIComponent(FLEET.sel) : '')).then(function (j) {
      if (epoch !== FLEET.epoch) return;
      FLEET.data = j._status === 200 ? j : { ok: false, message: 'Трекер не умеет запрашивать флот — обновите EVE Log Watcher.' };
    }, function () { if (epoch === FLEET.epoch) FLEET.data = { ok: false, message: 'Нет связи с трекером.' }; })
      .then(function () {
        FLEET.busy = false; FLEET.at = Date.now();
        if (FLEET.again || epoch !== FLEET.epoch) { FLEET.again = false; return loadFleet(true); }
        if (S.tab === 'fleet') renderFleet();
      });
  }
  // ---------- откуда берётся флот: вход через EVE в самом приложении или Alliance Auth ----------
  var SSO = { st: null, at: 0, msg: '' };
  function loadSso(force) {
    if (!force && Date.now() - SSO.at < 4000) return;
    SSO.at = Date.now();
    api('/api/sso').then(function (j) {
      var before = SSO.st && SSO.st.source + '|' + SSO.st.logged_in;
      SSO.st = j._status === 200 && j.ok ? j : { available: false };
      renderSso();
      if (before !== SSO.st.source + '|' + SSO.st.logged_in) { FLEET.epoch++; loadFleetList(true); loadFleet(true); }
    }, function () { });
  }
  function ssoPost(path, body) {
    return api(path, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}) }).then(function (j) { SSO.msg = j.message || ''; loadSso(true); return j; },
      function () { SSO.msg = 'Нет связи с трекером.'; renderSso(); });
  }
  function renderSso() {
    var st = SSO.st, box = $('fleetSource'), h = '<h2>Аккаунт EVE</h2>';
    if (!st) { box.innerHTML = h + empty('Загрузка…'); return; }
    if (!st.available) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    var msg = SSO.msg ? '<p class="small muted" role="status">' + esc(SSO.msg) + '</p>' : '';
    if (st.logged_in) {
      h += '<p style="margin:6px 0">Подключён аккаунт: <b>' + esc(st.character) + '</b>. Флот читается напрямую из игры.</p>' +
        '<div class="controls"><button type="button" class="btn" data-sso="logout">Отключить аккаунт</button>' +
        '<span class="small muted">Состав читается, пока вы босс флота. Всё хранится только на этом компьютере.</span></div>';
    } else if (st.client_id_set) {
      h += '<div class="controls" style="margin-top:6px"><button type="button" class="btn primary" data-sso="login">Подключить аккаунт EVE</button>' +
        '<span class="small muted">Откроется страница входа CCP в браузере. Пароль вводится только там. Входите персонажем — боссом флота.</span></div>';
    } else {
      var openNow = !!(document.getElementById('ssoSetup') && document.getElementById('ssoSetup').open);
      h += '<p style="margin:6px 0">Подключение аккаунта в этой сборке ещё не настроено.</p>' +
        '<details id="ssoSetup"' + (openNow ? ' open' : '') + '><summary class="small" style="cursor:pointer">Настройка для разработчика: указать Client ID</summary>' +
        '<ol class="small" style="margin:6px 0 8px;padding-left:20px">' +
        '<li>Откройте developers.eveonline.com, войдите и нажмите «Create New Application».</li>' +
        '<li>Тип подключения — «Authentication &amp; API Access», разрешение — <span class="mono">' + esc(st.scope || '') + '</span>.</li>' +
        '<li>Callback URL — <span class="mono">' + esc(st.callback || '') + '</span></li>' +
        '<li>Скопируйте Client ID (Secret Key не нужен) и вставьте сюда.</li></ol>' +
        '<div class="controls"><label class="sr" for="ssoClient">Client ID</label><input id="ssoClient" type="text" maxlength="32" size="34" placeholder="Client ID, 32 знака" autocomplete="off">' +
        '<button type="button" class="btn primary" data-sso="client">Сохранить</button></div></details>';
    }
    var cur = document.activeElement && document.activeElement.id === 'ssoClient' ? $('ssoClient').value : null;
    if (cur !== null && !SSO.msg) return;                  // не стираем то, что человек сейчас вводит
    box.innerHTML = h + msg;
  }
  $('fleetSource').addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-sso]');
    if (!b) return;
    var what = b.getAttribute('data-sso');
    b.disabled = true;
    if (what === 'client') ssoPost('/api/sso/client', { client_id: ($('ssoClient').value || '').trim() });
    else if (what === 'login') ssoPost('/api/sso/login');
    else if (what === 'logout') ssoPost('/api/sso/logout');
  });

  function renderFleet() {
    var d = FLEET.data, body = $('fleetBody'), f = d && d.ok ? d.fleet : null;
    loadSso(false);
    $('fleetStop').classList.toggle('hidden', !(f && f.is_active !== false && !FLEET.sel));
    var past = !!(f && f.is_active === false);
    loadFleetList(false);
    if (!(past && FLEET.sel)) loadFleet(false);            // завершённый флот не меняется — не перезапрашиваем
    $('fleetTrack').classList.toggle('hidden', !!f || !!FLEET.sel || !!(d && d.reason === 'no_login'));
    if (d && !d.ok && d.reason === 'no_login' && !FLEET.sel) { $('fleetUpdated').textContent = ''; body.innerHTML = empty('Сначала подключите аккаунт EVE — блок выше.'); return; }
    $('fleetUpdated').textContent = past ? '· из истории' : f && f.polled_at ? '· состав на ' + L.fmtTimeS(f.polled_at) : '';
    if (!d) { body.innerHTML = empty('Загрузка…'); return; }
    if (!d.ok) { body.innerHTML = empty(d.message || 'Нет данных о флоте.'); return; }
    if (!f && FLEET.sel) { body.innerHTML = empty('Этот флот не найден или вам недоступен.'); return; }
    if (!f) {
      body.innerHTML = empty('Вы не во флоте, который отслеживается.') +
        '<p class="small muted">Создайте флот в игре (или станьте его боссом) и нажмите «Отслеживать мой флот». ' +
        'Состав флота игра отдаёт только боссу, поэтому кнопка сработает, если босс — ваш персонаж. ' +
        'Когда отслеживание включено, окно «Флот» в оверлее появится само. ' +
        'Прошлые флоты — в списке «Флот» вверху.</p>';
      return;
    }
    var chips = function (list, label) {                   // плитка — кнопка: открывает список пилотов
      return '<div class="tiles" style="margin:10px 0">' + list.map(function (x) {
        return '<button type="button" class="tile' + (label ? '' : ' ore') + '" data-pick="' + (label ? 'system' : 'ship') + '" data-name="' + esc(x.name) + '"' +
          ' title="Показать пилотов"><div class="k">' + esc(x.name) + '</div><div class="v">' + esc(x.n) + '</div>' +
          (label && typeof x.sec === 'number' ? '<div class="s">безопасность ' + esc(x.sec.toFixed(1)) + '</div>' : '') + '</button>';
      }).join('') + '</div>';
    };
    var h = '<p style="margin:10px 0 0"><b>' + esc(f.name || 'Флот') + '</b> · пилотов: <b>' + esc(f.count) + '</b>' +
      (f.boss ? ' · босс <b>' + esc(f.boss) + '</b>' + (f.boss_system ? ' в ' + esc(f.boss_system) : '') : '') + '</p>';
    if (past) {
      h = '<p style="margin:10px 0 0"><b>' + esc(f.name || 'Флот') + '</b> · завершён · ' + esc(L.fmtDateTime(f.started_at)) + ' — ' +
        esc(f.ended_at ? L.fmtDateTime(f.ended_at) : '?') + ' · длился <b>' + esc(L.fmtDur(f.duration)) + '</b>' +
        (f.boss ? ' · босс <b>' + esc(f.boss) + '</b>' : '') + '</p>' +
        (f.end_reason ? '<p class="small muted" style="margin:4px 0 0">Почему закончился: ' + esc(f.end_reason) + '</p>' : '') +
        '<p class="small muted" style="margin:4px 0 0">Корабли и системы — на момент последнего опроса.</p>';
    }
    h += '<h3 class="small muted" style="margin:14px 0 0">Корабли</h3>' + chips(f.ships || [], false);
    h += '<h3 class="small muted" style="margin:14px 0 0">Системы</h3>' + chips(f.systems || [], true);
    var lim = fleetAwayMin() * 60, manage = !!f.can_manage;
    var pilotName = function (r) { return (r.boss ? '★ ' : '') + (r.me ? '<b>' + esc(r.name) + '</b>' : esc(r.name)); };
    var awayCell = function (r) {                          // сейчас не с боссом дольше порога — красная метка
      var past = (r.away_eps || []).filter(function (x) { return x >= lim; });
      var txt = r.away_now >= lim ? '<span class="awaytag">не с боссом ' + esc(L.fmtDur(r.away_now)) + '</span>' : '';
      var n = past.length - (r.away_now >= lim ? 1 : 0);
      if (n > 0) txt += (txt ? ' ' : '') + '<span class="muted small">раньше: ' + n + ' раз, до ' + esc(L.fmtDur(Math.max.apply(null, past))) + '</span>';
      return txt || '<span class="muted">—</span>';
    };
    var markCell = function (r) {
      var b = function (m, title) { return '<button type="button" data-mark="' + m + '" data-id="' + esc(r.id) + '" aria-pressed="' + (r.mark === m) + '" title="' + title + '" aria-label="' + title + ': ' + esc(r.name) + '"></button>'; };
      return '<span class="mk">' + b('good', 'Молодец') + b('warn', 'Внимание') + b('bad', 'Накосячил') + '</span>';
    };
    var cmtCell = function (r) {
      return '<button type="button" class="btn" data-comment="' + esc(r.id) + '" style="min-height:24px;padding:2px 8px" title="Комментарий">✎</button> ' + esc(r.comment || '');
    };
    var extra = manage ? [{ k: 'mark', t: 'Отметка', l: 1, f: markCell }, { k: 'comment', t: 'Комментарий', l: 1, cls: 'cmt', f: cmtCell }] : [];
    var flagged = (f.pilots || []).filter(function (p) { return p.away_now >= lim; });
    if (flagged.length) {
      h += '<h3 class="small muted" style="margin:14px 0 6px">Не с боссом флота дольше ' + fleetAwayMin() + ' минут · ' + flagged.length + '</h3>' +
        table('fleetAwayNow', flagged.map(function (p) { return Object.assign({}, p); }), [
          { k: 'name', t: 'Пилот', l: 1, f: pilotName },
          { k: 'system', t: 'Где он', l: 1, f: function (r) { return esc(r.system) + (r.docked ? ' (док)' : ''); } },
          { k: 'ship', t: 'Корабль', l: 1, f: function (r) { return esc(r.ship); } },
          { k: 'away_now', t: 'Сколько', f: function (r) { return '<span class="awaytag">' + esc(L.fmtDur(r.away_now)) + '</span>'; } }
        ], { sort: { k: 'away_now', d: -1 } });
    }
    h += '<h3 class="small muted" style="margin:14px 0 6px">' + (past ? 'Были до конца' : 'Во флоте') + ' · ' + (f.pilots || []).length + '</h3>';
    h += table('fleetPilots', (f.pilots || []).map(function (p) {
      return Object.assign({}, p, { where: p.docked ? 'в доке' : 'в космосе', mark: p.mark || '', comment: p.comment || '' });
    }), [
      { k: 'name', t: 'Пилот', l: 1, f: pilotName },
      { k: 'ship', t: 'Корабль', l: 1, f: function (r) { return esc(r.ship); } },
      { k: 'system', t: 'Система', l: 1, f: function (r) { return esc(r.system); } },
      { k: 'where', t: 'Где', l: 1, f: function (r) { return esc(r.where); } },
      { k: 'joined', t: 'Зашёл', f: function (r) { return esc(L.fmtTime(r.joined)); } },
      { k: 'seconds', t: 'Во флоте', f: function (r) { return esc(L.fmtDur(r.seconds)) + (r.rejoins ? ' <span class="muted small">(выходил ' + r.rejoins + ')</span>' : ''); } },
      { k: 'away_now', t: 'Не с боссом', l: 1, f: awayCell }
    ].concat(extra), { sort: { k: 'ship', d: 1 } });
    if ((f.left || []).length) {
      h += '<h3 class="small muted" style="margin:18px 0 6px">' + (past ? 'Вышли раньше' : 'Вышли из флота') + ' · ' + f.left.length + '</h3>';
      h += table('fleetLeft', f.left.map(function (p) { return Object.assign({}, p, { mark: p.mark || '', comment: p.comment || '' }); }), [
        { k: 'name', t: 'Пилот', l: 1, f: pilotName },
        { k: 'joined', t: 'Зашёл', f: function (r) { return esc(L.fmtTime(r.joined)); } },
        { k: 'left', t: 'Вышел', f: function (r) { return esc(L.fmtTime(r.left)); } },
        { k: 'seconds', t: 'Был во флоте', f: function (r) { return esc(L.fmtDur(r.seconds)); } },
        { k: 'away_eps', t: 'Не с боссом', l: 1, f: awayCell }
      ].concat(extra), { sort: { k: 'left', d: -1 } });
    }
    body.innerHTML = h;
    renderFleetPick();
  }
  function fleetAwayMin() { var v = parseInt($('fleetAway').value, 10); return v === 3 || v === 10 ? v : 5; }
  try { $('fleetAway').value = localStorage.getItem('elw.fleetAway') || '5'; } catch (e) { $('fleetAway').value = '5'; }
  $('fleetAway').addEventListener('change', function () {
    try { localStorage.setItem('elw.fleetAway', this.value); } catch (e) { }
    renderFleet();
  });
  function fleetPilot(id) {
    var f = FLEET.data && FLEET.data.ok ? FLEET.data.fleet : null;
    return ((f && f.pilots) || []).concat((f && f.left) || []).filter(function (p) { return String(p.id) === String(id); })[0] || null;
  }
  function saveMark(id, mark, comment) {
    $('fleetMsg').textContent = 'Сохраняю…';
    FLEET.epoch++;
    return api('/api/fleet/mark', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: id, mark: mark, comment: comment, fleet_id: FLEET.sel ? parseInt(FLEET.sel, 10) : null }) }).then(function (j) {
      $('fleetMsg').textContent = j.ok ? '' : (j.message || 'Не удалось сохранить.');
      FLEET.epoch++;
      loadFleet(true);
      return j;
    }, function () { $('fleetMsg').textContent = 'Нет связи с трекером.'; });
  }
  // окно «пилоты на этом корабле / в этой системе»; пока открыто — обновляется вместе с составом
  var fdlg = $('fdlg');
  function renderFleetPick() {
    var pk = FLEET.pick, f = FLEET.data && FLEET.data.ok ? FLEET.data.fleet : null;
    if (!pk || !fdlg.open) return;
    var byShip = pk.kind === 'ship';
    var list = ((f && f.pilots) || []).filter(function (p) { return (byShip ? p.ship : p.system) === pk.name; });
    $('fdlgTitle').textContent = (byShip ? 'На корабле ' : 'В системе ') + pk.name + ' · ' + list.length;
    if (!list.length) { $('fdlgBody').innerHTML = empty(byShip ? 'Сейчас на этом корабле никого нет.' : 'Сейчас в этой системе никого нет.'); return; }
    $('fdlgBody').innerHTML = table('fleetPick', list.map(function (p) {
      return { name: p.name, other: byShip ? p.system : p.ship, where: p.docked ? 'в доке' : 'в космосе', boss: p.boss, me: p.me };
    }), [
      { k: 'name', t: 'Пилот', l: 1, f: function (r) { return (r.boss ? '★ ' : '') + (r.me ? '<b>' + esc(r.name) + '</b>' : esc(r.name)); } },
      { k: 'other', t: byShip ? 'Система' : 'Корабль', l: 1, f: function (r) { return esc(r.other); } },
      { k: 'where', t: 'Где', l: 1, f: function (r) { return esc(r.where); } }
    ], { sort: { k: 'other', d: 1 } });
  }
  $('fleetBody').addEventListener('click', function (e) {
    var mk = e.target.closest && e.target.closest('button[data-mark]');
    if (mk) {                                              // повторное нажатие на ту же отметку снимает её
      var p = fleetPilot(mk.getAttribute('data-id'));
      if (!p) return;
      var next = p.mark === mk.getAttribute('data-mark') ? '' : mk.getAttribute('data-mark');
      p.mark = next;
      mk.parentNode.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', String(x.getAttribute('data-mark') === next)); });
      saveMark(p.id, next, p.comment || '');
      return;
    }
    var cm = e.target.closest && e.target.closest('button[data-comment]');
    if (cm) {
      var q = fleetPilot(cm.getAttribute('data-comment'));
      if (!q) return;
      FLEET.pick = null;
      $('fdlgTitle').textContent = 'Комментарий · ' + q.name;
      $('fdlgBody').innerHTML = '<label class="sr" for="fleetCmt">Комментарий</label><textarea id="fleetCmt" maxlength="500"></textarea>' +
        '<div class="controls" style="margin-top:8px"><button type="button" class="btn primary" id="fleetCmtSave">Сохранить</button>' +
        '<span class="small muted">Видят только те, кто ведёт флот.</span></div>';
      $('fleetCmt').value = q.comment || '';
      if (typeof fdlg.showModal === 'function') fdlg.showModal(); else fdlg.setAttribute('open', '');
      $('fleetCmt').focus();
      $('fleetCmtSave').addEventListener('click', function () {
        var text = $('fleetCmt').value.trim();
        q.comment = text;
        saveMark(q.id, q.mark || '', text);
        fdlg.close();
      });
      return;
    }
    var b = e.target.closest && e.target.closest('button[data-pick]');
    if (!b) return;
    FLEET.pick = { kind: b.getAttribute('data-pick'), name: b.getAttribute('data-name') };
    if (typeof fdlg.showModal === 'function') fdlg.showModal(); else fdlg.setAttribute('open', '');
    renderFleetPick();
    $('fdlgClose').focus();
  });
  $('fdlgClose').addEventListener('click', function () { fdlg.close(); });
  fdlg.addEventListener('click', function (e) { if (e.target === fdlg) fdlg.close(); });
  fdlg.addEventListener('close', function () { FLEET.pick = null; });
  $('fleetReload').addEventListener('click', function () { $('fleetMsg').textContent = ''; loadFleetList(true); loadFleet(true); });
  $('fleetStop').addEventListener('click', function () {
    var btn = this;
    btn.disabled = true;
    api('/api/fleet/stop', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } }).then(function (j) {
      $('fleetMsg').textContent = j.message || '';
      btn.disabled = false; FLEET.epoch++;
      loadFleetList(true); loadFleet(true);
    }, function () { btn.disabled = false; });
  });
  $('fleetSel').addEventListener('change', function () {
    FLEET.sel = this.value; FLEET.data = null; FLEET.epoch++; FLEET.pick = null;
    $('fleetMsg').textContent = '';
    renderFleet();
    loadFleet(true);
  });
  $('fleetTrack').addEventListener('click', function () {
    var btn = this, msg = $('fleetMsg');
    btn.disabled = true; msg.textContent = 'Спрашиваю Alliance Auth…';
    api('/api/fleet/track', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } }).then(function (j) {
      msg.textContent = j.message || (j.ok ? 'Отслеживание включено.' : 'Не получилось.');
      btn.disabled = false;
      loadFleetList(true);
      loadFleet(true);
    }, function () { msg.textContent = 'Нет связи с трекером.'; btn.disabled = false; });
  });
  setInterval(function () {
    if (S.tab !== 'fleet' || document.hidden) return;
    loadSso(false);
    var f = FLEET.data && FLEET.data.ok ? FLEET.data.fleet : null;
    loadFleetList(false);
    if (!(FLEET.sel && f && f.is_active === false)) loadFleet(false);
  }, 3000);
})(window.ELW);
