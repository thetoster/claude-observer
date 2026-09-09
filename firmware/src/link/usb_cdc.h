// Transport USB CDC. Ta sama warstwa wiadomosci co BLE — rozni sie tylko
// opakowaniem ramki (patrz proto.h).
#ifndef CO_USB_CDC_H
#define CO_USB_CDC_H

#include "proto.h"

void co_cdc_init(co_msg_cb cb, void *ctx);
void co_cdc_poll(void);                                  // wolac w petli glownej
void co_cdc_send(uint8_t type, const uint8_t *p, size_t len);
bool co_cdc_linked(void);                                // §7.5: usb_linked

#endif
