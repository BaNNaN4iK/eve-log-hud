# -*- coding: utf-8 -*-
"""
Независимая сверка на реальных логах (не использует парсер приложения).

  python tests/verify_real_logs.py [папка_логов]

1) пересобирает историю (--backfill --days 4000) во временную папку;
2) отдельно считает суммы по сырым строкам простыми регулярками (по цвету строки);
3) сравнивает: урон нанесён/получен, отражено, баунти, руда по типам, число строк промахов.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def independent_totals(logs_dir):
    tot = Counter()
    ore = Counter()
    for name in sorted(os.listdir(logs_dir)):
        if not name.lower().endswith(".txt"):
            continue
        with open(os.path.join(logs_dir, name), encoding="utf-8", errors="replace") as f:
            text = f.read()
        if not re.search(r"^\s*(Слушатель|Listener):", text, re.M):
            continue
        for ln in text.splitlines():
            m = re.match(r"^\[ [\d. :]+ \] \((\w+)\) (.*)$", ln)
            if not m:
                continue
            typ, raw = m.groups()
            plain = re.sub(r"<[^>]*>", "", raw).replace("\xa0", " ")
            if typ == "combat":
                if raw.startswith("<color=0xff00ffff><b>"):          # исходящий урон (голубой)
                    n = int(re.match(r"\d+", plain).group())
                    r = re.search(r"\(Отражено (\d+)\)\s*$", plain)
                    refl = int(r.group(1)) if r else 0
                    tot["out"] += n - refl
                    tot["refl"] += refl
                elif raw.startswith("<color=0xffcc0000><b>"):        # входящий урон (красный)
                    tot["in"] += int(re.match(r"\d+", plain).group())
                elif "промах мимо вашего корабля" in plain or "промахнулось мимо вашего корабля" in plain:
                    tot["miss_in"] += 1
                elif plain.startswith(("Ваше орудие", "Ваша группа")):
                    tot["miss_out"] += 1
            elif typ == "bounty":
                tot["bounty"] += int(re.sub(r"\D", "", plain.split("ISK")[0]))
            elif typ == "mining":
                m2 = re.search(r"добыли (?:ещё )?(\d[\d ]*) ед\. (?:ресурса|руды) (.+?)\*?(?: и утратили|$)", plain)
                if m2:
                    ore[m2.group(2).replace("*", "").strip()] += int(m2.group(1).replace(" ", ""))
    return tot, ore


def app_totals(data_dir):
    tot = Counter()
    ore = Counter()
    recs = []
    with open(os.path.join(data_dir, "sessions.jsonl"), encoding="utf-8") as f:
        recs += [json.loads(x) for x in f]
    with open(os.path.join(data_dir, "state.json"), encoding="utf-8") as f:
        st = json.load(f)
    sys.path.insert(0, ROOT)
    import eve_log_watcher as elw
    recs += [elw.session_finalize(s, 20) for s in st["open"].values()]
    for r in recs:
        for k in ("out", "in", "refl", "miss_in", "miss_out", "bounty"):
            tot[k] += r[k]
        ore.update(r["ore"])
    return tot, ore, len(recs), st.get("unparsed_total", 0)


def main():
    logs = sys.argv[1] if len(sys.argv) > 1 else None
    data = tempfile.mkdtemp(prefix="elw_verify_")
    if logs:
        with open(os.path.join(data, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"logs_dir": logs, "online_enabled": False, "lock_port": 47391}, f)
    else:
        with open(os.path.join(data, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"online_enabled": False, "lock_port": 47391}, f)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "eve_log_watcher.py"), "--data-dir", data,
                        "--backfill", "--days", "4000"], capture_output=True)
    if r.returncode != 0:
        print(r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace"))
        return 1
    sys.path.insert(0, ROOT)
    import eve_log_watcher as elw
    logs = logs or elw.resolve_logs_dir(elw.load_config(data))
    a, a_ore, n, unparsed = app_totals(data)
    b, b_ore = independent_totals(logs)
    ok = True
    print(f"Логи: {logs}\nСессий: {n}, нераспознанных строк: {unparsed}\n")
    print(f"{'показатель':<14}{'приложение':>16}{'независимо':>16}")
    for k in ("out", "in", "refl", "miss_in", "miss_out", "bounty"):
        same = abs(a[k] - b[k]) < 0.01
        ok &= same
        print(f"{k:<14}{a[k]:>16,.0f}{b[k]:>16,.0f}  {'OK' if same else 'РАСХОЖДЕНИЕ'}")
    print("\nРуда по типам:")
    for k in sorted(set(a_ore) | set(b_ore)):
        same = a_ore[k] == b_ore[k]
        ok &= same
        print(f"  {k:<28}{a_ore[k]:>12,}{b_ore[k]:>12,}  {'OK' if same else 'РАСХОЖДЕНИЕ'}")
    print("\nИТОГ:", "всё совпадает" if ok else "ЕСТЬ РАСХОЖДЕНИЯ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
