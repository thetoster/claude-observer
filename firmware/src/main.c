// claude-observer — szkielet M0.
// Sterownik ST7735S, wejscia i BLE dochodza w kolejnych etapach (M1/M3/M6).
// Na tym etapie weryfikujemy, ze zasoby i renderer linkuja sie w firmware
// i ze binarka miesci sie w budzecie pamieci.
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"

#include "framebuf.h"
#include "widgets.h"

static uint16_t g_px[CO_SCREEN_W * CO_SCREEN_H];
static co_fb_t  g_fb = { g_px, CO_SCREEN_W, CO_SCREEN_H };

int main(void)
{
    stdio_init_all();
    if (cyw43_arch_init()) return -1;

    uint32_t t = 0;
    while (true) {
        // ekran glowny: animacja jako tlo (M2 dokonczy kompozycje)
        co_fb_clear(&g_fb, CO_BLACK);
        co_fb_draw(&g_fb, co_anim_frame(&co_anim_working, t), 0, 0);

        printf("claude-observer M0: fb=%u B, klatka %lu\n",
               (unsigned)sizeof g_px, (unsigned long)(t / co_anim_working.frame_ms) % 4);

        t += co_anim_working.frame_ms;
        sleep_ms(co_anim_working.frame_ms);
    }
}
