#!/usr/bin/env python3
"""
proto_check.py — krzyzowa weryfikacja protokolu miedzy C a Pythonem.

Cztery testy:
  1. Python koduje  -> C dekoduje       (host -> urzadzenie)
  2. C koduje       -> Python dekoduje  (urzadzenie -> host)
  3. odpornosc na smieci i resynchronizacja
  4. wykrywanie przeklamanych bitow przez CRC

Uruchomienie:
    python3 tools/proto_check.py [sciezka/do/proto_bridge]
"""

import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))

from co_observer import proto as P  # noqa: E402

BRIDGE = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path("/tmp/claude-1000/-home-toster-work-claude-observer/"
         "a55741f3-fa4b-4a7e-88a4-51516452b886/scratchpad/proto_bridge")

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  BLAD {name}  {detail}")


def random_messages(rng, n):
    """Losowe, ale prawidlowe wiadomosci — z naciskiem na przypadki brzegowe."""
    out = []
    for _ in range(n):
        kind = rng.randrange(6)
        if kind == 0:
            k = rng.choice([0, 1, P.MAX_INSTANCES])       # 0 i maksimum wazne
            insts = [P.Instance(
                id=rng.randrange(256),
                state=rng.choice([P.ST_IDLE, P.ST_WORKING, P.ST_NEED_INPUT]),
                ctx_pct=rng.choice([0, 50, 100, P.CTX_UNKNOWN]),
                flags=rng.randrange(256),
                label=rng.choice(["a", "claude_observer", "x" * 15,
                                  "claude_obs#2", ""]),
            ) for _ in range(k)]
            out.append((P.MSG_SNAPSHOT, P.build_snapshot(insts)))
        elif kind == 1:
            out.append((P.MSG_STATE, P.build_state(rng.randrange(256),
                                                   rng.randrange(3),
                                                   rng.randrange(101))))
        elif kind == 2:
            out.append((P.MSG_LIMITS, P.build_limits(
                rng.choice([None, 0, 34, 100]), rng.choice([None, 0, 61, 100]),
                rng.randrange(2**32), rng.randrange(2**32))))
        elif kind == 3:
            out.append((P.MSG_TIME, rng.randrange(2**32).to_bytes(4, "little")))
        elif kind == 4:
            out.append((P.MSG_PING, rng.randrange(2**32).to_bytes(4, "little")))
        else:
            out.append((P.MSG_BATTERY, P.build_battery(rng.randrange(65536),
                                                       rng.randrange(101),
                                                       rng.randrange(4))))
    return out


def main():
    if not BRIDGE.exists():
        sys.exit(f"brak mostu C: {BRIDGE}")
    rng = random.Random(20260909)

    # --- 1. Python -> C ----------------------------------------------------
    msgs = random_messages(rng, 500)
    stream = b"".join(P.encode(t, p) for t, p in msgs)
    r = subprocess.run([str(BRIDGE)], input=stream, capture_output=True)
    lines = r.stdout.decode().strip().splitlines()
    check("Python koduje -> C dekoduje: liczba ramek",
          len(lines) == len(msgs), f"{len(lines)} != {len(msgs)}")
    bad = [i for i, (ln, (t, p)) in enumerate(zip(lines, msgs))
           if ln != f"OK {t:02x} {p.hex()}"]
    check("Python koduje -> C dekoduje: tresc", not bad, f"rozne: {bad[:3]}")

    # --- 2. C -> Python ----------------------------------------------------
    inp = "".join(f"{t:02x} {p.hex()}\n" for t, p in msgs).encode()
    r = subprocess.run([str(BRIDGE), "encode"], input=inp, capture_output=True)
    dec = list(P.Decoder().feed(r.stdout))
    check("C koduje -> Python dekoduje: liczba ramek",
          len(dec) == len(msgs), f"{len(dec)} != {len(msgs)}")
    check("C koduje -> Python dekoduje: tresc", dec == msgs)

    # bajt w bajt identyczne ramki po obu stronach
    check("identyczne bajty ramek", r.stdout == stream)

    # --- 3. odpornosc na smieci -------------------------------------------
    noisy = bytearray()
    for t, p in msgs[:100]:
        noisy += bytes(rng.randrange(256) for _ in range(rng.randrange(8)))
        noisy += P.encode(t, p)
    # zlosliwy przypadek: preambula w strumieniu smieci
    noisy += bytes([P.SYNC0, P.SYNC0, P.SYNC0]) + P.encode(*msgs[0])
    dec = [m for m in P.Decoder().feed(bytes(noisy))]
    got = sum(1 for m in dec if m in msgs)
    check("resynchronizacja po smieciach (Python)", got >= 100, f"odzyskano {got}/101")

    r = subprocess.run([str(BRIDGE)], input=bytes(noisy), capture_output=True)
    n_ok = len(r.stdout.decode().strip().splitlines())
    check("resynchronizacja po smieciach (C)", n_ok >= 100, f"odzyskano {n_ok}")

    # --- 4. CRC wykrywa przeklamania --------------------------------------
    caught = 0
    trials = 200
    for _ in range(trials):
        t, p = msgs[rng.randrange(len(msgs))]
        f = bytearray(P.encode(t, p))
        i = rng.randrange(4, len(f))            # nie ruszamy preambuly
        f[i] ^= 1 << rng.randrange(8)
        d = P.Decoder()
        out = list(d.feed(bytes(f)))
        if not out or out[0] != (t, p):
            caught += 1
    check("CRC wykrywa przeklamany bit", caught == trials,
          f"przepuszczono {trials - caught}/{trials}")

    # --- podsumowanie ------------------------------------------------------
    big = P.build_snapshot([P.Instance(i, P.ST_WORKING, 50, 0, "x" * 15)
                            for i in range(P.MAX_INSTANCES)])
    print(f"\n  najwieksza ramka (SNAPSHOT x{P.MAX_INSTANCES}): "
          f"{len(P.encode(P.MSG_SNAPSHOT, big))} B "
          f"(payload {len(big)} B, limit {P.MAX_PAYLOAD})")
    print(f"  wynik: {'WSZYSTKO OK' if not FAIL else f'{FAIL} BLEDOW'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
