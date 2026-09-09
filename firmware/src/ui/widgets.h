// Widgety wykorzystania: ciastko (wykres kolowy) i stos ciastek (wykres slupkowy).
// Zasoby graficzne pkt 3 i 4 spec.
#ifndef CO_WIDGETS_H
#define CO_WIDGETS_H

#include "framebuf.h"

// Ciastko = kontekst sesji (spec zasoby 3).
// Wycinek kolowy liczony od godziny 12 zgodnie z ruchem wskazowek zegara:
// czesc DOSTEPNA (100-pct) rysowana z `fresh`, czesc ZUZYTA (pct) z `used`.
// Oba obrazy nanoszone jako stack na tej samej pozycji.
void co_draw_cookie(co_fb_t *fb, const co_image_t *fresh, const co_image_t *used,
                    uint8_t pct, int dx, int dy);

// Stos ciastek = limit 7-dniowy (spec zasoby 4).
// Podzial poziomy: od dolu do (100-pct)% wysokosci `fresh`, powyzej `used`.
void co_draw_stack(co_fb_t *fb, const co_image_t *fresh, const co_image_t *used,
                   uint8_t pct, int dx, int dy);

#endif // CO_WIDGETS_H
