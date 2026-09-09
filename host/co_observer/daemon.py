"""
co-daemon — agreguje zdarzenia z hookow i statusLine, utrzymuje rejestr
instancji i wypycha stan do urzadzenia (§5.3 planu).

Uruchomienie:
    python3 -m co_observer.daemon --transport sim
    python3 -m co_observer.daemon --transport usb --port /dev/claude-observer
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import time
from pathlib import Path

from . import proto as P
from .registry import Registry
from .transport import make_transport

log = logging.getLogger("co-daemon")

PING_INTERVAL = 10.0        # §7.5: host nadaje bezwarunkowo co 10 s
PUSH_INTERVAL = 0.5         # dlawienie — nie czesciej niz 2 Hz (§5.3)
EXPIRE_INTERVAL = 60.0


def socket_path() -> Path:
    rt = os.environ.get("XDG_RUNTIME_DIR")
    if rt:
        return Path(rt) / "claude-observer.sock"
    return Path(f"/tmp/claude-observer-{os.getuid()}.sock")


class Daemon:
    def __init__(self, transport, sock_path: Path):
        self.reg = Registry()
        self.tr = transport
        self.sock_path = sock_path
        self.dirty = True
        self.limits = (None, None, 0, 0)
        self.limits_dirty = True
        self._ping_seq = 0
        self._last_snapshot: bytes | None = None

    # -- odbior zdarzen ----------------------------------------------------

    def handle_event(self, ev: dict) -> None:
        kind = ev.get("kind")
        sid = ev.get("session_id")
        if not sid:
            return

        if kind == "hook":
            before = self._fingerprint()
            self.reg.apply_hook(
                ev.get("event", ""), sid,
                cwd=ev.get("cwd", ""),
                env_label=ev.get("label"),
                notification_type=ev.get("notification_type"),
            )
            if self._fingerprint() != before:
                self.dirty = True

        elif kind == "status":
            before = self._fingerprint()
            self.reg.apply_status(sid, cwd=ev.get("cwd", ""),
                                  env_label=ev.get("label"),
                                  ctx_pct=ev.get("ctx_pct"))
            lim = (ev.get("five_h"), ev.get("seven_d"),
                   int(ev.get("five_reset") or 0), int(ev.get("seven_reset") or 0))
            if lim != self.limits:
                self.limits = lim
                self.limits_dirty = True
            if self._fingerprint() != before:
                self.dirty = True

    def _fingerprint(self):
        return [(i.dev_id, i.state, i.ctx_pct, i.label) for i in self.reg.instances()]

    # -- wypychanie stanu --------------------------------------------------

    def push(self) -> None:
        payload = P.build_snapshot(self.reg.snapshot())
        # wysylamy tylko przy realnej zmianie — oszczedza radio i baterie
        if payload != self._last_snapshot:
            self.tr.send(P.MSG_SNAPSHOT, payload)
            self._last_snapshot = payload
        if self.limits_dirty:
            five, seven, fr, sr = self.limits
            self.tr.send(P.MSG_LIMITS, P.build_limits(five, seven, fr, sr))
            self.limits_dirty = False

    def handle_device_msg(self, msg_type: int, payload: bytes) -> None:
        if msg_type == P.MSG_SELECT and payload:
            log.info("urzadzenie wybralo instancje id=%d", payload[0])
        elif msg_type == P.MSG_BATTERY and len(payload) >= 4:
            mv, pct, flags = P.parse_battery(payload)
            log.info("bateria: %d mV, %d%%, flags=0x%02x", mv, pct, flags)
        elif msg_type == P.MSG_HELLO:
            log.info("HELLO od urzadzenia: %s", payload.hex())
            self.dirty = True
            self.limits_dirty = True
            self._last_snapshot = None      # wymus pelny snapshot po (re)polaczeniu

    # -- petle -------------------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        if self.sock_path.exists():
            self.sock_path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(str(self.sock_path))
        os.chmod(self.sock_path, 0o600)
        sock.setblocking(False)
        log.info("nasluch: %s, transport: %s", self.sock_path, self.tr.name)

        def on_readable():
            try:
                while True:
                    data, _ = sock.recvfrom(65536)
                    try:
                        self.handle_event(json.loads(data))
                    except Exception as e:
                        log.debug("zle zdarzenie: %s", e)
            except BlockingIOError:
                pass

        loop.add_reader(sock.fileno(), on_readable)

        try:
            await asyncio.gather(self._push_loop(), self._ping_loop(),
                                 self._rx_loop(), self._expire_loop())
        finally:
            loop.remove_reader(sock.fileno())
            sock.close()
            self.sock_path.unlink(missing_ok=True)
            self.tr.close()

    async def _push_loop(self):
        while True:
            if self.dirty or self.limits_dirty:
                self.dirty = False
                try:
                    self.push()
                except Exception as e:
                    log.warning("blad wysylki: %s", e)
            await asyncio.sleep(PUSH_INTERVAL)

    async def _ping_loop(self):
        while True:
            await asyncio.sleep(PING_INTERVAL)
            self._ping_seq += 1
            try:
                self.tr.send(P.MSG_PING, self._ping_seq.to_bytes(4, "little"))
            except Exception as e:
                log.warning("blad PING: %s", e)

    async def _rx_loop(self):
        while True:
            try:
                for mt, pl in self.tr.poll():
                    self.handle_device_msg(mt, pl)
            except Exception as e:
                log.warning("blad odbioru: %s", e)
            await asyncio.sleep(0.05)

    async def _expire_loop(self):
        while True:
            await asyncio.sleep(EXPIRE_INTERVAL)
            if self.reg.expire():
                self.dirty = True


def main() -> None:
    ap = argparse.ArgumentParser(prog="co-daemon")
    ap.add_argument("--transport", choices=["auto", "usb", "sim"], default="auto")
    ap.add_argument("--port", help="port CDC, np. /dev/claude-observer")
    ap.add_argument("--state-file", help="zrzut stanu dla podgladu graficznego")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    kw = {}
    if a.transport == "usb" and a.port:
        kw["port"] = a.port
    if a.transport in ("sim", "auto"):
        kw["state_file"] = a.state_file

    tr = make_transport(a.transport, **kw)
    try:
        asyncio.run(Daemon(tr, socket_path()).run())
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
