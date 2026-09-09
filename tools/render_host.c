// Harness renderujacy: kompiluje ten sam kod co firmware, ale na hoscie,
// i zapisuje wynik jako PPM (konwertowane potem do PNG przez render.sh).
//
// Pozwala obejrzec kazdy ekran BEZ fizycznego wyswietlacza — kluczowe przy
// braku sondy SWD (D9), bo przenosi debug grafiki z plytki na PC.
//
// Kompilacja: patrz tools/render.sh
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "framebuf.h"
#include "widgets.h"

static uint16_t g_px[CO_SCREEN_W * CO_SCREEN_H];
static co_fb_t  g_fb = { g_px, CO_SCREEN_W, CO_SCREEN_H };

static void save_ppm(const char *path)
{
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    fprintf(f, "P6\n%d %d\n255\n", CO_SCREEN_W, CO_SCREEN_H);
    for (int i = 0; i < CO_SCREEN_W * CO_SCREEN_H; i++) {
        const uint16_t c = g_px[i];
        const int r5 = (c >> 11) & 0x1F, g6 = (c >> 5) & 0x3F, b5 = c & 0x1F;
        // replikacja bitow — tak samo jak robi to kontroler LCD
        const unsigned char rgb[3] = {
            (unsigned char)((r5 << 3) | (r5 >> 2)),
            (unsigned char)((g6 << 2) | (g6 >> 4)),
            (unsigned char)((b5 << 3) | (b5 >> 2)),
        };
        fwrite(rgb, 1, 3, f);
    }
    fclose(f);
}

// Pasek instancji: zaslania dolne 12 px animacji (D8).
#define BAR_H 12
#define BAR_Y (CO_SCREEN_H - BAR_H)

#define PIP_W 5
#define PIP_PITCH 6
#define BAT_RESERVE 20          // miejsce na ikone baterii po prawej

typedef enum { ST_WORKING, ST_IDLE, ST_NEED_INPUT } inst_state_t;

typedef struct {
    const char  *label;
    inst_state_t state;
} inst_t;

static uint16_t state_color(inst_state_t s)
{
    switch (s) {
        case ST_WORKING:    return CO_RGB(235, 110,  90);   // jak animacja working
        case ST_NEED_INPUT: return CO_RGB( 90, 170, 245);   // jak animacja question
        default:            return CO_RGB(110, 110, 120);   // idle — wygaszony
    }
}

// Pasek: po lewej po jednym "pipie" na instancje (kolor = stan, wybrany wyzszy
// i z podkresleniem), po prawej etykieta WYBRANEJ instancji. Tylko jedna
// etykieta, bo 8 nazw na 160 px sie nie zmiesci — patrz §7.6 planu.
static void draw_instance_bar(const inst_t *insts, int n, int selected)
{
    co_fb_rect(&g_fb, 0, BAR_Y, CO_SCREEN_W, BAR_H, CO_RGB(20, 20, 28));

    for (int i = 0; i < n; i++) {
        const int x = 2 + i * PIP_PITCH;
        const uint16_t c = state_color(insts[i].state);
        if (i == selected) {
            co_fb_rect(&g_fb, x, BAR_Y + 2, PIP_W, 6, c);
            co_fb_rect(&g_fb, x, BAR_Y + 9, PIP_W, 1, CO_WHITE);
        } else {
            co_fb_rect(&g_fb, x, BAR_Y + 4, PIP_W, 4, c);
        }
    }

    const int lx = 2 + n * PIP_PITCH + 4;
    const int avail = CO_SCREEN_W - BAT_RESERVE - lx;
    char buf[32];
    co_text_fit(buf, sizeof buf, insts[selected].label, avail / CO_FONT_ADVANCE);
    co_fb_text(&g_fb, lx, BAR_Y + 2, buf, CO_WHITE);
}

static void draw_battery_low(void)
{
    // prawy dolny rog, na pasku (spec 11)
    co_fb_draw(&g_fb, &co_img_battery_low,
               CO_SCREEN_W - co_img_battery_low.w - 3 - co_img_battery_low.x,
               BAR_Y + 3 - co_img_battery_low.y);
}

// --- ekrany --------------------------------------------------------------

static void screen_main_anim(const co_anim_t *anim, uint32_t t_ms,
                             const inst_t *insts, int n_inst, int selected,
                             bool bat_low, const char *out)
{
    co_fb_clear(&g_fb, CO_BLACK);
    co_fb_draw(&g_fb, co_anim_frame(anim, t_ms), 0, 0);   // tlo: pelny kadr
    if (n_inst > 1) draw_instance_bar(insts, n_inst, selected);  // na wierzchu (D2/D8)
    if (bat_low)    draw_battery_low();
    save_ppm(out);
}

static void screen_no_link(bool visible, const char *out)
{
    // spec 13 / §7.5: bez animacji, bez paska; ikona wysrodkowana, miga 0.5 Hz
    co_fb_clear(&g_fb, CO_BLACK);
    if (visible) {
        const int x = (CO_SCREEN_W - co_img_no_bt.w) / 2 - co_img_no_bt.x;
        const int y = (CO_SCREEN_H - co_img_no_bt.h) / 2 - co_img_no_bt.y;
        co_fb_draw(&g_fb, &co_img_no_bt, x, y);
    }
    save_ppm(out);
}

static void screen_usage(uint8_t ctx_pct, uint8_t week_pct, const char *out)
{
    co_fb_clear(&g_fb, CO_BLACK);
    // uklad wg makiety images/sessions.png: ciastko po lewej, stos po prawej
    co_draw_cookie(&g_fb, &co_img_cookie, &co_img_cookie_used, ctx_pct,
                   16 - co_img_cookie.x, 11 - co_img_cookie.y);
    co_draw_stack(&g_fb, &co_img_cookie_stack, &co_img_cookie_stack_used, week_pct,
                  88 - co_img_cookie_stack.x, 15 - co_img_cookie_stack.y);
    save_ppm(out);
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "tools/render_out";
    char p[512];

#define OUT(fmt, ...) (snprintf(p, sizeof p, "%s/" fmt, dir, ##__VA_ARGS__), p)

    static const inst_t one[] = { { "claude_observer", ST_WORKING } };

    // animacje — wszystkie klatki
    for (int i = 0; i < 4; i++) {
        const uint32_t t = (uint32_t)i * 200;   // D14: 200 ms/klatke
        screen_main_anim(&co_anim_working,  t, one, 1, 0, false, OUT("main_working_%d.ppm", i + 1));
        screen_main_anim(&co_anim_idle,     t, one, 1, 0, false, OUT("main_idle_%d.ppm", i + 1));
        screen_main_anim(&co_anim_question, t, one, 1, 0, false, OUT("main_question_%d.ppm", i + 1));
    }

    // --- rozroznianie rownoleglych sesji (§7.6 planu) ---

    // (a) rozne katalogi -> etykieta = basename cwd
    static const inst_t diff_dirs[] = {
        { "claude_observer", ST_WORKING },
        { "drone",           ST_NEED_INPUT },
        { "edoreczenia",     ST_WORKING },
    };
    screen_main_anim(&co_anim_question, 0, diff_dirs, 3, 1, false,
                     OUT("bar_a_rozne_katalogi.ppm"));

    // (b) ten sam katalog -> dyskryminator #n nadawany przez daemona
    static const inst_t same_dir[] = {
        { "claude_obs#1", ST_WORKING },
        { "claude_obs#2", ST_NEED_INPUT },
    };
    screen_main_anim(&co_anim_question, 0, same_dir, 2, 1, false,
                     OUT("bar_b_ten_sam_katalog.ppm"));

    // (c) etykieta nadana recznie przez CO_LABEL
    static const inst_t labeled[] = {
        { "frontend", ST_WORKING },
        { "backend",  ST_WORKING },
        { "infra",    ST_NEED_INPUT },
    };
    screen_main_anim(&co_anim_working, 0, labeled, 3, 2, true,
                     OUT("bar_c_co_label.ppm"));

    // (d) maksimum 8 instancji + dluga nazwa do obciecia
    static const inst_t many[] = {
        { "a", ST_WORKING },      { "b", ST_WORKING },
        { "c", ST_IDLE },         { "d", ST_WORKING },
        { "e", ST_NEED_INPUT },   { "f", ST_WORKING },
        { "g", ST_WORKING },      { "bardzo_dluga_nazwa_projektu", ST_NEED_INPUT },
    };
    screen_main_anim(&co_anim_question, 0, many, 8, 7, false,
                     OUT("bar_d_osiem.ppm"));

    // spec 13 — obie fazy migania
    screen_no_link(true,  OUT("no_link_on.ppm"));
    screen_no_link(false, OUT("no_link_off.ppm"));

    // ekran usage — przemiatanie procentow
    const uint8_t steps[] = { 0, 25, 40, 50, 75, 90, 100 };
    for (unsigned i = 0; i < sizeof steps; i++)
        screen_usage(steps[i], steps[i], OUT("usage_%03d.ppm", steps[i]));

    // przypadek mieszany z planu: kontekst 40%, tydzien 61%
    screen_usage(40, 61, OUT("usage_mixed.ppm"));

    printf("wyrenderowano do %s\n", dir);
    return 0;
}
