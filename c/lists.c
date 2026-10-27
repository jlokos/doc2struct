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
            if (native || (kind && payload && !rejected_table &&
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
