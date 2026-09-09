"""
Protokol claude-observer — strona hosta.

Bliźniacza implementacja firmware/src/link/proto.{c,h}. Zgodnosc obu stron
jest weryfikowana krzyzowo przez tools/proto_check.py (fuzz: Python koduje ->
C dekoduje i odwrotnie).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Iterator

PROTO_VERSION = 1

SYNC0, SYNC1 = 0xA5, 0x5A

MAX_INSTANCES = 8
LABEL_LEN = 16
INST_REC_LEN = 20
MAX_PAYLOAD = 224

# host -> urzadzenie
MSG_SNAPSHOT = 0x01
MSG_STATE = 0x02
MSG_LIMITS = 0x03
MSG_TIME = 0x04
MSG_PING = 0x05
# urzadzenie -> host
MSG_HELLO = 0x81
MSG_SELECT = 0x82
MSG_BATTERY = 0x83
MSG_PONG = 0x84

ST_IDLE, ST_WORKING, ST_NEED_INPUT = 0, 1, 2

STATE_NAMES = {ST_IDLE: "idle", ST_WORKING: "working", ST_NEED_INPUT: "need_input"}

LIM_HAS_5H = 0x01
LIM_HAS_7D = 0x02
BAT_CHARGING = 0x01
BAT_USB = 0x02

CTX_UNKNOWN = 0xFF


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(msg_type: int, payload: bytes = b"") -> bytes:
    """Ramka dla USB CDC (z preambula i CRC)."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload {len(payload)} > {MAX_PAYLOAD}")
    body = bytes([msg_type]) + payload
    return (bytes([SYNC0, SYNC1])
            + struct.pack("<H", len(payload))
            + body
            + struct.pack("<H", crc16(body)))


def encode_ble(msg_type: int, payload: bytes = b"") -> bytes:
    """Pakiet dla BLE — ATT sam wyznacza granice, wiec bez ramkowania."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload {len(payload)} > {MAX_PAYLOAD}")
    return bytes([msg_type]) + payload


@dataclass
class Instance:
    id: int
    state: int
    ctx_pct: int
    flags: int
    label: str

    def pack(self) -> bytes:
        lab = self.label.encode("ascii", "replace")[: LABEL_LEN - 1]
        return (bytes([self.id, self.state, self.ctx_pct, self.flags])
                + lab + b"\0" * (LABEL_LEN - len(lab)))

    @classmethod
    def unpack(cls, rec: bytes) -> "Instance":
        lab = rec[4:4 + LABEL_LEN].split(b"\0", 1)[0].decode("ascii", "replace")
        return cls(rec[0], rec[1], rec[2], rec[3], lab)


def build_snapshot(insts: list[Instance]) -> bytes:
    insts = insts[:MAX_INSTANCES]
    return bytes([len(insts)]) + b"".join(i.pack() for i in insts)


def parse_snapshot(p: bytes) -> list[Instance]:
    if not p:
        raise ValueError("pusty payload SNAPSHOT")
    n = p[0]
    if n > MAX_INSTANCES or len(p) < 1 + n * INST_REC_LEN:
        raise ValueError("obciety SNAPSHOT")
    return [Instance.unpack(p[1 + i * INST_REC_LEN: 1 + (i + 1) * INST_REC_LEN])
            for i in range(n)]


def build_state(inst_id: int, state: int, ctx_pct: int) -> bytes:
    return bytes([inst_id, state, ctx_pct])


def build_limits(five_h: int | None, seven_d: int | None,
                 five_reset: int = 0, seven_reset: int = 0) -> bytes:
    """`None` = okno nieobecne w JSON statusLine — urzadzenie wyszarza ciastko."""
    flags = (LIM_HAS_5H if five_h is not None else 0) | \
            (LIM_HAS_7D if seven_d is not None else 0)
    return struct.pack("<BBIIB", five_h or 0, seven_d or 0,
                       five_reset, seven_reset, flags)


def parse_limits(p: bytes) -> tuple[int | None, int | None, int, int]:
    five, seven, fr, sr, flags = struct.unpack("<BBIIB", p[:11])
    return (five if flags & LIM_HAS_5H else None,
            seven if flags & LIM_HAS_7D else None, fr, sr)


def build_battery(mv: int, pct: int, flags: int = 0) -> bytes:
    return struct.pack("<HBB", mv, pct, flags)


def parse_battery(p: bytes) -> tuple[int, int, int]:
    return struct.unpack("<HBB", p[:4])


class Decoder:
    """Dekoder strumieniowy dla USB CDC. Odporny na smieci i resynchronizacje."""

    S_SYNC0, S_SYNC1, S_LEN0, S_LEN1, S_TYPE, S_PAYLOAD, S_CRC0, S_CRC1 = range(8)

    def __init__(self, cb: Callable[[int, bytes], None] | None = None):
        self.cb = cb
        self.reset()
        self.n_ok = self.n_crc_err = self.n_overrun = 0

    def reset(self) -> None:
        self.state = self.S_SYNC0
        self.length = 0
        self.msg_type = 0
        self.buf = bytearray()
        self.crc_rx = 0

    def feed(self, data: bytes) -> Iterator[tuple[int, bytes]]:
        for b in data:
            msg = self._byte(b)
            if msg is not None:
                if self.cb:
                    self.cb(*msg)
                yield msg

    def _byte(self, b: int):
        s = self.state
        if s == self.S_SYNC0:
            if b == SYNC0:
                self.state = self.S_SYNC1
        elif s == self.S_SYNC1:
            # 0xA5 zamiast 0x5A moze byc poczatkiem prawdziwej ramki po smieciach
            if b == SYNC1:
                self.state = self.S_LEN0
            elif b == SYNC0:
                self.state = self.S_SYNC1
            else:
                self.state = self.S_SYNC0
        elif s == self.S_LEN0:
            self.length = b
            self.state = self.S_LEN1
        elif s == self.S_LEN1:
            self.length |= b << 8
            if self.length > MAX_PAYLOAD:
                self.n_overrun += 1
                self.reset()
            else:
                self.state = self.S_TYPE
        elif s == self.S_TYPE:
            self.msg_type = b
            self.buf = bytearray()
            self.state = self.S_PAYLOAD if self.length else self.S_CRC0
        elif s == self.S_PAYLOAD:
            self.buf.append(b)
            if len(self.buf) >= self.length:
                self.state = self.S_CRC0
        elif s == self.S_CRC0:
            self.crc_rx = b
            self.state = self.S_CRC1
        elif s == self.S_CRC1:
            self.crc_rx |= b << 8
            body = bytes([self.msg_type]) + bytes(self.buf)
            out = None
            if crc16(body) == self.crc_rx:
                self.n_ok += 1
                out = (self.msg_type, bytes(self.buf))
            else:
                self.n_crc_err += 1
            self.reset()
            return out
        return None
