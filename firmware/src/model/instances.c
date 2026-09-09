#include "instances.h"

#include <string.h>

void co_model_init(co_model_t *m)
{
    memset(m, 0, sizeof *m);
    m->five_h = m->seven_d = 0xFF;
}

uint8_t co_model_visible_count(const co_model_t *m)
{
    uint8_t n = 0;
    for (uint8_t i = 0; i < m->n; i++)
        if (m->insts[i].state != CO_ST_IDLE) n++;
    return n;
}

bool co_model_visible(const co_model_t *m, uint8_t i)
{
    if (i >= m->n) return false;
    if (m->insts[i].state != CO_ST_IDLE) return true;
    // spec 9, ogon reguly: gdy nie ma zadnej nie-idle, pokazujemy wszystkie
    return co_model_visible_count(m) == 0;
}

// spec 7: instancja wchodzaca w need_input wybiera sie sama
static void auto_select(co_model_t *m, uint8_t prev_n, const co_inst_t *prev)
{
    for (uint8_t i = 0; i < m->n; i++) {
        if (m->insts[i].state != CO_ST_NEED_INPUT) continue;
        bool was = false;
        for (uint8_t j = 0; j < prev_n; j++)
            if (prev[j].id == m->insts[i].id &&
                prev[j].state == CO_ST_NEED_INPUT) { was = true; break; }
        if (!was) { m->selected = i; return; }   // dopiero co weszla — wybierz
    }
    if (m->selected >= m->n) m->selected = 0;
    if (m->n && !co_model_visible(m, m->selected)) {
        for (uint8_t i = 0; i < m->n; i++)
            if (co_model_visible(m, i)) { m->selected = i; return; }
    }
}

void co_model_snapshot(co_model_t *m, const uint8_t *p, size_t len)
{
    co_inst_t prev[CO_MAX_INSTANCES];
    const uint8_t prev_n = m->n;
    memcpy(prev, m->insts, sizeof prev);

    const uint8_t sel_id = (m->n && m->selected < m->n)
                         ? m->insts[m->selected].id : 0;

    uint8_t n = 0;
    if (!co_parse_snapshot(p, len, m->insts, &n, CO_MAX_INSTANCES)) return;
    m->n = n;

    // utrzymaj wybor na tej samej instancji, nie na tym samym indeksie
    m->selected = 0;
    for (uint8_t i = 0; i < n; i++)
        if (m->insts[i].id == sel_id) { m->selected = i; break; }

    auto_select(m, prev_n, prev);
}

void co_model_state(co_model_t *m, const uint8_t *p, size_t len)
{
    if (len < 3) return;
    co_inst_t prev[CO_MAX_INSTANCES];
    const uint8_t prev_n = m->n;
    memcpy(prev, m->insts, sizeof prev);

    for (uint8_t i = 0; i < m->n; i++) {
        if (m->insts[i].id != p[0]) continue;
        m->insts[i].state = p[1];
        m->insts[i].ctx_pct = p[2];
        break;
    }
    auto_select(m, prev_n, prev);
}

void co_model_limits(co_model_t *m, const uint8_t *p, size_t len)
{
    if (len < 11) return;
    const uint8_t flags = p[10];
    m->five_h  = (flags & CO_LIM_HAS_5H) ? p[0] : 0xFF;
    m->seven_d = (flags & CO_LIM_HAS_7D) ? p[1] : 0xFF;
    memcpy(&m->five_reset,  &p[2], 4);
    memcpy(&m->seven_reset, &p[6], 4);
}

void co_model_step(co_model_t *m, int delta)
{
    if (!m->n) return;
    for (int k = 0; k < CO_MAX_INSTANCES; k++) {
        int s = (int)m->selected + delta * (k + 1);
        while (s < 0) s += m->n;
        s %= m->n;
        if (co_model_visible(m, (uint8_t)s)) { m->selected = (uint8_t)s; return; }
    }
}
