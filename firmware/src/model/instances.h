// Model instancji po stronie urzadzenia. Host wysyla surowy stan, urzadzenie
// decyduje o prezentacji (§4 planu) — dzieki temu UI dziala sensownie takze
// wtedy, gdy lacze chwilowo padnie.
#ifndef CO_INSTANCES_H
#define CO_INSTANCES_H

#include "proto.h"

typedef struct {
    co_inst_t insts[CO_MAX_INSTANCES];
    uint8_t   n;
    uint8_t   selected;          // indeks w insts[]
    uint8_t   five_h, seven_d;   // 0..100, 0xFF = nieznane
    uint32_t  five_reset, seven_reset;
} co_model_t;

void co_model_init(co_model_t *m);
void co_model_snapshot(co_model_t *m, const uint8_t *p, size_t len);
void co_model_state(co_model_t *m, const uint8_t *p, size_t len);
void co_model_limits(co_model_t *m, const uint8_t *p, size_t len);

// spec 8: przelaczanie instancji joystickiem LEFT/RIGHT
void co_model_step(co_model_t *m, int delta);

// spec 9: instancja w stanie idle znika, gdy widocznych jest wiecej niz jedna
bool co_model_visible(const co_model_t *m, uint8_t i);
uint8_t co_model_visible_count(const co_model_t *m);

#endif
