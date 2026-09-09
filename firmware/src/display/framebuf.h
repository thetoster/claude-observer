// Framebuffer RGB565 160x80 + rysowanie zasobow z assets_gen.
// Kod celowo wolny od zaleznosci na pico-sdk — ten sam plik kompiluje sie
// w firmware i w harnessie renderujacym na hoscie (tools/render_host.c).
#ifndef CO_FRAMEBUF_H
#define CO_FRAMEBUF_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "assets_gen.h"

typedef struct {
    uint16_t *px;       // CO_SCREEN_W * CO_SCREEN_H, RGB565
    uint16_t  w, h;
} co_fb_t;

#define CO_RGB(r, g, b) \
    ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))

#define CO_BLACK CO_RGB(0, 0, 0)
#define CO_WHITE CO_RGB(255, 255, 255)

void co_fb_clear(co_fb_t *fb, uint16_t color);
void co_fb_px(co_fb_t *fb, int x, int y, uint16_t color);
void co_fb_rect(co_fb_t *fb, int x, int y, int w, int h, uint16_t color);

// Rysuje obraz na jego wlasnej pozycji (img->x, img->y) przesunietej o (dx, dy).
// Piksele o indeksie 0 sa pomijane, gdy obraz ma flage CO_IMG_TRANSPARENT.
void co_fb_draw(co_fb_t *fb, const co_image_t *img, int dx, int dy);

// Jak wyzej, ale rysuje tylko te piksele, dla ktorych keep(x, y, ctx) == true.
// Wspolrzedne przekazywane do keep() sa lokalne wzgledem obrazu (0..w-1, 0..h-1).
typedef bool (*co_mask_fn)(int x, int y, void *ctx);
void co_fb_draw_masked(co_fb_t *fb, const co_image_t *img, int dx, int dy,
                       co_mask_fn keep, void *ctx);

// Klatka animacji dla zadanego czasu (ms od startu). Zwraca NULL dla anim == NULL.
const co_image_t *co_anim_frame(const co_anim_t *anim, uint32_t t_ms);

#endif // CO_FRAMEBUF_H
