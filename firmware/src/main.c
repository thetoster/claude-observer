// claude-observer — szkielet M0.
// Sterownik ST7735S, wejscia i BLE dochodza w kolejnych etapach (M1/M3/M6).
// Na tym etapie weryfikujemy, ze zasoby i renderer linkuja sie w firmware
// i ze binarka miesci sie w budzecie pamieci.
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"

#include "framebuf.h"
#include "widgets.h"
#include "instances.h"
#include "usb_cdc.h"

static uint16_t   g_px[CO_SCREEN_W * CO_SCREEN_H];
static co_fb_t    g_fb = { g_px, CO_SCREEN_W, CO_SCREEN_H };
static co_model_t g_model;
static uint32_t   g_last_rx_ms;      // §7.5: podstawa oceny link_alive

static void on_msg(uint8_t type, const uint8_t *p, size_t len, void *ctx)
{
    (void)ctx;
    g_last_rx_ms = to_ms_since_boot(get_absolute_time());
    switch (type) {
    case CO_MSG_SNAPSHOT: co_model_snapshot(&g_model, p, len); break;
    case CO_MSG_STATE:    co_model_state(&g_model, p, len);    break;
    case CO_MSG_LIMITS:   co_model_limits(&g_model, p, len);   break;
    case CO_MSG_PING:     co_cdc_send(CO_MSG_PONG, p, len);    break;
    default: break;
    }
}

int main(void)
{
    stdio_init_all();
    if (cyw43_arch_init()) return -1;

    co_model_init(&g_model);
    co_cdc_init(on_msg, NULL);

    const uint8_t hello[] = { CO_PROTO_VERSION, 0, 3, 0 };
    co_cdc_send(CO_MSG_HELLO, hello, sizeof hello);

    uint32_t t = 0;
    while (true) {
        co_cdc_poll();

        // Sterownik ST7735S dochodzi w M1 — na razie rysujemy do framebuffera,
        // zeby zweryfikowac sciezke danych: link -> model -> renderer.
        const co_inst_t *sel = g_model.n ? &g_model.insts[g_model.selected] : NULL;
        const co_anim_t *anim = &co_anim_idle;
        if (sel) {
            anim = (sel->state == CO_ST_NEED_INPUT) ? &co_anim_question
                 : (sel->state == CO_ST_WORKING)    ? &co_anim_working
                                                    : &co_anim_idle;
        }
        co_fb_clear(&g_fb, CO_BLACK);
        co_fb_draw(&g_fb, co_anim_frame(anim, t), 0, 0);
        if (co_model_visible_count(&g_model) > 1 && sel)
            co_fb_text(&g_fb, 2, CO_SCREEN_H - 10, sel->label, CO_WHITE);

        t += 50;
        sleep_ms(50);
    }
}
