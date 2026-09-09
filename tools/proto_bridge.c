// Most testowy: czyta strumien bajtow ze stdin, dekoduje ramki i wypisuje je
// na stdout jako linie "OK <type> <payload-hex>". Tryb `encode` robi odwrotnie:
// czyta linie "<type> <hex>" i wypluwa zakodowane ramki binarnie.
// Sluzy do krzyzowej weryfikacji z host/co_observer/proto.py.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "proto.h"

static void on_msg(uint8_t type, const uint8_t *p, size_t len, void *ctx)
{
    (void)ctx;
    printf("OK %02x ", type);
    for (size_t i = 0; i < len; i++) printf("%02x", p[i]);
    printf("\n");
}

int main(int argc, char **argv)
{
    const bool enc = (argc > 1 && strcmp(argv[1], "encode") == 0);

    if (enc) {
        char line[2048];
        while (fgets(line, sizeof line, stdin)) {
            unsigned type;
            char hex[1600] = {0};
            if (sscanf(line, "%x %1599s", &type, hex) < 1) continue;
            uint8_t payload[CO_MAX_PAYLOAD];
            size_t n = strlen(hex) / 2;
            if (n > CO_MAX_PAYLOAD) return 2;
            for (size_t i = 0; i < n; i++) {
                unsigned v; sscanf(&hex[i * 2], "%2x", &v); payload[i] = (uint8_t)v;
            }
            uint8_t out[CO_MAX_FRAME];
            size_t m = co_frame_encode((uint8_t)type, payload, n, out, sizeof out);
            if (!m) return 3;
            fwrite(out, 1, m, stdout);
        }
        return 0;
    }

    co_rx_t rx;
    co_rx_init(&rx, on_msg, NULL);
    int c;
    while ((c = fgetc(stdin)) != EOF) co_rx_byte(&rx, (uint8_t)c);
    fprintf(stderr, "ok=%u crc_err=%u overrun=%u\n",
            rx.n_ok, rx.n_crc_err, rx.n_overrun);
    return 0;
}
