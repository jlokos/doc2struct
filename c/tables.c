#include "doc2struct.h"
#include <string.h>
#include <stdio.h>

static int blank(Str s) { return !s.n || ds_is(s, "-") || ds_is(s, "\342\200\223"); }
static int format(Str s, int which) {
    size_t i = 0, k;
    int found = 0;
    for (; i < s.n; i += k) {
        uint32_t c = ds_utf8(s.p + i, s.n - i, &k);
        int allowed = which == 0   ? (c == '$' || c == '(' || c == 0x2013 || c == '-')
                      : which == 1 ? (c == ')' || c == '%' || c == 0x2013 || c == '-')
                                   : (c == '$' || c == '(' || c == ')' || c == '%' || c == 0x2013 ||
                                      c == '-');
        if (!allowed)
            return which == 2;
        found = 1;
    }
    return which == 2 ? 0 : found;
}
static int enabled(const Rules *r, unsigned i) { return (r->table_steps & (1u << i)) != 0; }
static void select_rows(Matrix *m, unsigned char *keep) {
    size_t i, j = 0;
    for (i = 0; i < m->nr; i++)
        if (keep[i]) {
            if (i != j)
                memmove(m->cells + j * m->nc, m->cells + i * m->nc, m->nc * sizeof(Str));
            j++;
        }
    m->nr = j;
}
static void select_cols(Matrix *m, unsigned char *keep) {
    size_t i, j, k = 0, nc = 0;
    for (j = 0; j < m->nc; j++)
        nc += keep[j] != 0;
    for (i = 0; i < m->nr; i++)
        for (j = 0; j < m->nc; j++)
            if (keep[j])
                m->cells[k++] = m->cells[i * m->nc + j];
    m->nc = nc;
}
static int clean_table(Document *d, const Rules *r, Row *row) {
    Matrix *m = &row->matrix;
    size_t i, j, k;
    unsigned char *keep;
    for (i = 0; i < m->nr * m->nc; i++)
        m->cells[i] = ds_strip(m->cells[i], 1);
    row->cleaned = 1;
    if (enabled(r, 1)) {
        for (i = 0; i < m->nr; i++)
            for (j = 0; j < m->nc; j++) {
                Str t = m->cells[i * m->nc + j];
                if (format(t, 0))
                    for (k = j + 1; k < m->nc; k++)
                        if (format(m->cells[i * m->nc + k], 2)) {
                            m->cells[i * m->nc + k] = ds_cat(&d->arena, t, m->cells[i * m->nc + k]);
                            m->cells[i * m->nc + j] = ds_str("");
                            break;
                        }
            }
        for (i = 0; i < m->nr; i++)
            for (j = 0; j < m->nc; j++) {
                Str t = m->cells[i * m->nc + j];
                if (format(t, 1))
                    for (k = j; k; k--)
                        if (format(m->cells[i * m->nc + k - 1], 2)) {
                            m->cells[i * m->nc + k - 1] =
                                ds_cat(&d->arena, m->cells[i * m->nc + k - 1], t);
                            m->cells[i * m->nc + j] = ds_str("");
                            break;
                        }
            }
    }
    keep = ds_alloc(&d->arena, m->nr > m->nc ? m->nr : m->nc);
    if (!keep)
        return 0;
    if (enabled(r, 2)) {
        for (i = 0; i < m->nr; i++) {
            keep[i] = 0;
            for (j = 0; j < m->nc; j++)
                if (!blank(m->cells[i * m->nc + j])) {
                    keep[i] = 1;
                    break;
                }
        }
        select_rows(m, keep);
    }
    if (enabled(r, 3) && m->nr && m->nc) {
        for (j = 0; j < m->nc; j++) {
            keep[j] = 0;
            for (i = 0; i < m->nr; i++)
                if (!blank(m->cells[i * m->nc + j])) {
                    keep[j] = 1;
                    break;
                }
        }
        select_cols(m, keep);
    }
    if (enabled(r, 4)) {
        memset(keep, 1, m->nr);
        for (i = m->nr; i > 1; i--) {
            size_t a = i - 1, b = i - 2;
            for (j = 0; j < m->nc; j++)
                if (!blank(m->cells[a * m->nc + j]) &&
                    !ds_eq(m->cells[a * m->nc + j], m->cells[b * m->nc + j]))
                    break;
            if (j == m->nc)
                keep[a] = 0;
        }
        select_rows(m, keep);
    }
    if (enabled(r, 5)) {
        memset(keep, 1, m->nr);
        for (i = 0; i + 1 < m->nr; i++) {
            for (j = 0; j < m->nc; j++)
                if (!blank(m->cells[i * m->nc + j]) &&
                    !ds_eq(m->cells[i * m->nc + j], m->cells[(i + 1) * m->nc + j]))
                    break;
            if (j == m->nc)
                keep[i] = 0;
        }
        select_rows(m, keep);
    }
    for (k = 6; k <= 7; k++)
        if (enabled(r, (unsigned)k) && m->nr) {
            memset(keep, 1, m->nc);
            for (j = 0; j + 1 < m->nc; j++) {
                size_t a = k == 6 ? j : j + 1, b = k == 6 ? j + 1 : j;
                for (i = 0; i < m->nr; i++)
                    if (!blank(m->cells[i * m->nc + a]) &&
                        !ds_eq(m->cells[i * m->nc + a], m->cells[i * m->nc + b]))
                        break;
                if (i == m->nr)
                    keep[a] = 0;
            }
            select_cols(m, keep);
        }
    if (enabled(r, 8) && m->nr >= 2) {
        for (j = 0; j + 1 < m->nc; j++)
            if (ds_eq(m->cells[j], m->cells[j + 1]))
                break;
        if (j + 1 < m->nc) {
            for (j = 0; j < m->nc; j++)
                if (!ds_eq(m->cells[j], m->cells[m->nc + j])) {
                    Str parts[] = {m->cells[j], m->cells[m->nc + j]};
                    m->cells[j] = ds_join(&d->arena, parts, 2, ds_str("\n"));
                }
            if (m->nr > 2)
                memmove(m->cells + m->nc, m->cells + 2 * m->nc, (m->nr - 2) * m->nc * sizeof(Str));
            m->nr--;
        }
    }
    return !d->arena.error[0];
}
static int text_row(Row *r) { return ds_is(r->type, "text") || ds_is(r->type, "textsmall"); }
static int add_note(Document *d, Vec *notes, Str id, Str text) {
    Note *n = ds_push(&d->arena, notes, sizeof(Note));
    if (!n)
        return 0;
    *n = (Note){id, text};
    return 1;
}
static int notes_table(Document *d, const Rules *r, Matrix *m, Vec *notes) {
    size_t i, original = notes->n;
    if (!m->nr || m->nc != 2)
        return 0;
    for (i = 0; i < m->nr; i++) {
        Str marker = ds_strip(m->cells[i * 2], 0);
        if (!ds_match(d, r->footnote, marker, 0)) {
            notes->n = original;
            return 0;
        }
        if (!r->footnote->groups) {
            snprintf(d->arena.error, sizeof(d->arena.error),
                     "footnote regex must have a capture group");
            return 0;
        }
        if (!add_note(d, notes, ds_group(d, marker, 1), ds_strip(m->cells[i * 2 + 1], 0)))
            return 0;
    }
    return 1;
}
static int absorb(Document *d, const Rules *r) {
    Row *rows = d->rows.p;
    size_t i, n = d->rows.n;
    for (i = 0; i < n; i++) {
        Row *row = rows + i;
        size_t j, k, last = i;
        Vec parts = {0}, notes = {0};
        if (row->removed || !ds_is(row->type, "table"))
            continue;
        if (r->preamble_lines > 0) {
            j = i;
            while (j && parts.n < (size_t)r->preamble_lines && text_row(rows + j - 1) &&
                   !rows[j - 1].removed) {
                Str *p = ds_push(&d->arena, &parts, sizeof(Str));
                if (!p)
                    return 0;
                j--;
                *p = rows[j].text;
                rows[j].removed = 1;
            }
            if (parts.n) {
                Str *all = parts.p;
                for (j = 0; j < parts.n / 2; j++) {
                    Str temp = all[j];
                    all[j] = all[parts.n - j - 1];
                    all[parts.n - j - 1] = temp;
                }
                row->preamble = ds_join(&d->arena, all, parts.n, ds_str(" "));
            }
        }
        if (r->footnote) {
            j = i + 1;
            while (j < n && !rows[j].removed) {
                Row *x = rows + j;
                Str marker, id, text;
                size_t extra = 0;
                if (ds_is(x->type, "table")) {
                    if (!notes_table(d, r, &x->matrix, &notes))
                        break;
                    x->removed = 1;
                    last = j++;
                    continue;
                }
                if (!text_row(x))
                    break;
                marker = ds_strip(x->text, 0);
                if (!ds_match(d, r->footnote, marker, 0))
                    break;
                if (!r->footnote->groups) {
                    snprintf(d->arena.error, sizeof(d->arena.error),
                             "footnote regex must have a capture group");
                    return 0;
                }
                id = ds_group(d, marker, 1);
                text = ds_group(d, marker, 0);
                text = ds_strip((Str){marker.p + text.n, marker.n - text.n}, 0);
                x->removed = 1;
                k = j + 1;
                while (k < n && r->footnote_lines > 0 && extra < (size_t)r->footnote_lines &&
                       text_row(rows + k) && !rows[k].removed &&
                       !ds_match(d, r->footnote, ds_strip(rows[k].text, 0), 0)) {
                    Str fragments[] = {text, ds_strip(rows[k].text, 0)};
                    text = ds_join(&d->arena, fragments, 2, ds_str(" "));
                    rows[k].removed = 1;
                    extra++;
                    k++;
                }
                if (!add_note(d, &notes, id, text))
                    return 0;
                last = k - 1;
                j = k;
            }
            row->notes = notes.p;
            row->nnotes = notes.n;
        }
        if (r->postamble_lines > 0) {
            parts = (Vec){0};
            j = last + 1;
            while (j < n && parts.n < (size_t)r->postamble_lines && text_row(rows + j) &&
                   !rows[j].removed) {
                Str *p = ds_push(&d->arena, &parts, sizeof(Str));
                if (!p)
                    return 0;
                *p = rows[j].text;
                rows[j].removed = 1;
                j++;
            }
            if (parts.n)
                row->postamble = ds_join(&d->arena, parts.p, parts.n, ds_str(" "));
        }
    }
    return !d->arena.error[0];
}
int ds_tables(Document *d, const Rules *r) {
    Row *rows = d->rows.p;
    size_t i, j, out = 0;
    for (i = 0; i < d->rows.n; i++) {
        Row row = rows[i];
        if (ds_is(row.type, "table")) {
            if (!clean_table(d, r, &row))
                return 0;
            if (!row.matrix.nr)
                continue;
            if (r->single_row_to_text && row.matrix.nr == 1) {
                row.type = row.klass = ds_str("text");
                row.text = ds_join(&d->arena, row.matrix.cells, row.matrix.nc, ds_str(" "));
                row.matrix = (Matrix){0};
                row.cleaned = -1;
            }
        }
        rows[out++] = row;
    }
    d->rows.n = out;
    if (!absorb(d, r))
        return 0;
    if (r->title_from_section) {
        Row *head = NULL, *table = NULL;
        size_t count = 0;
        for (i = 0; i <= d->rows.n; i++) {
            if (i < d->rows.n && rows[i].removed)
                continue;
            if (i == d->rows.n || ds_is(rows[i].type, "title")) {
                if (head && count == 1 && !table->text.n)
                    table->text = head->text;
                head = i < d->rows.n ? rows + i : NULL;
                table = NULL;
                count = 0;
            } else if (ds_is(rows[i].type, "table")) {
                table = rows + i;
                count++;
            }
        }
    }
    for (i = 0, j = 0; i < d->rows.n; i++)
        if (!rows[i].removed) {
            rows[j] = rows[i];
            rows[j].id = j;
            j++;
        }
    d->rows.n = j;
    return !d->arena.error[0];
}
