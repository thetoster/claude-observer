// Testy modelu instancji po stronie urzadzenia (spec 6-9), kompilowane na hoscie.
#include <stdio.h>
#include <string.h>
#include "instances.h"

static int fails = 0;
static void chk(const char *n, int ok, const char *d)
{
    if (ok) printf("  OK   %s\n", n);
    else { fails++; printf("  BLAD %s  %s\n", n, d ? d : ""); }
}

static void push(co_model_t *m, const co_inst_t *in, uint8_t n)
{
    uint8_t buf[CO_MAX_PAYLOAD];
    size_t len = co_build_snapshot(in, n, buf, sizeof buf);
    co_model_snapshot(m, buf, len);
}

int main(void)
{
    co_model_t m;
    char d[128];

    // spec 7: need_input wybiera sie samo
    co_model_init(&m);
    co_inst_t a[3] = {
        { 1, CO_ST_WORKING, 10, 0, "alfa" },
        { 2, CO_ST_WORKING, 20, 0, "beta" },
        { 3, CO_ST_WORKING, 30, 0, "gamma" },
    };
    push(&m, a, 3);
    chk("start: wybrana pierwsza", m.selected == 0, NULL);
    a[2].state = CO_ST_NEED_INPUT;
    push(&m, a, 3);
    chk("spec 7: need_input auto-wybrane", m.selected == 2, NULL);

    // nie przeskakuj z powrotem, gdy stan sie utrzymuje
    push(&m, a, 3);
    chk("need_input nie przeskakuje przy powtorce", m.selected == 2, NULL);

    // spec 9: idle znika gdy jest wiecej niz jedna widoczna
    a[0].state = CO_ST_IDLE;
    push(&m, a, 3);
    chk("spec 9: idle niewidoczna", !co_model_visible(&m, 0), NULL);
    chk("spec 9: liczba widocznych", co_model_visible_count(&m) == 2,
        (snprintf(d, sizeof d, "=%u", co_model_visible_count(&m)), d));

    // spec 9 ogon: gdy wszystkie idle, pokazujemy je mimo to
    for (int i = 0; i < 3; i++) a[i].state = CO_ST_IDLE;
    push(&m, a, 3);
    chk("spec 9 ogon: wszystkie idle -> widoczne",
        co_model_visible(&m, 0) && co_model_visible(&m, 1), NULL);

    // spec 8: przelaczanie pomija niewidoczne
    co_model_init(&m);
    co_inst_t b[3] = {
        { 1, CO_ST_WORKING,    0, 0, "x" },
        { 2, CO_ST_IDLE,       0, 0, "y" },
        { 3, CO_ST_NEED_INPUT, 0, 0, "z" },
    };
    push(&m, b, 3);
    m.selected = 0;
    co_model_step(&m, +1);
    chk("spec 8: krok pomija idle", m.selected == 2,
        (snprintf(d, sizeof d, "selected=%u", m.selected), d));
    co_model_step(&m, +1);
    chk("spec 8: zawijanie", m.selected == 0, NULL);
    co_model_step(&m, -1);
    chk("spec 8: krok wstecz", m.selected == 2, NULL);

    // wybor trzyma sie instancji, nie indeksu
    co_model_init(&m);
    push(&m, b, 3);
    m.selected = 2;                       // id=3
    co_inst_t c[2] = { { 9, CO_ST_WORKING, 0, 0, "nowa" },
                       { 3, CO_ST_WORKING, 0, 0, "z" } };
    push(&m, c, 2);
    chk("wybor podaza za id, nie za indeksem",
        m.n == 2 && m.insts[m.selected].id == 3,
        (snprintf(d, sizeof d, "id=%u", m.insts[m.selected].id), d));

    // limity: brak okna -> 0xFF (§5.2)
    co_model_init(&m);
    uint8_t lim[11] = {0};
    lim[0] = 34; lim[1] = 61; lim[10] = CO_LIM_HAS_5H;   // tylko 5h obecne
    co_model_limits(&m, lim, sizeof lim);
    chk("limit 5h znany, 7d nieznany",
        m.five_h == 34 && m.seven_d == 0xFF,
        (snprintf(d, sizeof d, "5h=%u 7d=%u", m.five_h, m.seven_d), d));

    printf("\n  wynik: %s\n", fails ? "SA BLEDY" : "WSZYSTKO OK");
    return fails ? 1 : 0;
}
