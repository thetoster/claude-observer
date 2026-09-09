#include "framebuf.h"

#include <string.h>

void co_fb_clear(co_fb_t *fb, uint16_t color)
{
    const int n = fb->w * fb->h;
    for (int i = 0; i < n; i++) fb->px[i] = color;
}

void co_fb_px(co_fb_t *fb, int x, int y, uint16_t color)
{
    if (x < 0 || y < 0 || x >= fb->w || y >= fb->h) return;
    fb->px[y * fb->w + x] = color;
}

void co_fb_rect(co_fb_t *fb, int x, int y, int w, int h, uint16_t color)
{
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            co_fb_px(fb, x + i, y + j, color);
}

// Dekoduje strumien PackBits i wola cb() dla kolejnych pikseli.
// Dekompresja jest strumieniowa — nie alokujemy bufora na cala bitmape.
void co_fb_draw_masked(co_fb_t *fb, const co_image_t *img, int dx, int dy,
                       co_mask_fn keep, void *ctx)
{
    if (!img) return;

    const bool has_alpha = (img->flags & CO_IMG_TRANSPARENT) != 0;
    const int  ox = img->x + dx;
    const int  oy = img->y + dy;
    const int  total = img->w * img->h;

    int pos = 0;                 // indeks piksela w obrazie
    uint16_t i = 0;              // pozycja w strumieniu RLE

    while (pos < total && i < img->rle_len) {
        uint8_t c = img->rle[i++];
        uint8_t run;
        const uint8_t *lit = NULL;
        uint8_t rep = 0;

        if (c & 0x80) {
            run = (uint8_t)((c & 0x7F) + 2);
            rep = img->rle[i++];
        } else {
            run = (uint8_t)(c + 1);
            lit = &img->rle[i];
            i = (uint16_t)(i + run);
        }

        for (uint8_t k = 0; k < run && pos < total; k++, pos++) {
            uint8_t idx = lit ? lit[k] : rep;
            if (has_alpha && idx == 0) continue;

            const int lx = pos % img->w;
            const int ly = pos / img->w;
            if (keep && !keep(lx, ly, ctx)) continue;

            co_fb_px(fb, ox + lx, oy + ly, img->palette[idx]);
        }
    }
}

void co_fb_draw(co_fb_t *fb, const co_image_t *img, int dx, int dy)
{
    co_fb_draw_masked(fb, img, dx, dy, NULL, NULL);
}

const co_image_t *co_anim_frame(const co_anim_t *anim, uint32_t t_ms)
{
    if (!anim || anim->n_frames == 0) return NULL;
    const uint32_t step = anim->frame_ms ? anim->frame_ms : 1;
    return &anim->frames[(t_ms / step) % anim->n_frames];
}

int co_fb_text(co_fb_t *fb, int x, int y, const char *s, uint16_t color)
{
    for (; *s; s++) {
        const unsigned char ch = (unsigned char)*s;
        if (ch < CO_FONT_FIRST || ch > CO_FONT_LAST) { x += CO_FONT_ADVANCE; continue; }
        const uint8_t *g = co_font[ch - CO_FONT_FIRST];
        for (int cx = 0; cx < CO_FONT_W; cx++)
            for (int cy = 0; cy < CO_FONT_H; cy++)
                if (g[cx] & (1u << cy)) co_fb_px(fb, x + cx, y + cy, color);
        x += CO_FONT_ADVANCE;
    }
    return x;
}

int co_text_w(const char *s)
{
    const int n = (int)strlen(s);
    return n ? n * CO_FONT_ADVANCE - 1 : 0;
}

void co_text_fit(char *dst, size_t cap, const char *src, int max_chars)
{
    if (cap == 0) return;
    if (max_chars < 1) { dst[0] = 0; return; }
    if ((size_t)max_chars >= cap) max_chars = (int)cap - 1;

    const int n = (int)strlen(src);
    if (n <= max_chars) { memcpy(dst, src, (size_t)n + 1); return; }

    memcpy(dst, src, (size_t)max_chars - 1);
    dst[max_chars - 1] = '~';       // znacznik obciecia
    dst[max_chars] = 0;
}
