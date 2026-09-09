#include "widgets.h"

#include <math.h>

// M_PI nie jest czescia C11 — definiujemy wlasne, zeby nie zalezec od _GNU_SOURCE
#define CO_PI 3.14159265358979323846f

// ---------------------------------------------------------------------------
// wykres kolowy
// ---------------------------------------------------------------------------

typedef struct {
    float cx, cy;       // srodek obrazu we wspolrzednych lokalnych
    float limit;        // ulamek 0..1 obwodu
    bool  inside;       // true -> zachowaj piksele PONIZEJ limitu
} pie_ctx_t;

// Ulamek obwodu liczony od godziny 12, zgodnie z ruchem wskazowek zegara.
static float pie_frac(const pie_ctx_t *c, int x, int y)
{
    // +0.5 -> srodek piksela; os Y ekranu rosnie w dol, stad (cy - y)
    const float dx = (float)x + 0.5f - c->cx;
    const float dy = c->cy - ((float)y + 0.5f);
    float a = atan2f(dx, dy);                 // 0 na godzinie 12, rosnie zgodnie z zegarem
    if (a < 0.0f) a += 2.0f * CO_PI;
    return a / (2.0f * CO_PI);
}

static bool pie_keep(int x, int y, void *ctx)
{
    const pie_ctx_t *c = (const pie_ctx_t *)ctx;
    const bool below = pie_frac(c, x, y) < c->limit;
    return c->inside ? below : !below;
}

void co_draw_cookie(co_fb_t *fb, const co_image_t *fresh, const co_image_t *used,
                    uint8_t pct, int dx, int dy)
{
    if (pct > 100) pct = 100;

    // czesc dostepna = 100 - pct, rysowana jako pierwsza (od godziny 12)
    const float avail = (float)(100 - pct) / 100.0f;

    if (fresh) {
        pie_ctx_t c = { fresh->w / 2.0f, fresh->h / 2.0f, avail, true };
        co_fb_draw_masked(fb, fresh, dx, dy, pie_keep, &c);
    }
    if (used) {
        pie_ctx_t c = { used->w / 2.0f, used->h / 2.0f, avail, false };
        co_fb_draw_masked(fb, used, dx, dy, pie_keep, &c);
    }
}

// ---------------------------------------------------------------------------
// wykres slupkowy
// ---------------------------------------------------------------------------

typedef struct {
    int  split;         // wiersz graniczny (lokalny y)
    bool below;         // true -> zachowaj wiersze OD split w dol
} bar_ctx_t;

static bool bar_keep(int x, int y, void *ctx)
{
    (void)x;
    const bar_ctx_t *c = (const bar_ctx_t *)ctx;
    return c->below ? (y >= c->split) : (y < c->split);
}

void co_draw_stack(co_fb_t *fb, const co_image_t *fresh, const co_image_t *used,
                   uint8_t pct, int dx, int dy)
{
    if (pct > 100) pct = 100;

    if (fresh) {
        // dostepne: od dolu do (100-pct)% wysokosci
        const int split = fresh->h - (fresh->h * (100 - pct)) / 100;
        bar_ctx_t c = { split, true };
        co_fb_draw_masked(fb, fresh, dx, dy, bar_keep, &c);
    }
    if (used) {
        // zuzyte: gorne pct% wysokosci
        const int split = used->h - (used->h * (100 - pct)) / 100;
        bar_ctx_t c = { split, false };
        co_fb_draw_masked(fb, used, dx, dy, bar_keep, &c);
    }
}
