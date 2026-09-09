#include "usb_cdc.h"

#include "pico/stdlib.h"
#include "pico/stdio_usb.h"

// UWAGA: pico_stdio potrafi tlumaczyc '\n' na "\r\n", co rozwaliloby ramke
// binarna. Wylaczamy to jawnie przy inicjalizacji (patrz co_cdc_init).

static co_rx_t s_rx;

void co_cdc_init(co_msg_cb cb, void *ctx)
{
    co_rx_init(&s_rx, cb, ctx);
    stdio_set_translate_crlf(&stdio_usb, false);
}

bool co_cdc_linked(void)
{
    return stdio_usb_connected();
}

void co_cdc_poll(void)
{
    for (;;) {
        const int c = getchar_timeout_us(0);
        if (c == PICO_ERROR_TIMEOUT) break;
        co_rx_byte(&s_rx, (uint8_t)c);
    }
}

void co_cdc_send(uint8_t type, const uint8_t *p, size_t len)
{
    uint8_t frame[CO_MAX_FRAME];
    const size_t n = co_frame_encode(type, p, len, frame, sizeof frame);
    if (!n) return;
    for (size_t i = 0; i < n; i++) putchar_raw(frame[i]);
    stdio_flush();
}
