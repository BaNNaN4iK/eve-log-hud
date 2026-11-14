// Модуль «ESS»: выплаты ESS и реальные выплаты баунти из журнала кошелька — плитки на «Обзоре» и блок во вкладке «Баунти».
(function (ELW) {
  'use strict';
  if (!ELW || !ELW.hook) return;
  var api = ELW.api, esc = ELW.esc, L = ELW.L, tile = ELW.tile;
  var POST = { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' };
  var E = { status: null, data: {}, wait: {}, msg: '', statusAt: 0, share: 60, pend: null, pendWho: null, pendAt: 0 };
  try { var sv = parseFloat(localStorage.getItem('elw.ess.share')); if (sv >= 0 && sv <= 100) E.share = sv; } catch (e) { }
  // ожидаемая выплата ESS: доля от баунти по логам (по умолчанию 60%)
  function expected(T) { return (T.bounty || 0) * E.share / 100; }
  function pctTxt() { return String(E.share).replace('.', ',') + '%'; }
  // баунти с последней выплаты ESS (по подключённым персонажам) — раз в минуту
  function pending() {
    var who = ELW.S.who || '';
    if (E.pendWho !== who || Date.now() - E.pendAt > 60000) {
      E.pendAt = Date.now(); E.pendWho = who;
      api('/api/ess/pending?who=' + encodeURIComponent(who)).then(function (j) {
        if (!j.ok) return;
        var was = JSON.stringify(E.pend); E.pend = j.chars;
        if (was !== JSON.stringify(E.pend)) ELW.render();
      }, function () { });
    }
    return E.pend;
  }
  function expTile(T, d) {
    var pc = pending(), known = (pc || []).filter(function (c) { return c.bounty !== null; });
    if (known.length) {                                         // с последней выплаты: выплата пришла — снова с нуля
      var b = known.reduce(function (a, c) { return a + c.bounty; }, 0);
      var last = Math.max.apply(null, known.map(function (c) { return c.last_t; }));
      var who = known.length === 1 ? '' : ' (' + known.length + ' персонажа)';
      var lastAmt = known.length === 1 ? ' на ' + L.fmtIsk(known[0].last_amount) : '';
      return tile('Ожидаемая ESS', L.fmtIsk(b * E.share / 100),
        pctTxt() + ' от баунти ' + L.fmtIsk(b) + ' с последней выплаты · ' + esc(L.fmtDateTime(last)) + lastAmt + who, 'bounty');
    }
    var ex = expected(T);
    var sub = pctTxt() + ' от баунти · с баунти ' + L.fmtIsk((T.bounty || 0) + ex);
    if (d) sub = pctTxt() + ' от баунти · пришло ' + L.fmtIsk(d.ess) + (ex ? ' (' + Math.round(d.ess * 100 / ex) + '%)' : '');
    return tile('Ожидаемая ESS', L.fmtIsk(ex), sub, 'bounty');
  }

  function key(sel) { return sel.range.from + '|' + sel.range.to + '|' + (ELW.S.who || ''); }
  function load(sel) {
    var k = key(sel);
    if (E.data[k] || E.wait[k]) return E.data[k] || null;
    E.wait[k] = true;
    api('/api/ess?from=' + sel.range.from + '&to=' + sel.range.to + '&who=' + encodeURIComponent(ELW.S.who || '')).then(function (j) {
      delete E.wait[k];
      if (j.ok) { E.data[k] = j; ELW.render(); }
    }, function () { delete E.wait[k]; });
    return null;
  }
  function status() {
    if (Date.now() - E.statusAt > 60000) {
      E.statusAt = Date.now();
      api('/api/ess/status').then(function (j) { if (j.ok) { var was = JSON.stringify(E.status); E.status = j; if (was !== JSON.stringify(j)) { E.data = {}; ELW.render(); } } }, function () { });
    }
    return E.status;
  }
  function act(path, body, text) {
    E.msg = text || '';
    return api(path, { method: 'POST', headers: POST, body: JSON.stringify(body || {}) }).then(function (j) {
      E.msg = j.message || ''; E.statusAt = 0; E.data = {}; ELW.render();
      if (path === '/api/ess/sync' || path === '/api/eve/login') setTimeout(function () { E.statusAt = 0; E.data = {}; ELW.render(); }, path === '/api/ess/sync' ? 8000 : 30000);
    }, function () { E.msg = 'Нет связи с трекером.'; ELW.render(); });
  }

  // «Обзор»: ожидаемая ESS (доля от баунти по логам), ESS за период и итого с ней
  ELW.hook('overview', function (sel, T) {
    var st = status();
    var exp = T.bounty ? expTile(T, null) : '';
    if (!st || !st.chars.length) return { tiles: exp };
    var d = load(sel);
    return { tiles: expTile(T, d) + tile('Выплаты ESS', d ? L.fmtIsk(d.ess) : '…', d ? 'баунти с ESS ' + L.fmtIsk((T.bounty || 0) + d.ess) : 'загружаю', 'bounty') };
  });
  function shareBox() {
    return '<label class="small muted" title="Какую долю от баунти по логам считать ожидаемой выплатой ESS">Ожидаемая ESS — доля от баунти ' +
      '<input id="essShare" value="' + esc(String(E.share).replace('.', ',')) + '" inputmode="decimal" style="width:4em;text-align:right;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:2px 6px"> %</label>';
  }
  document.addEventListener('change', function (e) {
    if (!e.target || e.target.id !== 'essShare') return;
    var v = parseFloat(String(e.target.value).replace(',', '.'));
    if (!(v >= 0 && v <= 100)) { e.target.value = String(E.share).replace('.', ','); return; }
    E.share = v;
    try { localStorage.setItem('elw.ess.share', String(v)); } catch (err) { }
    ELW.render();
  });

  // «Баунти»: плитки, сверка с CCP, персонажи, список выплат
  ELW.hook('bounty', function (sel, T) {
    var st = status();
    var head = '<section class="panel"><h2>Выплаты ESS и кошелёк <span class="small muted">из журнала кошелька в игре (ESI)</span></h2>' +
      '<div class="controls" style="margin-bottom:6px">' + shareBox() + '</div>';
    if (!st) return { tiles: expTile(T, null) };
    if (!st.chars.length) {
      return { tiles: expTile(T, null), html: head + '<p class="small" style="margin-top:0">В системах с ESS часть баунти уходит в банк ESS и приходит отдельной выплатой раз в ~3 часа. ' +
        'В логи игры она не попадает — поэтому «Баунти» выше без неё. Подключите персонажа, и приложение будет брать выплаты ESS и реальные выплаты баунти из журнала кошелька.</p>' +
        (st.client_id_set ? '<div class="controls"><button type="button" class="btn primary" data-ess="login">Подключить персонажа (вход через EVE)</button>' +
          '<span class="small muted">Общий вход «данные персонажа» (кошелёк, склад, добыча, киллмейлы) — отдельное приложение EVE, не флотское. Персонажи — и в «Настройках».</span></div>' :
          '<p class="small">Сначала впишите Client ID приложения EVE «данные персонажа»: <a href="#" data-goto="modules">«Настройки» → «Персонажи EVE»</a>.</p>') +
        (E.msg ? '<div class="small" role="status">' + esc(E.msg) + '</div>' : '') + '</section>' };
    }
    var d = load(sel), tiles = expTile(T, null);
    if (d) {
      var diff = d.bounty_paid - (T.bounty || 0);
      tiles = expTile(T, d) + tile('Выплаты ESS', L.fmtIsk(d.ess), 'выплат: ' + L.fmtInt(d.count), 'bounty') +
        tile('Баунти с ESS', L.fmtIsk((T.bounty || 0) + d.ess), 'по логам + ESS', 'bounty') +
        tile('Выплачено CCP', d.bounty_paid ? L.fmtIsk(d.bounty_paid) : '—', d.bounty_paid ? (Math.abs(diff) < 1 ? 'совпадает с логами' : (diff > 0 ? 'больше логов на ' : 'меньше логов на ') + L.fmtIsk(Math.abs(diff))) : 'баунти из кошелька за период');
    }
    var h = head + '<div class="controls">' + st.chars.map(function (c) {
      return '<span class="small" style="background:var(--panel2);border-radius:7px;padding:4px 8px">' + esc(c.name) +
        ' <span class="muted">' + (c.error ? '<span style="color:var(--bad)">' + esc(c.error) + '</span>' : c.synced ? 'обновлено ' + esc(L.fmtDateTime(c.synced)) : 'ещё не обновлялось') + '</span>' +
        ' <button type="button" class="btn" data-ess="logout" data-id="' + c.id + '" title="Отключить персонажа" style="padding:0 6px">×</button></span>';
    }).join('') + '<button type="button" class="btn" data-ess="login">+ персонаж</button><button type="button" class="btn" data-ess="sync"' + (st.busy ? ' disabled' : '') + '>' + (st.busy ? 'Обновляю…' : 'Обновить') + '</button></div>' +
      (E.msg ? '<div class="small" role="status" style="margin-bottom:6px">' + esc(E.msg) + '</div>' : '') +
      '<div class="small muted" style="margin-bottom:8px">«Баунти» выше — из логов (ваша доля сразу за каждого NPC). ESS — доля из банка ESS, приходит раз в ~3 часа; если банк украли, выплаты не будет. «Ожидаемая ESS» — сколько должно прийти со следующей выплатой: заданная доля от баунти по логам с последней выплаты ESS (пришла выплата — считается с нуля; журнал кошелька обновляется раз в ~30 минут). Без подключённого кошелька — доля от баунти за выбранный период. ' +
      '«Выплачено CCP» — что реально пришло на кошелёк как баунти (раз в 20 минут): так видно, сходится ли лог с игрой. Журнал кошелька ESI отдаёт за 30 дней — приложение копит историю у себя.</div>';
    if (!d) h += '<p class="small muted">Загружаю выплаты…</p>';
    else if (!d.payments.length) h += '<p class="small muted">Выплат ESS за этот период нет' + (ELW.S.who ? ' у ' + esc(ELW.S.who) : '') + '.</p>';
    else h += ELW.table('essPay', d.payments, [
      { k: 't', t: 'Когда', l: 1, f: function (r) { return esc(L.fmtDateTime(r.t)); } },
      { k: 'who', t: 'Персонаж', l: 1, f: function (r) { return esc(r.who || ''); } },
      { k: 'system', t: 'Система', l: 1, f: function (r) { return esc(r.system || '—'); } },
      { k: 'amount', t: 'Выплата ESS', f: function (r) { return L.fmtIsk(r.amount); } }
    ], { sort: { k: 't', d: -1 }, limit: 50 });
    return { tiles: tiles, html: h + '</section>' };
  });

  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-ess]');
    if (!b) return;
    var a = b.getAttribute('data-ess');
    if (a === 'login') act('/api/eve/login', {}, 'Открываю вход EVE…');
    else if (a === 'sync') act('/api/ess/sync', {}, 'Обновляю…');
    else if (a === 'logout' && confirm('Отключить персонажа? Его токен «данные персонажа» будет удалён (кошелёк, склад, добыча). Сохранённые выплаты останутся.')) act('/api/eve/logout', { id: +b.getAttribute('data-id') });
  });
})(window.ELW);
