#!/usr/bin/env python3
"""Testy rejestru instancji — logika etykiet i stanow (§7.6, D16)."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))

from co_observer import proto as P          # noqa: E402
from co_observer.registry import Registry   # noqa: E402

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  BLAD {name}  {detail}")


def labels(r):
    return [i.label for i in r.instances()]


# --- etykiety: rozne katalogi ---------------------------------------------
r = Registry()
r.touch("s1", "/home/t/work/claude_observer")
r.touch("s2", "/home/t/work/drone")
check("rozne katalogi -> basename", labels(r) == ["claude_observer", "drone"],
      str(labels(r)))

# --- etykiety: ten sam katalog --------------------------------------------
r = Registry()
r.touch("s1", "/home/t/work/proj")
check("jedna instancja bez numeru", labels(r) == ["proj"], str(labels(r)))
r.touch("s2", "/home/t/work/proj")
check("kolizja -> obie dostaja numer", labels(r) == ["proj#1", "proj#2"],
      str(labels(r)))
r.touch("s3", "/home/t/work/proj")
check("trzecia dostaje #3", labels(r) == ["proj#1", "proj#2", "proj#3"],
      str(labels(r)))

# --- stabilnosc numeracji po zamknieciu -----------------------------------
r.remove("s1")
check("po usunieciu #1 reszta NIE przenumerowana",
      labels(r) == ["proj#2", "proj#3"], str(labels(r)))
r.touch("s4", "/home/t/work/proj")
check("nowa zajmuje zwolniony #1", labels(r) == ["proj#2", "proj#3", "proj#1"],
      str(labels(r)))

# --- CO_LABEL ma pierwszenstwo --------------------------------------------
r = Registry()
r.touch("s1", "/home/t/work/proj", env_label="frontend")
r.touch("s2", "/home/t/work/proj", env_label="backend")
check("CO_LABEL ma pierwszenstwo i nie koliduje",
      labels(r) == ["frontend", "backend"], str(labels(r)))

# --- obcinanie do 15 znakow -----------------------------------------------
r = Registry()
r.touch("s1", "/home/t/bardzo_dluga_nazwa_projektu")
check("etykieta obcieta do 15", len(labels(r)[0]) == 15, labels(r)[0])
r.touch("s2", "/home/t/bardzo_dluga_nazwa_projektu")
both = labels(r)
check("z sufiksem tez miesci sie w 15",
      all(len(x) <= 15 for x in both) and all(x.endswith(("#1", "#2")) for x in both),
      str(both))

# --- stany z hookow --------------------------------------------------------
r = Registry()
r.apply_hook("SessionStart", "s1", "/w/a")
check("SessionStart -> idle", r.instances()[0].state == P.ST_IDLE)
r.apply_hook("UserPromptSubmit", "s1", "/w/a")
check("UserPromptSubmit -> working", r.instances()[0].state == P.ST_WORKING)
r.apply_hook("Notification", "s1", "/w/a", notification_type="permission_prompt")
check("Notification/permission_prompt -> need_input",
      r.instances()[0].state == P.ST_NEED_INPUT)
r.apply_hook("Notification", "s1", "/w/a", notification_type="auth_success")
check("Notification nieistotne nie zmienia stanu",
      r.instances()[0].state == P.ST_NEED_INPUT)
r.apply_hook("SessionStart", "s1", "/w/a")
check("SessionStart nie zbija need_input (resume)",
      r.instances()[0].state == P.ST_NEED_INPUT)
r.apply_hook("Stop", "s1", "/w/a")
check("Stop -> idle", r.instances()[0].state == P.ST_IDLE)
r.apply_hook("SessionEnd", "s1", "/w/a")
check("SessionEnd usuwa instancje", len(r) == 0)

# --- subagenty nie mnoza instancji ----------------------------------------
r = Registry()
r.apply_hook("UserPromptSubmit", "s1", "/w/a")
for _ in range(5):
    r.apply_hook("SubagentStop", "s1", "/w/a")
check("subagenty nie tworza osobnych instancji", len(r) == 1, f"len={len(r)}")

# --- limit instancji -------------------------------------------------------
r = Registry()
for i in range(P.MAX_INSTANCES):
    r.apply_hook("UserPromptSubmit", f"s{i}", f"/w/p{i}")
check(f"limit {P.MAX_INSTANCES} instancji", len(r) == P.MAX_INSTANCES)
r.apply_hook("UserPromptSubmit", "s99", "/w/x")
check("ponad limit odrzucone gdy nic nie jest idle", len(r) == P.MAX_INSTANCES)
r.apply_hook("Stop", "s0", "/w/p0")
r.apply_hook("UserPromptSubmit", "s99", "/w/x")
check("idle wypierane przez nowa instancje",
      len(r) == P.MAX_INSTANCES and "s99" in [i.session_id for i in r.instances()])

# --- TTL -------------------------------------------------------------------
r = Registry()
r.touch("s1", "/w/a")
r.instances()[0].last_seen = time.time() - 20 * 60
check("TTL usuwa martwa sesje", r.expire() == ["s1"] and len(r) == 0)

# --- snapshot miesci sie w protokole --------------------------------------
r = Registry()
for i in range(P.MAX_INSTANCES):
    r.apply_hook("UserPromptSubmit", f"s{i}", "/home/t/work/ten_sam_katalog")
snap = r.snapshot()
frame = P.encode(P.MSG_SNAPSHOT, P.build_snapshot(snap))
back = P.parse_snapshot(P.build_snapshot(snap))
check("snapshot round-trip przez protokol",
      [i.label for i in back] == [i.label for i in snap])
check(f"ramka {len(frame)} B <= limit", len(frame) <= 2 + 2 + 1 + P.MAX_PAYLOAD + 2)
print(f"\n  8 instancji w tym samym katalogu: {[i.label for i in snap]}")
print(f"  wynik: {'WSZYSTKO OK' if not FAIL else f'{FAIL} BLEDOW'}")
sys.exit(1 if FAIL else 0)
