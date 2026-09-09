#!/usr/bin/env python3
"""
Instalator strony hosta: hooki, opakowanie statusLine, usluga systemd.

Idempotentny. `--uninstall` przywraca stan sprzed instalacji.
Nic nie nadpisuje bez kopii zapasowej.

    python3 host/install.py --dry-run          # pokaz co by zrobil
    python3 host/install.py
    python3 host/install.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / "host"
NOTIFY = HOST / "co-notify"
VENV_PY = ROOT / ".venv" / "bin" / "python"

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
SL_WRAPPER = CLAUDE_DIR / "statusline-co.sh"

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT = UNIT_DIR / "claude-observer.service"

MARKER = "co-notify"          # po tym rozpoznajemy wlasne wpisy przy deinstalacji

# UserPromptSubmit i Stop nie wspieraja matchera — stad brak klucza "matcher".
HOOK_EVENTS = [
    ("SessionStart", "startup|resume|clear"),
    ("UserPromptSubmit", None),
    ("PreToolUse", "*"),
    ("PostToolUse", "*"),
    ("Notification", "*"),
    ("Stop", None),
    ("SessionEnd", "*"),
]


def hook_entry(cmd: str, matcher: str | None) -> dict:
    entry = {
        "hooks": [{
            "type": "command",
            "command": cmd,
            "timeout": 5,
            # kluczowe: hook nie moze opozniac Claude Code (§5.1 planu)
            "async": True,
        }]
    }
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


def load_settings() -> dict:
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def backup(path: Path, dry: bool) -> Path | None:
    if not path.exists():
        return None
    dst = path.with_suffix(path.suffix + f".co-backup-{int(time.time())}")
    print(f"  kopia zapasowa: {dst.name}")
    if not dry:
        shutil.copy2(path, dst)
    return dst


def strip_ours(settings: dict) -> dict:
    """Usuwa wylacznie nasze wpisy, cudze zostawia nietkniete."""
    hooks = settings.get("hooks") or {}
    for event in list(hooks):
        kept = []
        for entry in hooks[event]:
            inner = [h for h in entry.get("hooks", [])
                     if MARKER not in str(h.get("command", ""))]
            if inner:
                kept.append({**entry, "hooks": inner})
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)
    return settings


def install(dry: bool) -> None:
    if not NOTIFY.exists():
        sys.exit(f"brak {NOTIFY}")
    py = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    cmd = f"{py} {NOTIFY} --hook"

    print("1. hooki w ~/.claude/settings.json")
    settings = load_settings()
    backup(SETTINGS, dry)
    settings = strip_ours(settings)          # najpierw sprzataj po poprzedniej instalacji
    hooks = settings.setdefault("hooks", {})
    for event, matcher in HOOK_EVENTS:
        hooks.setdefault(event, []).append(hook_entry(cmd, matcher))
        print(f"   + {event}" + (f" [{matcher}]" if matcher else ""))

    print("2. opakowanie statusLine")
    old = (settings.get("statusLine") or {}).get("command", "")
    if MARKER in old or "statusline-co.sh" in old:
        print("   juz opakowany — pomijam")
    else:
        wrapper = f"""#!/bin/bash
# Opakowanie statusLine dla claude-observer.
# Rozdziela JSON na dwa strumienie: jeden do daemona (w tle, zero opoznienia),
# drugi do oryginalnego skryptu, ktorego wyjscie nadal trafia na pasek.
input=$(cat)
printf '%s' "$input" | {py} {NOTIFY} --status >/dev/null 2>&1 &
"""
        if old:
            wrapper += f'printf \'%s\' "$input" | {old}\n'
            print(f"   oryginal zachowany: {old}")
        else:
            wrapper += "printf '%s' \"$input\" | jq -r '.model.display_name'\n"
        if not dry:
            SL_WRAPPER.write_text(wrapper, encoding="utf-8")
            SL_WRAPPER.chmod(0o755)
        settings["statusLine"] = {"type": "command",
                                  "command": f"bash {SL_WRAPPER}"}
        print(f"   -> {SL_WRAPPER}")

    if not dry:
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    print("3. usluga systemd --user")
    unit = f"""[Unit]
Description=claude-observer daemon
After=default.target

[Service]
Type=simple
Environment=PYTHONPATH={HOST}
ExecStart={py} -m co_observer.daemon --transport auto
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    if not dry:
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
        UNIT.write_text(unit, encoding="utf-8")
    print(f"   -> {UNIT}")
    print("\nGotowe. Uruchom:")
    print("   systemctl --user daemon-reload")
    print("   systemctl --user enable --now claude-observer")
    print("\nBez plytki podejrzyj dzialanie na zywo:")
    print(f"   PYTHONPATH={HOST} {py} -m co_observer.daemon --transport sim")


def uninstall(dry: bool) -> None:
    print("1. usuwanie hookow")
    settings = load_settings()
    backup(SETTINGS, dry)
    settings = strip_ours(settings)

    print("2. przywracanie statusLine")
    cur = (settings.get("statusLine") or {}).get("command", "")
    if "statusline-co.sh" in cur and SL_WRAPPER.exists():
        orig = ""
        for line in SL_WRAPPER.read_text(encoding="utf-8").splitlines():
            if line.startswith("printf") and MARKER not in line:
                orig = line.split("| ", 1)[1] if "| " in line else ""
        if orig:
            settings["statusLine"] = {"type": "command", "command": orig}
            print(f"   przywrocony: {orig}")
        else:
            settings.pop("statusLine", None)
        if not dry:
            SL_WRAPPER.unlink(missing_ok=True)

    if not dry:
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    print("3. usluga systemd")
    if not dry:
        os.system("systemctl --user disable --now claude-observer 2>/dev/null")
        UNIT.unlink(missing_ok=True)
    print(f"   usunieto {UNIT}")
    print("\nOdinstalowane. Kopie zapasowe settings.json zostaly zachowane.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--claude-dir", type=Path,
                    help="katalog .claude do testow (domyslnie ~/.claude)")
    a = ap.parse_args()

    if a.claude_dir:
        global CLAUDE_DIR, SETTINGS, SL_WRAPPER
        CLAUDE_DIR = a.claude_dir
        SETTINGS = CLAUDE_DIR / "settings.json"
        SL_WRAPPER = CLAUDE_DIR / "statusline-co.sh"

    if a.dry_run:
        print("--- DRY RUN, nic nie zostanie zapisane ---")
    (uninstall if a.uninstall else install)(a.dry_run)


if __name__ == "__main__":
    main()
