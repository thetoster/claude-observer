"""
Transporty daemona. USB CDC dziala dzis; BLE dochodzi w M6 (§5.3 planu).
Wybor transportu jest dynamiczny — USB ma pierwszenstwo (spec 2).
"""

from __future__ import annotations

import glob
import sys
import time

from . import proto as P

PICO_VID_PID = ("2E8A", "000A")     # RP2350 CDC


class Transport:
    name = "?"

    def send(self, msg_type: int, payload: bytes = b"") -> None: ...
    def poll(self) -> list[tuple[int, bytes]]: return []
    def close(self) -> None: ...
    @property
    def alive(self) -> bool: return False


class SerialTransport(Transport):
    """USB CDC. Ramkowanie z preambula i CRC (proto.encode)."""

    name = "USB"

    def __init__(self, port: str | None = None, baud: int = 115200):
        import serial  # import lokalny — daemon dziala tez bez pyserial
        self._serial_mod = serial
        self.port = port or self._autodetect()
        if not self.port:
            raise FileNotFoundError("nie znaleziono portu CDC urzadzenia")
        self.ser = serial.Serial(self.port, baud, timeout=0)
        self.dec = P.Decoder()

    @staticmethod
    def _autodetect() -> str | None:
        # alias z reguly udev (99-pico.rules) ma pierwszenstwo
        for p in ("/dev/claude-observer", *sorted(glob.glob("/dev/ttyACM*"))):
            try:
                open(p).close()
                return p
            except OSError:
                continue
        return None

    def send(self, msg_type, payload=b""):
        self.ser.write(P.encode(msg_type, payload))

    def poll(self):
        data = self.ser.read(4096)
        return list(self.dec.feed(data)) if data else []

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    @property
    def alive(self):
        return self.ser.is_open


class SimTransport(Transport):
    """
    Symulator: zamiast plytki rysuje pasek instancji w terminalu.
    Pozwala domknac M4 zanim sprzet bedzie dostepny — dokladnie ta sama
    sciezka danych, tylko inne ujscie.
    """

    name = "SIM"

    PIP = {P.ST_WORKING: "\033[38;5;209m●\033[0m",
           P.ST_NEED_INPUT: "\033[38;5;39m●\033[0m",
           P.ST_IDLE: "\033[38;5;240m●\033[0m"}

    def __init__(self, stream=sys.stdout, state_file: str | None = None):
        self.out = stream
        self.state_file = state_file
        self.insts: list[P.Instance] = []
        self.limits: tuple = (None, None, 0, 0)
        self.selected = 0
        self._last = ""

    def send(self, msg_type, payload=b""):
        if msg_type == P.MSG_SNAPSHOT:
            self.insts = P.parse_snapshot(payload)
        elif msg_type == P.MSG_STATE and len(payload) >= 3:
            for i in self.insts:
                if i.id == payload[0]:
                    i.state, i.ctx_pct = payload[1], payload[2]
        elif msg_type == P.MSG_LIMITS:
            self.limits = P.parse_limits(payload)
        elif msg_type == P.MSG_PING:
            return
        self._draw()

    def _select(self) -> int:
        """Odwzorowuje regule spec 7: need_input wybiera sie samo."""
        for n, i in enumerate(self.insts):
            if i.state == P.ST_NEED_INPUT:
                return n
        return min(self.selected, max(0, len(self.insts) - 1))

    def _draw(self):
        if not self.insts:
            line = "\033[38;5;240m(brak instancji)\033[0m"
        else:
            sel = self._select()
            pips = " ".join(self.PIP.get(i.state, "?") for i in self.insts)
            cur = self.insts[sel]
            ctx = "--" if cur.ctx_pct == P.CTX_UNKNOWN else f"{cur.ctx_pct}%"
            five, seven, _, _ = self.limits
            lim = f"5h:{five if five is not None else '--'}% " \
                  f"7d:{seven if seven is not None else '--'}%"
            line = (f"[{pips}] \033[1m{cur.label:<15}\033[0m "
                    f"ctx:{ctx:>4}  {lim}")
        if line != self._last:
            self.out.write(f"\r\033[K{time.strftime('%H:%M:%S')}  {line}")
            self.out.flush()
            self._last = line
        if self.state_file:
            self._dump()

    def _dump(self):
        sel = self._select() if self.insts else 0
        five, seven, _, _ = self.limits
        with open(self.state_file, "w") as f:
            f.write(f"{len(self.insts)} {sel} "
                    f"{self.insts[sel].ctx_pct if self.insts else 255} "
                    f"{seven if seven is not None else 255}\n")
            for i in self.insts:
                f.write(f"{i.state} {i.label}\n")

    @property
    def alive(self):
        return True


def make_transport(kind: str, **kw) -> Transport:
    if kind == "usb":
        return SerialTransport(**kw)
    if kind == "sim":
        return SimTransport(**kw)
    if kind == "auto":
        try:
            return SerialTransport()
        except Exception:
            return SimTransport(**kw)
    raise ValueError(f"nieznany transport: {kind}")
