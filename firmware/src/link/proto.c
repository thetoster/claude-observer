#include "proto.h"

#include <string.h>

// CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, bez refleksji, bez xorout.
uint16_t co_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++)
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021)
                                 : (uint16_t)(crc << 1);
    }
    return crc;
}

size_t co_frame_encode(uint8_t type, const uint8_t *payload, size_t len,
                       uint8_t *out, size_t out_cap)
{
    if (len > CO_MAX_PAYLOAD) return 0;
    const size_t total = 2 + 2 + 1 + len + 2;
    if (out_cap < total) return 0;

    size_t i = 0;
    out[i++] = CO_SYNC0;
    out[i++] = CO_SYNC1;
    out[i++] = (uint8_t)(len & 0xFF);
    out[i++] = (uint8_t)(len >> 8);
    out[i++] = type;
    if (len && payload) memcpy(&out[i], payload, len);
    i += len;

    // CRC liczone po `type` + payload — czyli po tym, co niesie tresc
    uint8_t tmp[1 + CO_MAX_PAYLOAD];
    tmp[0] = type;
    if (len && payload) memcpy(&tmp[1], payload, len);
    const uint16_t crc = co_crc16(tmp, 1 + len);

    out[i++] = (uint8_t)(crc & 0xFF);
    out[i++] = (uint8_t)(crc >> 8);
    return i;
}

// ---------------------------------------------------------------------------

void co_rx_init(co_rx_t *rx, co_msg_cb cb, void *ctx)
{
    memset(rx, 0, sizeof *rx);
    rx->cb = cb;
    rx->ctx = ctx;
}

static void rx_reset(co_rx_t *rx)
{
    rx->state = CO_RX_SYNC0;
    rx->len = rx->got = 0;
}

void co_rx_byte(co_rx_t *rx, uint8_t b)
{
    switch (rx->state) {
    case CO_RX_SYNC0:
        if (b == CO_SYNC0) rx->state = CO_RX_SYNC1;
        break;

    case CO_RX_SYNC1:
        // Gdy trafimy na 0xA5 zamiast 0x5A, zostajemy w SYNC1 — to moze byc
        // poczatek prawdziwej ramki po smieciach.
        if (b == CO_SYNC1)      rx->state = CO_RX_LEN0;
        else if (b == CO_SYNC0) rx->state = CO_RX_SYNC1;
        else                    rx->state = CO_RX_SYNC0;
        break;

    case CO_RX_LEN0:
        rx->len = b;
        rx->state = CO_RX_LEN1;
        break;

    case CO_RX_LEN1:
        rx->len |= (uint16_t)b << 8;
        if (rx->len > CO_MAX_PAYLOAD) {   // nie moze byc nasza ramka
            rx->n_overrun++;
            rx_reset(rx);
        } else {
            rx->state = CO_RX_TYPE;
        }
        break;

    case CO_RX_TYPE:
        rx->type = b;
        rx->got = 0;
        rx->state = rx->len ? CO_RX_PAYLOAD : CO_RX_CRC0;
        break;

    case CO_RX_PAYLOAD:
        rx->buf[rx->got++] = b;
        if (rx->got >= rx->len) rx->state = CO_RX_CRC0;
        break;

    case CO_RX_CRC0:
        rx->crc_rx = b;
        rx->state = CO_RX_CRC1;
        break;

    case CO_RX_CRC1: {
        rx->crc_rx |= (uint16_t)b << 8;
        uint8_t tmp[1 + CO_MAX_PAYLOAD];
        tmp[0] = rx->type;
        if (rx->len) memcpy(&tmp[1], rx->buf, rx->len);
        if (co_crc16(tmp, 1 + rx->len) == rx->crc_rx) {
            rx->n_ok++;
            if (rx->cb) rx->cb(rx->type, rx->buf, rx->len, rx->ctx);
        } else {
            rx->n_crc_err++;
        }
        rx_reset(rx);
        break;
    }
    }
}

void co_rx_feed(co_rx_t *rx, const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) co_rx_byte(rx, data[i]);
}

void co_rx_packet(co_rx_t *rx, const uint8_t *data, size_t len)
{
    if (len < 1 || len > 1 + CO_MAX_PAYLOAD) { rx->n_overrun++; return; }
    rx->n_ok++;
    if (rx->cb) rx->cb(data[0], &data[1], len - 1, rx->ctx);
}

// ---------------------------------------------------------------------------

size_t co_build_snapshot(const co_inst_t *insts, uint8_t n,
                         uint8_t *out, size_t cap)
{
    if (n > CO_MAX_INSTANCES) n = CO_MAX_INSTANCES;
    const size_t need = 1u + (size_t)n * CO_INST_REC_LEN;
    if (cap < need) return 0;

    out[0] = n;
    for (uint8_t i = 0; i < n; i++) {
        uint8_t *r = &out[1 + (size_t)i * CO_INST_REC_LEN];
        r[0] = insts[i].id;
        r[1] = insts[i].state;
        r[2] = insts[i].ctx_pct;
        r[3] = insts[i].flags;
        memset(&r[4], 0, CO_LABEL_LEN);
        strncpy((char *)&r[4], insts[i].label, CO_LABEL_LEN - 1);
    }
    return need;
}

bool co_parse_snapshot(const uint8_t *p, size_t len,
                       co_inst_t *out, uint8_t *n_out, uint8_t max)
{
    if (len < 1) return false;
    const uint8_t n = p[0];
    if (n > max || len < 1u + (size_t)n * CO_INST_REC_LEN) return false;

    for (uint8_t i = 0; i < n; i++) {
        const uint8_t *r = &p[1 + (size_t)i * CO_INST_REC_LEN];
        out[i].id      = r[0];
        out[i].state   = r[1];
        out[i].ctx_pct = r[2];
        out[i].flags   = r[3];
        memcpy(out[i].label, &r[4], CO_LABEL_LEN);
        out[i].label[CO_LABEL_LEN - 1] = 0;
    }
    *n_out = n;
    return true;
}
