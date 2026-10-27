#include "doc2struct.h"
#include <string.h>
#include <stdio.h>

/* Return 1 for a bullet and 2 for a numbering/letter marker. Numbered text
 * needs a delimiter and a boundary, so dates, decimals and prose stay text. */
int ds_list_marker(Str text, size_t *length) {
    size_t i = 0, k, start;
    uint32_t c;
    int parenthesis, digits = 1, roman = 1;
    text = ds_strip(text, 1);
    if (!text.n)
        return 0;
    if (text.p[0] == '(' && ds_phone(text))
        return 0;
    c = ds_utf8(text.p, text.n, &k);
    if (c == 0x2022 || c == 0x25e6 || c == 0x25cf || c == 0x25aa ||
        c == 0x25a0 || c == 0x25cb || c == 0x2023 || c == 0x2043 || c == 0xb7) {
        *length = k;
        return 1;
    }
    if (c == '-' || c == '*' || c == 0x2013) {
        if (k < text.n && !ds_space(ds_utf8(text.p + k, text.n - k, &i)))
            return 0;
        *length = k;
        return c == '*' ? 2 : 1;
    }
    parenthesis = text.p[0] == '(';
    start = i = parenthesis ? 1 : 0;
    while (i < text.n && i - start < 8) {
        unsigned char ch = (unsigned char)text.p[i];
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') ||
              (ch >= 'A' && ch <= 'Z')))
            break;
        if (ch < '0' || ch > '9')
            digits = 0;
        if (!strchr("ivxlcdmIVXLCDM", ch))
            roman = 0;
        i++;
    }
    if (i == start || (digits ? i - start > 3 : i - start > 1 && !roman))
        return 0;
    if (i == text.n || (parenthesis ? text.p[i] != ')' :
                       text.p[i] != '.' && text.p[i] != ')'))
        return 0;
    i++;
    if (i < text.n && !ds_space(ds_utf8(text.p + i, text.n - i, &k)))
        return 0;
    *length = i;
    return 2;
}

static int marker_only(Str text) {
    size_t length;
    text = ds_strip(text, 1);
    return ds_list_marker(text, &length) && length == text.n;
}

static int bullet_decoration(Str text) {
    size_t length, count = 0;
    text = ds_strip(text, 1);
    while (text.n && ds_list_marker(text, &length) == 1) {
        count++;
        text = ds_strip((Str){text.p + length, text.n - length}, 1);
    }
    return count > 1 && !text.n;
}

static int prose(Str text) {
    size_t i, k;
    for (i = 0; i < text.n; i += k) {
        uint32_t c = ds_utf8(text.p + i, text.n - i, &k);
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            (c >= 0xc0 && !(c >= 0x2000 && c <= 0x2bff)))
            return 1;
    }
    return 0;
}

/* Source cells, before spans are expanded or formatting columns are removed.
 * Require exactly a marker and a textual payload per nonempty row. In
 * particular, a financial table with a bullet plus several values stays a table. */
int ds_list_table(Document *d, Line *line, Item *cells, size_t n) {
    size_t i, count = 0, used = 0, last_row = 0;
    Item *pair[2];
    ListLines *list;
    for (i = 0; i <= n; i++) {
        if (i < n && !ds_strip(cells[i].run.text, 1).n)
            continue;
        if (i == n || (used && cells[i].run.row != last_row)) {
            if (used != 2 || !marker_only(pair[0]->run.text) ||
                !prose(pair[1]->run.text))
                return 1;
            count++;
            used = 0;
            if (i == n)
                break;
        }
        if (used == 2 || cells[i].run.rowspan > 1 || cells[i].run.src.p)
            return 1;
        pair[used++] = cells + i;
        last_row = cells[i].run.row;
    }
    if (!count)
        return 1;
    list = ds_alloc(&d->arena, sizeof(*list));
    if (!list)
        return 0;
    list->lines = ds_alloc(&d->arena, count * sizeof(Line));
    if (!list->lines)
        return 0;
    list->n = count;
    for (i = 0, count = 0, used = 0; i < n; i++) {
        Line *out;
        Item *marker;
        size_t length;
        if (!ds_strip(cells[i].run.text, 1).n)
            continue;
        pair[used++] = cells + i;
        if (used != 2)
            continue;
        out = list->lines + count++;
        out->items = ds_alloc(&d->arena, 2 * sizeof(Item));
        if (!out->items)
            return 0;
        out->items[0] = *pair[0];
        out->items[1] = *pair[1];
        out->items[0].fake_table = out->items[1].fake_table = 1;
        out->nitems = 2;
        out->listitem = 1;
        marker = out->items;
        out->list_kind = ds_list_marker(marker->run.text, &length);
        out->list_indent = marker->run.has_indent ? marker->run.indent :
                           (double)marker->run.col * 24;
        used = 0;
    }
    line->list = list;
    return 1;
}

int ds_lists(Document *d, Vec *lines) {
    Vec out = {0};
    Line *all = lines->p;
    size_t i, j;
    int after_table = 0;
    for (i = 0; i < lines->n; i++) {
        Line line = all[i], *dest;
        if (line.list && !(after_table && line.list->lines[0].list_kind == 2)) {
            for (j = 0; j < line.list->n; j++) {
                dest = ds_push(&d->arena, &out, sizeof(Line));
                if (!dest)
                    return 0;
                *dest = line.list->lines[j];
            }
            after_table = 0;
            continue;
        }
        if (!line.matrix.nr && line.nitems && !line.items[0].run.src.p) {
            Item *first = line.items;
            Str text = ds_strip(first->run.text, 1);
            size_t length = 0;
            int native = ds_is(first->run.tag, "li");
            int kind = ds_list_marker(text, &length);
            int payload = text.n > length || line.nitems > 1;
            /* A rejected layout table may have extra financial cells. Only
             * the validated table path may combine a standalone marker cell. */
            int rejected_table = first->fake_table && text.n == length;
            int decoration = kind == 1 && line.nitems == 1 && bullet_decoration(text);
            if (native || (kind && payload && !rejected_table && !decoration &&
                           !(after_table && kind == 2))) {
                line.listitem = 1;
                line.list_kind = kind;
                line.list_indent = first->run.has_indent ? first->run.indent : 0;
            }
        }
        dest = ds_push(&d->arena, &out, sizeof(Line));
        if (!dest)
            return 0;
        *dest = line;
        /* Preserve table-adjacent numbered footnotes for the notes stage. */
        if (line.matrix.nr)
            after_table = 1;
        else if (line.listitem || !line.nitems ||
                 !ds_list_marker(line.items[0].run.text, &j))
            after_table = 0;
    }
    *lines = out;
    return !d->arena.error[0];
}

/* Ignore a standalone marker's styling: continuation text belongs to the
 * payload, including when the marker was a separate table cell or font run. */
static const Run *payload_run(const Row *row) {
    size_t i, length;
    for (i = 0; i < row->nitems; i++) {
        const Run *run = &row->items[i].run;
        Str text = ds_strip(run->text, 1);
        if (!text.n || run->src.p)
            continue;
        if (ds_is(row->type, "listitem") && ds_list_marker(text, &length) && length == text.n)
            continue;
        return run;
    }
    return NULL;
}
static int matching_payload(const Row *item, const Row *next) {
    const Run *a = payload_run(item), *b = payload_run(next);
    unsigned style = BOLD | ITALIC | UNDERLINE | CENTERED;
    return item->level == next->level && a && b &&
           (a->flags & style) == (b->flags & style) && a->has_font == b->has_font &&
           (!a->has_font || a->font == b->font) && a->has_indent == b->has_indent &&
           (!a->has_indent || a->indent == b->indent);
}
static int matching_text(const Row *item, const Row *next) {
    return (ds_is(next->type, "text") || ds_is(next->type, "textsmall")) &&
           matching_payload(item, next);
}
static int append_continuations(Document *d, Row *item, const Row *rows, size_t count) {
    Vec parts = {0}, items = {0};
    size_t i, j;
    for (i = 0; i <= count; i++) {
        const Row *source = i ? rows + i - 1 : item;
        Str *text = ds_push(&d->arena, &parts, sizeof(Str));
        if (!text)
            return 0;
        *text = source->text;
        for (j = 0; j < source->nitems; j++) {
            Item *run = ds_push(&d->arena, &items, sizeof(Item));
            if (!run)
                return 0;
            *run = source->items[j];
        }
    }
    item->text = ds_join(&d->arena, parts.p, parts.n, ds_str(" "));
    item->items = items.p;
    item->nitems = items.n;
    return !d->arena.error[0];
}
/* Infer list/text/list gaps before grouping lists or compacting prose. A tail
 * is permitted only after a positive gap confirmed that same-style chain.
 * Capitalization and sentence punctuation play no part in this decision. */
int ds_list_continuations(Document *d, const Rules *rules) {
    Row *rows = d->rows.p;
    size_t i, next, out = 0;
    int confirmed = 0;
    if (!rules->list_gap_rows)
        return 1;
    for (i = 0; i < d->rows.n; i = next) {
        Row item = rows[i];
        next = i + 1;
        if (ds_is(item.type, "listitem")) {
            size_t end = next, gap, take = 0;
            int following_item;
            while (end < d->rows.n && matching_text(&item, rows + end))
                end++;
            gap = end - next;
            following_item = end < d->rows.n && ds_is(rows[end].type, "listitem") &&
                             matching_payload(&item, rows + end);
            if (following_item) {
                if (gap <= (size_t)rules->list_gap_rows) {
                    take = gap;
                    if (gap)
                        confirmed = 1;
                } else
                    confirmed = 0;  /* Reject the entire oversized gap. */
            } else {
                if (confirmed)
                    take = gap < (size_t)rules->list_tail_rows ? gap : (size_t)rules->list_tail_rows;
                confirmed = 0;
            }
            if (take) {
                if (!append_continuations(d, &item, rows + next, take))
                    return 0;
                next += take;
            }
        } else
            confirmed = 0;
        rows[out++] = item;
    }
    d->rows.n = out;
    return !d->arena.error[0];
}

/* Keep each contiguous list in one document row. Its matrix has two string
 * columns: depth relative to the list's level, and the original item text. */
int ds_list_blocks(Document *d) {
    Row *rows = d->rows.p;
    size_t i, j, k, out = 0;
    for (i = 0; i < d->rows.n; i = j) {
        Row block = rows[i];
        j = i + 1;
        if (ds_is(block.type, "listitem")) {
            Vec cells = {0}, items = {0};
            size_t end;
            for (end = i + 1; end < d->rows.n && ds_is(rows[end].type, "listitem"); end++)
                if (rows[end].level < block.level)
                    block.level = rows[end].level;
            block.type = block.klass = ds_str("list");
            block.text = (Str){0};
            for (j = i; j < end; j++) {
                Row *item = rows + j;
                char depth[32];
                int length = snprintf(depth, sizeof(depth), "%zu", item->level - block.level);
                Str *cell = ds_push(&d->arena, &cells, sizeof(Str));
                if (!cell)
                    return 0;
                *cell = ds_copy(&d->arena, (Str){depth, (size_t)length});
                cell = ds_push(&d->arena, &cells, sizeof(Str));
                if (!cell)
                    return 0;
                *cell = item->text;
                for (k = 0; k < item->nitems; k++) {
                    Item *run = ds_push(&d->arena, &items, sizeof(Item));
                    if (!run)
                        return 0;
                    *run = item->items[k];
                }
            }
            block.matrix = (Matrix){cells.p, j - i, 2};
            block.items = items.p;
            block.nitems = items.n;
        }
        rows[out++] = block;
    }
    d->rows.n = out;
    return !d->arena.error[0];
}
