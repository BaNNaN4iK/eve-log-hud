// Тесты чистых функций dashboard.html в Node (без браузера).
// Запуск: node tests/dashboard_logic.test.js   (часовой пояс задаётся переменной TZ)
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
const start = html.indexOf('/* LOGIC-START'), end = html.indexOf('/* LOGIC-END */');
assert(start > 0 && end > start, 'блок LOGIC не найден');
const ctx = { module: { exports: {} } };
vm.createContext(ctx);
vm.runInContext(html.slice(start, end), ctx);
const L = ctx.module.exports;
// объекты из другого контекста vm: сравниваем через JSON
const plain = x => JSON.parse(JSON.stringify(x));
const eq = (a, b, m) => assert.deepStrictEqual(plain(a), plain(b), m);

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; } catch (e) { console.error('FAIL', name, '\n', e && e.stack || e); process.exitCode = 1; }
}
const NB = ' ';
const ts = (y, m, d, h = 0, mi = 0, s = 0) => new Date(y, m - 1, d, h, mi, s).getTime() / 1000;

// --- тестовые сессии: 3 дня, 2 персонажа ---
function mk(t0, who, o) {
  return Object.assign({ id: who + '|' + t0, who, t0, t1: t0 + (o.dur || 0), dur: o.dur || 0, out: 0, in: 0, bounty: 0, ore_total: 0, ore: {},
    weapons: {}, targets: {}, attackers: {}, in_weapons: {}, systems: {}, avg_dps: 0, peak_dps: 0 }, o);
}
const now = ts(2026, 10, 9, 15, 0);
const S = [
  mk(ts(2026, 10, 9, 10, 5), 'A', { dur: 600, out: 1000, avg_dps: 10, peak_dps: 30, weapons: { Gun: { dmg: 1000, hits: 10, miss: 2, max: 150, active: 100, peak: 30, q: { 'Попал': 8, 'Пробил': 2 } } }, systems: { Jita: { out: 1000, in: 0, bounty: 0, ore: 0, n: 12, t0: 0, t1: 600 } } }),
  mk(ts(2026, 10, 9, 13, 59), 'B', { dur: 120, ore_total: 500, ore: { Veldspar: 400, Omber: 100 } }),
  mk(ts(2026, 10, 8, 23, 59), 'A', { dur: 60, bounty: 250000, in: 77 }),
  mk(ts(2026, 10, 1, 0, 0), 'A', { dur: 30, out: 5, avg_dps: 5, weapons: { Gun: { dmg: 5, hits: 1, miss: 0, max: 5, active: 1, peak: 0.2, q: {} } } }),
  mk(ts(2026, 9, 10, 0, 0), 'B', { dur: 30, out: 9 }),   // ровно 30-й день назад — входит в d30
  mk(ts(2026, 9, 9, 23, 59), 'B', { dur: 30, out: 11 }), // 31-й день — не входит в d30
];

test('formatting', () => {
  assert.strictEqual(L.fmtInt(1234567), '1' + NB + '234' + NB + '567');
  assert.strictEqual(L.fmtInt(-5), '−5');
  assert.strictEqual(L.fmtInt(null), '—');
  assert.strictEqual(L.fmtNum(1.5, 1), '1,5');
  assert.strictEqual(L.fmtNum(2.0, 2), '2');
  assert.strictEqual(L.fmtNum(-0.04, 1), '0');
  assert.strictEqual(L.fmtCompact(7840000), '7,84' + NB + 'млн');
  assert.strictEqual(L.fmtCompact(1.31e9), '1,31' + NB + 'млрд');
  assert.strictEqual(L.fmtCompact(397800), '397,8' + NB + 'тыс.');
  assert.strictEqual(L.fmtCompact(9999), '9' + NB + '999');
  assert.strictEqual(L.fmtIsk(1500), '1' + NB + '500' + NB + 'ISK');
  assert.strictEqual(L.fmtDur(0), '0' + NB + 'с');
  assert.strictEqual(L.fmtDur(125), '2' + NB + 'мин 5' + NB + 'с');
  assert.strictEqual(L.fmtDur(3600 * 13 + 56 * 60), '13' + NB + 'ч 56' + NB + 'мин');
  assert.strictEqual(L.fmtDur(3600 + 5 * 60), '1' + NB + 'ч 05' + NB + 'мин');
  assert.strictEqual(L.fmtPct(0.5), '50%');
  assert.strictEqual(L.fmtTime(ts(2026, 10, 9, 7, 3)), '07:03');
  assert.strictEqual(L.fmtDate(ts(2026, 1, 2)), '02.01');
});

test('periodRange', () => {
  const t = L.periodRange('today', now);
  assert.strictEqual(t.from, ts(2026, 10, 9)); assert.strictEqual(t.to, ts(2026, 10, 10)); assert.strictEqual(t.unit, 'hour');
  const w = L.periodRange('d7', now);
  assert.strictEqual(w.from, ts(2026, 10, 3)); assert.strictEqual(w.unit, 'day');
  const m = L.periodRange('d30', now);
  assert.strictEqual(m.from, ts(2026, 9, 10));
  const c = L.periodRange('custom', now, { from: '2026-10-05', to: '2026-10-01' });   // перепутанные даты
  assert.strictEqual(c.from, ts(2026, 10, 1)); assert.strictEqual(c.to, ts(2026, 10, 6));
  const one = L.periodRange('custom', now, { from: '2026-10-05', to: '2026-10-05' });
  assert.strictEqual(one.unit, 'hour');
  const all = L.periodRange('all', now, { minTs: ts(2025, 1, 15, 12) });
  assert.strictEqual(all.from, ts(2025, 1, 15)); assert.strictEqual(all.unit, 'week');
  assert.strictEqual(L.periodRange('all', now, { minTs: ts(2020, 1, 1) }).unit, 'month');
});

test('buckets include all days, zero days, and sums match records', () => {
  for (const key of ['today', 'd7', 'd30', 'all']) {
    const r = L.periodRange(key, now, { minTs: Math.min.apply(null, S.map(s => s.t0)) });
    const list = L.filterSessions(S, { from: r.from, to: r.to });
    for (const metric of ['out', 'in', 'bounty', 'ore', 'minutes']) {
      const b = L.buckets(list, r, metric);
      const total = b.reduce((a, x) => a + x.value, 0);
      const expect = list.reduce((a, s) => a + L.metricValue(s, metric), 0);
      assert(Math.abs(total - expect) < 1e-9, key + '/' + metric + ': ' + total + ' != ' + expect);
      const T = L.sumSessions(list);
      if (metric !== 'minutes') {
        const k = metric === 'ore' ? 'ore_total' : metric;
        assert.strictEqual(T[k], expect);
      }
    }
    const b = L.buckets(list, r, 'out');
    if (key === 'today') assert.strictEqual(b.length, 24);
    if (key === 'd7') assert.strictEqual(b.length, 7);
    if (key === 'd30') assert.strictEqual(b.length, 30);
    for (let i = 1; i < b.length; i++) assert(b[i].start > b[i - 1].start);
  }
  const r30 = L.periodRange('d30', now);
  const l30 = L.filterSessions(S, { from: r30.from, to: r30.to });
  assert.strictEqual(l30.length, 5);   // 31-й день не входит
  const b30 = L.buckets(l30, r30, 'out');
  assert.strictEqual(b30.filter(x => x.value === 0).length, 30 - 3);   // нулевые дни тоже есть
  assert.strictEqual(b30[0].value, 9);
  assert.strictEqual(b30[29].value, 1000);
  const today = L.buckets(L.filterSessions(S, L.periodRange('today', now)), L.periodRange('today', now), 'out');
  assert.strictEqual(today[10].value, 1000); assert.strictEqual(today[10].label, '10');
});

test('filter by character', () => {
  const r = L.periodRange('d30', now);
  const a = L.filterSessions(S, { from: r.from, to: r.to, who: 'A' });
  const bb = L.filterSessions(S, { from: r.from, to: r.to, who: 'B' });
  const all = L.filterSessions(S, { from: r.from, to: r.to });
  assert.strictEqual(a.length + bb.length, all.length);
  assert.strictEqual(L.sumSessions(a).out + L.sumSessions(bb).out, L.sumSessions(all).out);
});

test('sumSessions merges weapons, ore, systems', () => {
  const T = L.sumSessions(S);
  assert.strictEqual(T.n, S.length);
  assert.strictEqual(T.out, 1000 + 5 + 9 + 11);
  assert.strictEqual(T.weapons.Gun.dmg, 1005);
  assert.strictEqual(T.weapons.Gun.active, 101);
  assert(Math.abs(T.weapons.Gun.dps - 1005 / 101) < 1e-9);
  assert.strictEqual(T.weapons.Gun.hit_rate, 11 / 13);
  assert.strictEqual(T.weapons.Gun.peak, 30);
  assert.strictEqual(T.weapons.Gun.q['Попал'], 8);
  eq(T.ore, { Veldspar: 400, Omber: 100 });
  assert.strictEqual(T.systems.Jita.out, 1000);
  assert.strictEqual(T.who.A, 3);
  assert.strictEqual(T.peak_dps, 30);
  // средний DPS за период = урон / сумма времени стрельбы
  assert(Math.abs(T.avg_dps - T.out / (1000 / 10 + 5 / 5)) < 1e-9);
});

test('ore value and volume via ctx', () => {
  const ctx = { volumeOf: n => ({ Veldspar: 0.1, Omber: 0.6 })[n] ?? null, priceOf: n => ({ Veldspar: 20 })[n] ?? null };
  const T = L.sumSessions(S);
  assert(Math.abs(L.oreSum(T.ore, ctx, 'm3') - (40 + 60)) < 1e-9);
  assert.strictEqual(L.oreSum(T.ore, ctx, 'isk'), 8000);   // Omber без цены не считается
  const r = L.periodRange('d30', now);
  const b = L.buckets(L.filterSessions(S, r), r, 'ore_m3', ctx);
  assert(Math.abs(b.reduce((a, x) => a + x.value, 0) - 100) < 1e-9);
});

test('niceScale', () => {
  const cases = [[0, 1], [7, 8], [10, 10], [11, 15], [97.9, 100], [123456, 150000], [0.3, 0.3], [2600, 3000]];
  for (const [v, max] of cases) {
    const s = L.niceScale(v);
    assert(Math.abs(s.max - max) < 1e-9, v + ' -> ' + s.max);
    assert(s.max >= v);
    const steps = s.max / s.step;
    assert(Math.abs(steps - Math.round(steps)) < 1e-9 && steps >= 2 && steps <= 6, v + ' steps ' + steps);
  }
});

test('sellToBook', () => {
  const book = [[100, 10], [90, 5, 1], [80, 1000, 50]];
  eq(L.sellToBook(book, 12), { isk: 1000 + 180, sold: 12, left: 0 });
  eq(L.sellToBook(book, 20), { isk: 1000 + 450, sold: 15, left: 5 });   // 5 < min_volume 50
  const r = L.sellToBook(book, 2000);
  assert.strictEqual(r.sold, 1015); assert.strictEqual(r.left, 985);
  eq(L.sellToBook([], 5), { isk: 0, sold: 0, left: 5 });
});

test('series helpers', () => {
  eq(L.denseSeries([[0, 5], [3, 7], [9, 1]], 5), [5, 0, 0, 7, 0]);
  const rec = { series: { t0: 1000, step: 10, out: [[0, 100], [5, 300], [6, 600]] } };
  assert.strictEqual(L.recentDps(rec, 1069, 30), (300 + 600) / 30);
});

test('security status', () => {
  assert.strictEqual(L.secRound(0.9459), 0.9);
  assert.strictEqual(L.secRound(0.04), 0.1);
  assert.strictEqual(L.secClass(0.5), 'hi');
  assert.strictEqual(L.secClass(0.45), 'hi');
  assert.strictEqual(L.secClass(0.3), 'lo');
  assert.strictEqual(L.secClass(-0.2), 'null');
});

test('sortBy and entries', () => {
  const rows = [{ name: 'б', v: 2 }, { name: 'а', v: null }, { name: 'в', v: 5 }];
  eq(L.sortBy(rows, 'v', -1).map(r => r.name), ['в', 'б', 'а']);
  eq(L.sortBy(rows, 'name', 1).map(r => r.name), ['а', 'б', 'в']);
  eq(L.entries({ x: 1, y: 3 }).map(e => e.name), ['y', 'x']);
});

test('DST: day buckets stay on local midnight', () => {
  // при переходе на летнее/зимнее время (если он есть в TZ) столбцы остаются на полуночи
  const r = { from: ts(2026, 3, 1), to: ts(2026, 11, 30), unit: 'day' };
  for (const t of L.bucketStarts(r)) { const d = new Date(t * 1000); assert.strictEqual(d.getHours() + d.getMinutes(), 0); }
  const today = L.periodRange('today', ts(2026, 3, 29, 12));
  const n = L.bucketStarts(today).length;
  assert(n >= 23 && n <= 25);
});

console.log(`dashboard logic: ${passed} tests passed (TZ=${process.env.TZ || 'system'})`);
