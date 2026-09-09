#!/bin/bash
# Buduje harness renderujacy i zapisuje podglady ekranow jako PNG.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/tools/render_out"
mkdir -p "$OUT"
rm -f "$OUT"/*.ppm "$OUT"/*.png

gcc -O2 -std=c11 -Wall -Wextra \
    -I"$ROOT/firmware/src/display" -I"$ROOT/firmware/src/ui" \
    -o "$OUT/render_host" \
    "$ROOT/tools/render_host.c" \
    "$ROOT/firmware/src/display/framebuf.c" \
    "$ROOT/firmware/src/display/assets_gen.c" \
    "$ROOT/firmware/src/ui/widgets.c" \
    -lm

"$OUT/render_host" "$OUT"

for f in "$OUT"/*.ppm; do
    [ -e "$f" ] || continue
    magick "$f" -scale 300% "${f%.ppm}.png" 2>/dev/null || \
      convert "$f" -scale 300% "${f%.ppm}.png"
    rm -f "$f"
done
echo "PNG w: $OUT"
ls "$OUT"/*.png | wc -l | xargs echo "plikow:"
