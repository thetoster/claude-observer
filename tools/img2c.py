#!/usr/bin/env python3
"""
img2c.py — konwersja zasobow PNG z images/ do tablic C we flashu.

Format wyjsciowy: paleta RGB565 + indeksy 8bpp skompresowane algorytmem
PackBits (§8 planu). Klatki animacji sa przycinane do wspolnego bounding boxa
(unia po wszystkich klatkach, zeby animacja nie skakala) i zapisywane wraz
z offsetem (x, y) wzgledem pelnego kadru 160x80.

Uzycie:
    python3 tools/img2c.py                 # generuje firmware/src/display/assets_gen.{c,h}
    python3 tools/img2c.py --verify        # dodatkowo dekoduje i porownuje z zrodlem
"""

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "images"
OUT_DIR = ROOT / "firmware" / "src" / "display"

SCREEN_W, SCREEN_H = 160, 80

# D14: 5 fps -> 200 ms na klatke
FRAME_MS = 200

ANIMATIONS = {
    "working": ["working_1.png", "working_2.png", "working_3.png", "working_4.png"],
    "idle": ["idle_1.png", "idle_2.png", "idle_3.png", "idle_4.png"],
    "question": ["question_1.png", "question_2.png", "question_3.png", "question_4.png"],
}

STATIC = [
    "cookie.png",
    "cookie_used.png",
    "cookie_stack.png",
    "cookie_stack_used.png",
    "battery_low.png",
    "no_bt.png",
]

FLAG_TRANSPARENT = 0x01  # indeks 0 palety = piksel przezroczysty

ALPHA_THRESHOLD = 128


# --------------------------------------------------------------------------
# konwersja kolorow
# --------------------------------------------------------------------------

def rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def rgb565_to_rgb888(c: int) -> tuple:
    """Odwrotnosc rgb565() z replikacja bitow — tak samo robi kontroler LCD."""
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


# --------------------------------------------------------------------------
# PackBits
# --------------------------------------------------------------------------

def packbits_encode(data: bytes) -> bytes:
    """
    Kodowanie:
      c & 0x80  -> powtorzenie: nastepny bajt powielony (c & 0x7f) + 2 razy   (2..129)
      inaczej   -> literal: nastepne (c + 1) bajtow                           (1..128)
    """
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        # policz dlugosc biezacej serii powtorzen
        run = 1
        while i + run < n and data[i + run] == data[i] and run < 129:
            run += 1

        if run >= 2:
            out.append(0x80 | (run - 2))
            out.append(data[i])
            i += run
            continue

        # zbieraj literaly az do momentu, gdy oplaca sie zaczac serie
        start = i
        while i < n:
            nxt = 1
            while i + nxt < n and data[i + nxt] == data[i] and nxt < 3:
                nxt += 1
            if nxt >= 3:          # trzy takie same -> przerwij literal
                break
            i += 1
            if i - start == 128:
                break
        lit = data[start:i]
        out.append(len(lit) - 1)
        out.extend(lit)
    return bytes(out)


def packbits_decode(data: bytes, expected: int) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data) and len(out) < expected:
        c = data[i]
        i += 1
        if c & 0x80:
            out.extend([data[i]] * ((c & 0x7F) + 2))
            i += 1
        else:
            cnt = c + 1
            out.extend(data[i:i + cnt])
            i += cnt
    return bytes(out)


# --------------------------------------------------------------------------
# przetwarzanie obrazow
# --------------------------------------------------------------------------

class Asset:
    def __init__(self, name, x, y, w, h, palette, indices, transparent):
        self.name = name
        self.x, self.y, self.w, self.h = x, y, w, h
        self.palette = palette          # lista RGB565
        self.indices = indices          # bytes, w*h
        self.transparent = transparent
        self.rle = packbits_encode(indices)

    @property
    def flags(self):
        return FLAG_TRANSPARENT if self.transparent else 0

    @property
    def raw_size(self):
        return self.w * self.h

    @property
    def packed_size(self):
        return len(self.rle) + len(self.palette) * 2


def load_rgba(path: Path) -> Image.Image:
    im = Image.open(path)
    return im.convert("RGBA")


def content_bbox(im: Image.Image) -> tuple:
    """
    Bounding box tresci. Dla obrazow z alfa — po kanale alfa.
    Dla nieprzezroczystych — po odcieciu jednolitego tla (koloru piksela 0,0).
    """
    alpha = im.getchannel("A")
    if alpha.getextrema()[0] < 255:
        bb = alpha.point(lambda a: 255 if a >= ALPHA_THRESHOLD else 0).getbbox()
        return bb if bb else (0, 0, im.width, im.height)

    bg = im.getpixel((0, 0))
    bg_img = Image.new("RGBA", im.size, bg)
    from PIL import ImageChops
    bb = ImageChops.difference(im, bg_img).convert("L").getbbox()
    return bb if bb else (0, 0, im.width, im.height)


def build_asset(name: str, im: Image.Image, box: tuple) -> Asset:
    x0, y0, x1, y1 = box
    crop = im.crop(box)
    w, h = crop.size
    px = crop.load()

    has_alpha = crop.getchannel("A").getextrema()[0] < 255
    max_colors = 255 if has_alpha else 256

    def opaque(x, y):
        return not has_alpha or px[x, y][3] >= ALPHA_THRESHOLD

    # ile unikalnych kolorow po konwersji do RGB565? (rozne RGB888 moga sie zlac)
    uniq = {rgb565(*px[x, y][:3])
            for y in range(h) for x in range(w) if opaque(x, y)}

    if len(uniq) > max_colors:
        # Kwantyzacja. Przezroczyste piksele wypelniamy najczestszym kolorem
        # nieprzezroczystym, zeby nie zasmiecaly palety wlasnym tlem.
        rgb = crop.convert("RGB")
        if has_alpha:
            from collections import Counter
            common = Counter(px[x, y][:3]
                             for y in range(h) for x in range(w)
                             if opaque(x, y)).most_common(1)[0][0]
            fill = Image.new("RGB", crop.size, common)
            mask = crop.getchannel("A").point(
                lambda a: 255 if a >= ALPHA_THRESHOLD else 0)
            rgb = Image.composite(rgb, fill, mask)
        q = rgb.quantize(colors=max_colors,
                         method=Image.Quantize.MEDIANCUT,
                         dither=Image.Dither.NONE)
        qpal = q.getpalette()
        qpx = q.load()
        src = lambda x, y: tuple(qpal[qpx[x, y] * 3: qpx[x, y] * 3 + 3])
    else:
        src = lambda x, y: px[x, y][:3]

    palette, lookup = [], {}
    if has_alpha:
        palette.append(0x0000)          # indeks 0 zarezerwowany na przezroczystosc
        lookup[None] = 0

    indices = bytearray()
    for y in range(h):
        for x in range(w):
            if not opaque(x, y):
                indices.append(0)
                continue
            c = rgb565(*src(x, y))
            idx = lookup.get(c)
            if idx is None:
                idx = len(palette)
                lookup[c] = idx
                palette.append(c)
            indices.append(idx)

    return Asset(name, x0, y0, w, h, palette, bytes(indices), has_alpha)


def union_box(boxes) -> tuple:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


# --------------------------------------------------------------------------
# generowanie C
# --------------------------------------------------------------------------

def c_array(data: bytes, indent="    ", per_line=16) -> str:
    lines = []
    for i in range(0, len(data), per_line):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i:i + per_line])
        lines.append(indent + chunk + ",")
    return "\n".join(lines)


def c_palette(pal, indent="    ", per_line=8) -> str:
    lines = []
    for i in range(0, len(pal), per_line):
        chunk = ", ".join(f"0x{c:04x}" for c in pal[i:i + per_line])
        lines.append(indent + chunk + ",")
    return "\n".join(lines)


def emit(assets, anims) -> tuple:
    h = ["""// WYGENEROWANE PRZEZ tools/img2c.py — NIE EDYTOWAC RECZNIE
#ifndef CO_ASSETS_GEN_H
#define CO_ASSETS_GEN_H

#include <stdint.h>

#define CO_SCREEN_W %d
#define CO_SCREEN_H %d

#define CO_IMG_TRANSPARENT 0x01

typedef struct {
    uint8_t         x, y;        // pozycja w kadrze 160x80
    uint8_t         w, h;        // rozmiar po przycieciu
    uint8_t         flags;       // CO_IMG_TRANSPARENT
    uint8_t         n_colors;
    const uint16_t *palette;     // RGB565
    const uint8_t  *rle;         // PackBits nad indeksami palety
    uint16_t        rle_len;
} co_image_t;

typedef struct {
    const co_image_t *frames;
    uint8_t           n_frames;
    uint16_t          frame_ms;
} co_anim_t;
""" % (SCREEN_W, SCREEN_H)]

    c = ['// WYGENEROWANE PRZEZ tools/img2c.py — NIE EDYTOWAC RECZNIE',
         '#include "assets_gen.h"', ""]

    for a in assets:
        c.append(f"// {a.name}: {a.w}x{a.h} @ ({a.x},{a.y}), "
                 f"{len(a.palette)} kol., {a.raw_size} -> {a.packed_size} B")
        c.append(f"static const uint16_t {a.name}_pal[] = {{")
        c.append(c_palette(a.palette))
        c.append("};")
        c.append(f"static const uint8_t {a.name}_rle[] = {{")
        c.append(c_array(a.rle))
        c.append("};")
        c.append("")

    # obrazy statyczne
    for a in assets:
        if a.name.startswith(("anim_",)):
            continue
        h.append(f"extern const co_image_t co_img_{a.name};")
        c.append(f"const co_image_t co_img_{a.name} = {{")
        c.append(f"    .x = {a.x}, .y = {a.y}, .w = {a.w}, .h = {a.h},")
        c.append(f"    .flags = 0x{a.flags:02x}, .n_colors = {len(a.palette)},")
        c.append(f"    .palette = {a.name}_pal, .rle = {a.name}_rle, "
                 f".rle_len = {len(a.rle)},")
        c.append("};")
        c.append("")

    # animacje
    h.append("")
    for aname, frames in anims.items():
        c.append(f"static const co_image_t anim_{aname}_frames[] = {{")
        for f in frames:
            c.append("    {")
            c.append(f"        .x = {f.x}, .y = {f.y}, .w = {f.w}, .h = {f.h},")
            c.append(f"        .flags = 0x{f.flags:02x}, .n_colors = {len(f.palette)},")
            c.append(f"        .palette = {f.name}_pal, .rle = {f.name}_rle, "
                     f".rle_len = {len(f.rle)},")
            c.append("    },")
        c.append("};")
        c.append(f"const co_anim_t co_anim_{aname} = {{")
        c.append(f"    .frames = anim_{aname}_frames, .n_frames = {len(frames)}, "
                 f".frame_ms = {FRAME_MS},")
        c.append("};")
        c.append("")
        h.append(f"extern const co_anim_t co_anim_{aname};")

    h.append("")
    h.append("#endif // CO_ASSETS_GEN_H")
    return "\n".join(h) + "\n", "\n".join(c) + "\n"


# --------------------------------------------------------------------------

def verify(asset: Asset, im: Image.Image, box: tuple) -> float:
    """
    Dwie kontrole:
      1. round-trip PackBits musi byc bezstratny (twardy warunek),
      2. blad koloru wzgledem zrodla — zero bez kwantyzacji, male przy kwantyzacji.
    Zwraca sredni blad na kanal (0..255).
    """
    decoded = packbits_decode(asset.rle, asset.raw_size)
    if len(decoded) != asset.raw_size:
        raise SystemExit(f"{asset.name}: dekoder zwrocil {len(decoded)} B, "
                         f"oczekiwano {asset.raw_size}")
    if decoded != asset.indices:
        raise SystemExit(f"{asset.name}: round-trip PackBits niezgodny")

    crop = im.crop(box)
    px = crop.load()
    err = n = 0
    for y in range(asset.h):
        for x in range(asset.w):
            r, g, b, a = px[x, y]
            idx = decoded[y * asset.w + x]
            if asset.transparent and a < ALPHA_THRESHOLD:
                if idx != 0:
                    raise SystemExit(f"{asset.name}: piksel przezroczysty "
                                     f"({x},{y}) ma indeks {idx}, nie 0")
                continue
            dr, dg, db = rgb565_to_rgb888(asset.palette[idx])
            err += abs(dr - r) + abs(dg - g) + abs(db - b)
            n += 3
    return err / n if n else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="dekoduj i porownaj z zrodlem")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    assets, anims, errs = [], {}, []
    total_raw = total_packed = 0

    # animacje — wspolny bbox dla wszystkich klatek
    for aname, files in ANIMATIONS.items():
        paths = [IMAGES / f for f in files]
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            sys.exit(f"brak plikow: {', '.join(missing)}")
        ims = [load_rgba(p) for p in paths]
        box = union_box([content_bbox(i) for i in ims])
        frames = []
        for p, im in zip(paths, ims):
            a = build_asset(p.stem, im, box)
            if args.verify:
                errs.append((a.name, verify(a, im, box)))
            frames.append(a)
            assets.append(a)
            total_raw += a.raw_size
            total_packed += a.packed_size
        anims[aname] = frames
        print(f"  anim {aname:9s} bbox={box} {frames[0].w}x{frames[0].h} "
              f"x{len(frames)} klatek")

    # obrazy statyczne
    for fname in STATIC:
        p = IMAGES / fname
        if not p.exists():
            sys.exit(f"brak pliku: {fname}")
        im = load_rgba(p)
        box = content_bbox(im)
        a = build_asset(p.stem, im, box)
        if args.verify:
            errs.append((a.name, verify(a, im, box)))
        assets.append(a)
        total_raw += a.raw_size
        total_packed += a.packed_size
        print(f"  img  {p.stem:20s} {a.w}x{a.h} @({a.x},{a.y}) "
              f"{len(a.palette):3d} kol. {a.raw_size:6d} -> {a.packed_size:6d} B")

    h_src, c_src = emit(assets, anims)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "assets_gen.h").write_text(h_src, encoding="utf-8")
    (args.out / "assets_gen.c").write_text(c_src, encoding="utf-8")

    ratio = total_raw / total_packed if total_packed else 0
    print(f"\n  razem: {total_raw} B surowo -> {total_packed} B "
          f"(x{ratio:.1f}), {len(assets)} obrazow")
    print(f"  zapisano: {args.out / 'assets_gen.c'}")
    if args.verify:
        worst = max(errs, key=lambda e: e[1])
        print(f"  round-trip PackBits: OK ({len(errs)} obrazow, bezstratnie)")
        print(f"  blad koloru vs zrodlo RGB888: najgorszy {worst[0]} = "
              f"{worst[1]:.2f}/255 sredniego na kanal")
        print(f"  (sam RGB565 daje ~1.7 — kroki 8/4/8; powyzej tego to kwantyzacja palety)")


if __name__ == "__main__":
    main()
