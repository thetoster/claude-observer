#!/bin/bash
# Wszystkie testy dzialajace bez plytki.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== protokol (C <-> Python) =="
gcc -O2 -std=c11 -Wall -Wextra -I "$ROOT/firmware/src/link" \
    -o "$TMP/proto_bridge" "$ROOT/tools/proto_bridge.c" "$ROOT/firmware/src/link/proto.c"
"$PY" "$ROOT/tools/proto_check.py" "$TMP/proto_bridge"

echo
echo "== model urzadzenia (spec 6-9) =="
gcc -O2 -std=c11 -Wall -Wextra -I "$ROOT/firmware/src/link" -I "$ROOT/firmware/src/model" \
    -o "$TMP/model_check" "$ROOT/tools/model_check.c" \
    "$ROOT/firmware/src/model/instances.c" "$ROOT/firmware/src/link/proto.c"
"$TMP/model_check"

echo
echo "== rejestr hosta (§7.6, D16) =="
"$PY" "$ROOT/tools/registry_check.py"

echo
echo "== zasoby graficzne =="
"$PY" "$ROOT/tools/img2c.py" --verify | tail -3
