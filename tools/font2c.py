#!/usr/bin/env python3
"""
font2c.py — generuje bitmapowy font do firmware/src/display/font_gen.{c,h}.

Zrodlo: X11 misc-fixed 5x8 (pakiet xfonts-base). To font ZAPROJEKTOWANY na
siatce pikselowej, nie skalowany z TTF — przy 5x8 daje czytelne glify, czego
downscaling DejaVuSansMono nie potrafi (sprawdzone: przy 4-5 px szerokosci
progowanie antyaliasingu rozmywa ksztalty do nierozpoznawalnosci).

Format: 5 bajtow na znak, kolumnowo, bit 0 = gorny wiersz. Zakres ASCII
0x20..0x7E (95 znakow) = 475 B we flashu. Advance 6 px -> 26 znakow na linie.

Uzycie:
    python3 tools/font2c.py [--preview]
"""

import argparse
import gzip
import io
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PcfFontFile

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "firmware" / "src" / "display"

PCF = Path("/usr/share/fonts/X11/misc/5x8.pcf.gz")

CW, CH = 5, 8       # komorka znaku
ADVANCE = 6         # CW + 1 px odstepu
FIRST, LAST = 0x20, 0x7E

PAD = 8


def load_pcf(path: Path):
    if not path.exists():
        raise SystemExit(f"brak {path} — zainstaluj: sudo apt install xfonts-base")
    with gzip.open(path, "rb") as f:
        data = io.BytesIO(f.read())
    pcf = PcfFontFile.PcfFontFile(data)
    tmp = Path(tempfile.mkdtemp()) / "font5x8"
    pcf.save(str(tmp))
    return ImageFont.load(str(tmp) + ".pil")


def raster(font, ch):
    """Rasteryzuje znak w stalym ukladzie. Font bitmapowy -> brak antyaliasingu."""
    img = Image.new("L", (PAD * 3, PAD * 3), 0)
    ImageDraw.Draw(img).text((PAD, PAD), ch, fill=255, font=font)
    return img.point(lambda v: 255 if v >= 128 else 0)


def common_window(font, codes):
    """
    Okno komorki = unia bboxow wszystkich glifow przy wspolnym punkcie
    odniesienia, dzieki czemu linia bazowa jest jedna dla calego fontu
    i znaki z podciagiem (g, p, q, y) nie skacza wzgledem reszty.
    """
    boxes = [b for b in (raster(font, chr(c)).getbbox() for c in codes) if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def render_glyph(font, ch, win):
    px = raster(font, ch).load()
    wx, wy = win[0], win[1]
    cols = [0] * CW
    for gx in range(CW):
        for gy in range(CH):
            if px[wx + gx, wy + gy]:
                cols[gx] |= (1 << gy)
    return cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    font = load_pcf(PCF)
    codes = list(range(FIRST, LAST + 1))
    win = common_window(font, codes)
    ww, wh = win[2] - win[0], win[3] - win[1]
    if ww > CW or wh > CH:
        raise SystemExit(f"glify nie mieszcza sie w {CW}x{CH}: potrzeba {ww}x{wh}")
    print(f"  okno glifu: {ww}x{wh} w komorce {CW}x{CH}, advance {ADVANCE} px "
          f"-> {160 // ADVANCE} znakow na linie")

    glyphs = {c: render_glyph(font, chr(c), win) for c in codes}

    if args.preview:
        for code in codes:
            cols = glyphs[code]
            print(f"--- {chr(code)!r} ---")
            for y in range(CH):
                print("".join("#" if cols[x] & (1 << y) else "." for x in range(CW)))

    c = ['// WYGENEROWANE PRZEZ tools/font2c.py — NIE EDYTOWAC RECZNIE',
         '#include "font_gen.h"', "",
         "const uint8_t co_font[CO_FONT_COUNT][CO_FONT_W] = {"]
    for code in codes:
        ch = chr(code)
        label = ch.replace("\\", "\\\\").replace("'", "\\'")
        c.append("    { " + ", ".join(f"0x{v:02x}" for v in glyphs[code]) +
                 f" }},  // '{label}'")
    c.append("};")

    h = f"""// WYGENEROWANE PRZEZ tools/font2c.py — NIE EDYTOWAC RECZNIE
#ifndef CO_FONT_GEN_H
#define CO_FONT_GEN_H

#include <stdint.h>

#define CO_FONT_W       {CW}
#define CO_FONT_H       {CH}
#define CO_FONT_ADVANCE {ADVANCE}
#define CO_FONT_FIRST   0x{FIRST:02X}
#define CO_FONT_LAST    0x{LAST:02X}
#define CO_FONT_COUNT   ({LAST} - {FIRST} + 1)

// {CW} bajtow na znak, kolumnowo; bit 0 = gorny wiersz
extern const uint8_t co_font[CO_FONT_COUNT][CO_FONT_W];

#endif // CO_FONT_GEN_H
"""

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "font_gen.c").write_text("\n".join(c) + "\n", encoding="utf-8")
    (OUT_DIR / "font_gen.h").write_text(h, encoding="utf-8")

    empty = [chr(x) for x in range(0x21, 0x7F) if not any(glyphs[x])]
    print(f"  {len(codes)} znakow, {len(codes) * CW} B we flashu")
    if empty:
        print(f"  UWAGA: puste glify: {''.join(empty)}")
    print(f"  zapisano: {OUT_DIR / 'font_gen.c'}")


if __name__ == "__main__":
    main()
