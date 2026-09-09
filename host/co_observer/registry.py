"""
Rejestr rownoleglych instancji Claude Code (§7.6 planu).

Rozdziela TOZSAMOSC (session_id — klucz maszynowy) od ETYKIETY (to, co widzi
czlowiek na 160 px). Etykieta wg trojstopniowego fallbacku D16:
    1. $CO_LABEL   2. basename(cwd)   3. przy kolizji: +#n
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from . import proto as P

# Odpowiada CO_LABEL_LEN - 1 w proto.h
LABEL_MAX = P.LABEL_LEN - 1

# Bez SessionEnd (ubity terminal) instancja wygasa po tym czasie (§5.3).
TTL_S = 15 * 60

# Mapowanie hookow na stany (§5.1 planu).
HOOK_STATE = {
    "SessionStart": P.ST_IDLE,
    "UserPromptSubmit": P.ST_WORKING,
    "PreToolUse": P.ST_WORKING,
    "PostToolUse": P.ST_WORKING,
    "PostToolUseFailure": P.ST_WORKING,
    "Stop": P.ST_IDLE,
    "SubagentStop": P.ST_WORKING,   # subagent skonczyl, ale sesja pracuje dalej
}

# Typy powiadomien oznaczajace "czeka na uzytkownika" (§5.1).
NEED_INPUT_NOTIFICATIONS = {
    "permission_prompt",
    "idle_prompt",
    "agent_needs_input",
    "elicitation_dialog",
    "elicitation_url_dialog",
}


@dataclass
class Instance:
    session_id: str
    dev_id: int                  # 1..255, identyfikator w protokole
    base_label: str              # bez dyskryminatora
    index: int | None = None     # #n nadawane przy kolizji, potem stale
    state: int = P.ST_IDLE
    ctx_pct: int = P.CTX_UNKNOWN
    cwd: str = ""
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    @property
    def label(self) -> str:
        if self.index is None:
            return self.base_label[:LABEL_MAX]
        suffix = f"#{self.index}"
        return self.base_label[: LABEL_MAX - len(suffix)] + suffix

    def to_proto(self) -> P.Instance:
        return P.Instance(id=self.dev_id, state=self.state,
                          ctx_pct=self.ctx_pct, flags=0, label=self.label)


class Registry:
    def __init__(self, max_instances: int = P.MAX_INSTANCES):
        self.max = max_instances
        self._by_session: dict[str, Instance] = {}
        self._next_dev_id = 1

    # -- pomocnicze --------------------------------------------------------

    def _alloc_dev_id(self) -> int:
        used = {i.dev_id for i in self._by_session.values()}
        for _ in range(255):
            did = self._next_dev_id
            self._next_dev_id = self._next_dev_id % 255 + 1
            if did not in used:
                return did
        raise RuntimeError("brak wolnych identyfikatorow")

    @staticmethod
    def _base_label(cwd: str, env_label: str | None) -> str:
        if env_label:
            return env_label.strip()[:LABEL_MAX]
        name = os.path.basename(cwd.rstrip("/")) or "?"
        return name[:LABEL_MAX]

    def _resolve_collision(self, new: Instance) -> None:
        """
        Nadaje #n gdy etykieta bazowa sie powtarza. Numer raz przypisany zostaje
        do konca zycia sesji — zwolniony przez zamknieta sesje NIE powoduje
        przenumerowania pozostalych, bo instancja zmienialaby nazwe pod palcem
        uzytkownika.
        """
        peers = [i for i in self._by_session.values()
                 if i.base_label == new.base_label and i is not new]
        if not peers:
            return

        taken = {i.index for i in peers if i.index is not None}

        # pierwsza kolizja: dotychczas samotna instancja tez dostaje numer
        for p in peers:
            if p.index is None:
                n = 1
                while n in taken:
                    n += 1
                p.index = n
                taken.add(n)

        n = 1
        while n in taken:
            n += 1
        new.index = n

    # -- API ---------------------------------------------------------------

    def touch(self, session_id: str, cwd: str = "",
              env_label: str | None = None) -> Instance | None:
        """Zwraca instancje, rejestrujac ja przy pierwszym kontakcie."""
        inst = self._by_session.get(session_id)
        if inst is not None:
            inst.last_seen = time.time()
            if cwd and cwd != inst.cwd:
                inst.cwd = cwd          # /cd w trakcie sesji nie zmienia etykiety
            return inst

        if len(self._by_session) >= self.max:
            self._evict_oldest_idle()
            if len(self._by_session) >= self.max:
                return None

        inst = Instance(
            session_id=session_id,
            dev_id=self._alloc_dev_id(),
            base_label=self._base_label(cwd, env_label),
            cwd=cwd,
        )
        self._by_session[session_id] = inst
        self._resolve_collision(inst)
        return inst

    def _evict_oldest_idle(self) -> None:
        idle = [i for i in self._by_session.values() if i.state == P.ST_IDLE]
        if idle:
            victim = min(idle, key=lambda i: i.last_seen)
            self.remove(victim.session_id)

    def remove(self, session_id: str) -> bool:
        return self._by_session.pop(session_id, None) is not None

    def apply_hook(self, event: str, session_id: str, cwd: str = "",
                   env_label: str | None = None,
                   notification_type: str | None = None) -> Instance | None:
        if event == "SessionEnd":
            self.remove(session_id)
            return None

        inst = self.touch(session_id, cwd, env_label)
        if inst is None:
            return None

        if event == "Notification":
            if notification_type in NEED_INPUT_NOTIFICATIONS:
                inst.state = P.ST_NEED_INPUT
            return inst

        state = HOOK_STATE.get(event)
        if state is not None:
            # SessionStart nie moze zbic stanu need_input przy /resume
            if not (event == "SessionStart" and inst.state == P.ST_NEED_INPUT):
                inst.state = state
        return inst

    def apply_status(self, session_id: str, cwd: str = "",
                     env_label: str | None = None,
                     ctx_pct: int | None = None) -> Instance | None:
        inst = self.touch(session_id, cwd, env_label)
        if inst is not None and ctx_pct is not None:
            inst.ctx_pct = max(0, min(100, int(ctx_pct)))
        return inst

    def expire(self, now: float | None = None) -> list[str]:
        now = now or time.time()
        dead = [sid for sid, i in self._by_session.items()
                if now - i.last_seen > TTL_S]
        for sid in dead:
            del self._by_session[sid]
        return dead

    def instances(self) -> list[Instance]:
        """Kolejnosc rejestracji — stabilna (§14 planu)."""
        return sorted(self._by_session.values(), key=lambda i: i.registered_at)

    def snapshot(self) -> list[P.Instance]:
        return [i.to_proto() for i in self.instances()]

    def __len__(self) -> int:
        return len(self._by_session)
