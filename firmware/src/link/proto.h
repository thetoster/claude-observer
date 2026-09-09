// Protokol claude-observer — wspolny dla USB CDC i BLE.
//
// USB CDC to strumien bajtow, wiec ramka potrzebuje synchronizacji i CRC:
//
//     A5 5A | len_lo len_hi | type | payload[len] | crc_lo crc_hi
//                             \_______ CRC-16/CCITT-FALSE _______/
//
// BLE nie potrzebuje ani preambuly, ani CRC — warstwa ATT sama wyznacza
// granice pakietu i zapewnia integralnosc. Tam przesylamy samo `type | payload`.
// Dzieki temu obie sciezki dziela ten sam kod obslugi wiadomosci, a roznia sie
// wylacznie opakowaniem.
//
// Kolejnosc bajtow: little-endian (naturalna dla ARM i x86).
#ifndef CO_PROTO_H
#define CO_PROTO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CO_PROTO_VERSION 1

#define CO_SYNC0 0xA5
#define CO_SYNC1 0x5A

#define CO_MAX_INSTANCES   8      // D4
#define CO_LABEL_LEN      16      // 15 znakow + NUL
#define CO_INST_REC_LEN   20      // id, state, ctx_pct, flags, label[16]
#define CO_MAX_PAYLOAD   224      // SNAPSHOT dla 8 instancji = 1 + 8*20 = 161
#define CO_MAX_FRAME     (2 + 2 + 1 + CO_MAX_PAYLOAD + 2)

// --- typy wiadomosci ------------------------------------------------------
// host -> urzadzenie
#define CO_MSG_SNAPSHOT  0x01     // n(1) + n * rekord instancji
#define CO_MSG_STATE     0x02     // id(1) state(1) ctx_pct(1)
#define CO_MSG_LIMITS    0x03     // 5h%(1) 7d%(1) 5h_reset(u32) 7d_reset(u32) flags(1)
#define CO_MSG_TIME      0x04     // unix epoch (u32)
#define CO_MSG_PING      0x05     // seq (u32)
// urzadzenie -> host
#define CO_MSG_HELLO     0x81     // proto(1) fw[3] mac[6]
#define CO_MSG_SELECT    0x82     // id(1)
#define CO_MSG_BATTERY   0x83     // mv(u16) pct(1) flags(1)
#define CO_MSG_PONG      0x84     // seq (u32)

// --- stany instancji ------------------------------------------------------
#define CO_ST_IDLE        0
#define CO_ST_WORKING     1
#define CO_ST_NEED_INPUT  2

// --- flagi ----------------------------------------------------------------
#define CO_LIM_HAS_5H    0x01     // rate_limits.five_hour obecne (§5.2)
#define CO_LIM_HAS_7D    0x02     // rate_limits.seven_day obecne
#define CO_BAT_CHARGING  0x01
#define CO_BAT_USB       0x02

uint16_t co_crc16(const uint8_t *data, size_t len);

// Pakuje ramke CDC do `out`. Zwraca dlugosc lub 0 przy bledzie.
size_t co_frame_encode(uint8_t type, const uint8_t *payload, size_t len,
                       uint8_t *out, size_t out_cap);

// --- dekoder strumieniowy -------------------------------------------------

typedef void (*co_msg_cb)(uint8_t type, const uint8_t *payload, size_t len,
                          void *ctx);

typedef enum {
    CO_RX_SYNC0 = 0, CO_RX_SYNC1, CO_RX_LEN0, CO_RX_LEN1,
    CO_RX_TYPE, CO_RX_PAYLOAD, CO_RX_CRC0, CO_RX_CRC1,
} co_rx_state_t;

typedef struct {
    co_rx_state_t state;
    uint16_t      len, got;
    uint8_t       type;
    uint16_t      crc_rx;
    uint8_t       buf[CO_MAX_PAYLOAD];
    co_msg_cb     cb;
    void         *ctx;
    uint32_t      n_ok, n_crc_err, n_overrun;   // liczniki diagnostyczne
} co_rx_t;

void co_rx_init(co_rx_t *rx, co_msg_cb cb, void *ctx);
void co_rx_byte(co_rx_t *rx, uint8_t b);
void co_rx_feed(co_rx_t *rx, const uint8_t *data, size_t len);

// Sciezka BLE: pakiet jest juz zdelimitowany, wiec omijamy ramkowanie.
void co_rx_packet(co_rx_t *rx, const uint8_t *data, size_t len);

// --- pomocnicze budowanie payloadow --------------------------------------

typedef struct {
    uint8_t id;
    uint8_t state;
    uint8_t ctx_pct;      // 0..100, 0xFF = nieznane
    uint8_t flags;
    char    label[CO_LABEL_LEN];
} co_inst_t;

size_t co_build_snapshot(const co_inst_t *insts, uint8_t n,
                         uint8_t *out, size_t cap);
bool   co_parse_snapshot(const uint8_t *p, size_t len,
                         co_inst_t *out, uint8_t *n_out, uint8_t max);

#endif // CO_PROTO_H
