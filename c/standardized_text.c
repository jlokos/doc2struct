#include "doc2struct.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

static int image(const Item *i) { return i->run.src.p != NULL; }
static int empty(const Item *i) { return !image(i) && !ds_strip(i->run.text, 1).n; }
static int same(const Item *a, const Item *b) {
    return a->run.flags == b->run.flags && a->run.has_font == b->run.has_font &&
           (!a->run.has_font || a->run.font == b->run.font);
}
static int append_item(Document *d, Vec *v, Item item) {
    Item *p = ds_push(&d->arena, v, sizeof(Item));
    if (!p)
        return 0;
    *p = item;
    return 1;
}
static int append_line(Document *d, Vec *v, Line line) {
    Line *p = ds_push(&d->arena, v, sizeof(Line));
    if (!p)
        return 0;
    *p = line;
    return 1;
}
typedef struct {
    Run *run;
    size_t index;
} Ref;
typedef struct {
    Item item;
    size_t row, col, rs, cs, index;
} Cell;
static int compare_ref(const void *a, const void *b) {
    const Ref *x = a, *y = b;
#define CMP(field)                                                                                 \
    if (x->run->field != y->run->field)                                                            \
    return x->run->field < y->run->field ? -1 : 1
    CMP(row);
    CMP(col);
    CMP(line);
#undef CMP
    return x->index < y->index ? -1 : x->index > y->index;
}
static int compare_cell(const void *a, const void *b) {
    const Cell *x = a, *y = b;
    return x->index < y->index ? -1 : x->index > y->index;
}
static int table_line(Document *d, Run *runs, size_t n, Line *out) {
    Ref *refs;
    Vec cells = {0};
    size_t i, j, maxr = 0, maxc = 0, meaningful = 0, lastrow = 0;
    Item *grid;
    Vec items = {0};
    refs = ds_alloc(&d->arena, n * sizeof(Ref));
    if (!refs)
        return 0;
    for (i = 0; i < n; i++)
        refs[i] = (Ref){runs + i, i};
    qsort(refs, n, sizeof(Ref), compare_ref);
    for (i = 0; i < n; i = j) {
        Cell *c = ds_push(&d->arena, &cells, sizeof(Cell));
        Vec texts = {0};
        size_t q, k;
        if (!c)
            return 0;
        c->row = refs[i].run->row;
        c->col = refs[i].run->col;
        c->rs = refs[i].run->rowspan;
        c->cs = refs[i].run->colspan;
        c->index = refs[i].index;
        c->item.run = *refs[i].run;
        c->item.run.flags = 0;
        c->item.run.has_font = c->item.run.has_indent = 0;
        c->item.run.href = (Str){0};
        c->item.run.src = (Str){0};
        for (j = i; j < n && refs[j].run->row == c->row && refs[j].run->col == c->col; j++)
            if (refs[j].index < c->index) {
                c->index = refs[j].index;
                c->rs = refs[j].run->rowspan;
                c->cs = refs[j].run->colspan;
            }
        for (q = i; q < j; q = k) {
            Vec parts = {0};
            for (k = q; k < j && refs[k].run->line == refs[q].run->line; k++) {
                Run *r = refs[k].run;
                Str text = r->text, *p;
                if (r->src.p) {
                    Str fragments[] = {ds_str("[ALT: "), r->text, ds_str(". SRC: "), r->src,
                                       ds_str("]")};
                    text = ds_join(&d->arena, fragments, 5, ds_str(""));
                }
                p = ds_push(&d->arena, &parts, sizeof(Str));
                if (!p)
                    return 0;
                *p = text;
                c->item.run.flags |= r->flags;
                if (r->has_font) {
                    c->item.run.font = r->font;
                    c->item.run.has_font = 1;
                    c->item.run.font_float = r->font_float;
                }
                if (r->has_indent) {
                    c->item.run.indent = r->indent;
                    c->item.run.has_indent = 1;
                    c->item.run.indent_float = r->indent_float;
                }
                if (r->href.p)
                    c->item.run.href = r->href;
            }
            {
                Str *p = ds_push(&d->arena, &texts, sizeof(Str));
                if (!p)
                    return 0;
                *p = ds_join(&d->arena, parts.p, parts.n, ds_str(""));
            }
        }
        c->item.run.text = ds_strip(ds_join(&d->arena, texts.p, texts.n, ds_str("\n")), 1);
        if (c->row > SIZE_MAX - c->rs || c->col > SIZE_MAX - c->cs)
            goto large;
        if (c->row + c->rs > maxr)
            maxr = c->row + c->rs;
        if (c->col + c->cs > maxc)
            maxc = c->col + c->cs;
    }
    if (maxc && maxr > SIZE_MAX / maxc / sizeof(Item))
        goto large;
    grid = ds_alloc(&d->arena, maxr * maxc * sizeof(Item));
    if (!grid)
        return 0;
    for (i = 0; i < maxr * maxc; i++)
        grid[i].run.text = ds_str("");
    qsort(cells.p, cells.n, sizeof(Cell), compare_cell);
    for (i = 0; i < cells.n; i++) {
        Cell *c = (Cell *)cells.p + i;
        size_t y, x;
        for (y = 0; y < c->rs; y++)
            for (x = 0; x < c->cs; x++)
                grid[(c->row + y) * maxc + c->col + x] = c->item;
    }
    for (i = 0; i < maxr; i++) {
        int found = 0;
        for (j = 0; j < maxc; j++)
            if (grid[i * maxc + j].run.text.n) {
                found = 1;
                break;
            }
        if (found) {
            meaningful++;
            lastrow = i;
        }
    }
    if (meaningful == 1) {
        for (j = 0; j < maxc; j++) {
            Item item = grid[lastrow * maxc + j];
            if (item.run.text.n) {
                item.fake_table = 1;
                if (!append_item(d, &items, item))
                    return 0;
            }
        }
        out->items = items.p;
        out->nitems = items.n;
    } else if (meaningful) {
        Str *texts = ds_alloc(&d->arena, maxr * maxc * sizeof(Str));
        if (!texts)
            return 0;
        for (i = 0; i < maxr * maxc; i++)
            texts[i] = grid[i].run.text;
        out->matrix = (Matrix){texts, maxr, maxc};
    }
    return !d->arena.error[0];
large:
    snprintf(d->arena.error, sizeof(d->arena.error), "table dimensions overflow");
    return 0;
}
static int group(Document *d, Vec *lines) {
    Run *runs = d->runs.p;
    size_t i, j, k;
    for (i = 0; i < d->runs.n; i = j) {
        Line line = {0};
        Vec items = {0};
        for (j = i; j < d->runs.n && runs[j].block == runs[i].block; j++)
            ;
        if (runs[i].in_table) {
            if (!table_line(d, runs + i, j - i, &line))
                return 0;
            if ((line.nitems || line.matrix.nr) && !append_line(d, lines, line))
                return 0;
            continue;
        }
        for (k = i; k < j; k++) {
            Item cur = {runs[k], 0};
            Item *all = items.p;
            size_t q;
            if (!items.n && empty(&cur))
                continue;
            if (!items.n) {
                if (!append_item(d, &items, cur))
                    return 0;
                continue;
            }
            if (image(&cur) || image(all + items.n - 1)) {
                if (!append_item(d, &items, cur))
                    return 0;
            } else if (empty(&cur) || same(&cur, all + items.n - 1))
                all[items.n - 1].run.text =
                    ds_cat(&d->arena, all[items.n - 1].run.text, cur.run.text);
            else {
                int merged = 0;
                for (q = items.n; q; q--)
                    if (!image(all + q - 1) && same(&cur, all + q - 1)) {
                        Vec parts = {0};
                        Str *p;
                        size_t x;
                        for (x = q - 1; x < items.n; x++)
                            if (!image(all + x)) {
                                p = ds_push(&d->arena, &parts, sizeof(Str));
                                if (!p)
                                    return 0;
                                *p = all[x].run.text;
                            }
                        p = ds_push(&d->arena, &parts, sizeof(Str));
                        if (!p)
                            return 0;
                        *p = cur.run.text;
                        all[q - 1].run.text = ds_join(&d->arena, parts.p, parts.n, ds_str(""));
                        items.n = q;
                        merged = 1;
                        break;
                    }
                if (!merged && !append_item(d, &items, cur))
                    return 0;
            }
        }
        if (items.n == 1 && !image(items.p))
            ((Item *)items.p)->run.text = ds_strip(((Item *)items.p)->run.text, 1);
        for (k = 0; k < items.n; k++)
            if (!empty((Item *)items.p + k))
                break;
        if (k < items.n) {
            line.items = items.p;
            line.nitems = items.n;
            if (!append_line(d, lines, line))
                return 0;
        }
    }
    return !d->arena.error[0];
}
static int clean(Document *d, const Rules *r, Vec *lines) {
    Map counts = {0};
    Line *all = lines->p;
    size_t i, j, k, out = 0;
    for (i = 0; r->repeat_threshold && i < lines->n; i++)
        for (j = 0; j < all[i].nitems; j++) {
            Item *it = all[i].items + j;
            Str text = ds_lower(&d->arena, ds_strip(it->run.text, 1));
            size_t *count;
            if (!text.n || image(it))
                continue;
            count = ds_map_get(&counts, text);
            if (!count) {
                count = ds_alloc(&d->arena, sizeof(size_t));
                if (!count || !ds_map_put(&d->arena, &counts, text, count))
                    return 0;
            }
            (*count)++;
        }
    for (i = 0; i < lines->n; i++) {
        Line line = all[i];
        size_t kept = 0;
        if (line.matrix.nr) {
            all[out++] = line;
            continue;
        }
        for (j = 0; j < line.nitems; j++) {
            Item it = line.items[j];
            Str text;
            size_t *count;
            int remove = 0;
            if (image(&it)) {
                line.items[kept++] = it;
                continue;
            }
            text = ds_lower(&d->arena, ds_strip(it.run.text, 0));
            count = ds_map_get(&counts, text);
            if (count && r->repeat_threshold &&
                (r->repeat_threshold < 0 || *count >= (size_t)r->repeat_threshold))
                remove = 1;
            for (k = 0; !remove && k < r->nremove; k++)
                if ((!r->remove[k].needs_href || it.run.href.p) &&
                    ds_match(d, r->remove[k].rx, text, 0))
                    remove = 1;
            if (!remove)
                line.items[kept++] = it;
        }
        line.nitems = kept;
        if (kept)
            all[out++] = line;
    }
    lines->n = out;
    return !d->arena.error[0];
}
static double font_stats(Document *d, Vec *lines, int *dominant) {
    Map counts = {0};
    size_t i, best = 0;
    double common = 0;
    Line *all = lines->p;
    *dominant = 0;
    for (i = 0; i < lines->n; i++)
        if (all[i].nitems) {
            Item *f = all[i].items;
            size_t *count;
            Str key;
            if (image(f) || !f->run.has_font)
                continue;
            key = (Str){(const char *)&f->run.font, sizeof(double)};
            count = ds_map_get(&counts, key);
            if (!count) {
                count = ds_alloc(&d->arena, sizeof(size_t));
                if (!count || !ds_map_put(&d->arena, &counts, key, count))
                    return 0;
            }
            (*count)++;
        }
    /* Iterate in source order to preserve Python's first-seen tie breaking. */
    for (i = 0; i < lines->n; i++)
        if (all[i].nitems) {
            Item *f = all[i].items;
            size_t *count;
            if (image(f) || !f->run.has_font)
                continue;
            count = ds_map_get(&counts, (Str){(char *)&f->run.font, sizeof(double)});
            if (count && *count > best) {
                best = *count;
                common = f->run.font;
            }
        }
    *dominant = best > lines->n * .5;
    return common;
}
static unsigned attrs(Item *i) {
    unsigned flags = i->run.flags;
    if (ds_upper(i->run.text))
        flags |= ALL_CAPS;
    else if (ds_proper(i->run.text))
        flags |= PROPER_CASE;
    if (i->fake_table)
        flags |= FAKE_TABLE;
    return flags;
}
static int split(Document *d, Vec *lines) {
    Vec out = {0};
    Line *all = lines->p;
    int dominant;
    double common = font_stats(d, lines, &dominant);
    size_t i;
    for (i = 0; i < lines->n; i++) {
        Line line = all[i];
        if (line.nitems > 1 && !image(line.items) &&
            (attrs(line.items) ||
             (dominant && line.items[0].run.has_font && line.items[0].run.font > common * 1.2))) {
            Line first = line;
            first.nitems = 1;
            if (!append_line(d, &out, first))
                return 0;
            line.items++;
            line.nitems--;
        }
        if (!append_line(d, &out, line))
            return 0;
    }
    *lines = out;
    return !d->arena.error[0];
}
static int classify(Document *d, const Rules *r, Vec *lines) {
    Line *all = lines->p;
    int dominant, predicted = 0, section = -1, attr_levels[128], next = 0;
    double common = font_stats(d, lines, &dominant);
    size_t i, j;
    for (i = 0; i < 128; i++)
        attr_levels[i] = -1;
    if (r->nheaders) {
        predicted = r->headers[0].level + 1;
        for (i = 1; i < r->nheaders; i++)
            if (r->headers[i].level >= predicted)
                predicted = r->headers[i].level + 1;
    }
    for (i = 0; i < lines->n; i++) {
        Line *ln = all + i;
        Item *first = ln->nitems ? ln->items : NULL;
        ln->level = -1;
        ln->klass = ds_str("text");
        if (first && !image(first)) {
            int big = dominant && first->run.has_font && first->run.font > 1.2 * common;
            ln->attrs = attrs(first);
            if (dominant && first->run.has_font && first->run.font < common) {
                ln->level = -2;
                ln->klass = ds_str("textsmall");
                ln->attrs = 0;
            } else if (big || ln->attrs) {
                Str text = ds_strip(ds_lower(&d->arena, first->run.text), 0);
                int matched = 0;
                for (j = 0; j < r->nheaders; j++) {
                    Header *h = r->headers + j;
                    if (ds_match(d, h->rx, text, 0) && (h->requires & ln->attrs) == h->requires) {
                        Vec groups = {0};
                        unsigned g;
                        Str *p = ds_push(&d->arena, &groups, sizeof(Str));
                        if (!p)
                            return 0;
                        *p = h->name;
                        for (g = 1; g <= h->rx->groups; g++) {
                            Str part = ds_group(d, text, g);
                            if (part.p) {
                                p = ds_push(&d->arena, &groups, sizeof(Str));
                                if (!p)
                                    return 0;
                                *p = part;
                            }
                        }
                        ln->title = ds_join(&d->arena, groups.p, groups.n, ds_str(""));
                        ln->level = h->level;
                        ln->klass = h->name;
                        matched = 1;
                        break;
                    }
                }
                if (!matched) {
                    ln->level = predicted;
                    ln->klass = ds_str("predicted header");
                    ln->predicted = 1;
                }
            }
        }
    }
    for (i = 0; i < lines->n; i++) {
        Line *ln = all + i;
        if (!ln->predicted && !ds_is(ln->klass, "text") && !ds_is(ln->klass, "textsmall")) {
            if (ln->level <= section) {
                for (j = 0; j < 128; j++)
                    attr_levels[j] = -1;
                next = 0;
            }
            section = ln->level;
        } else if (ln->predicted) {
            unsigned key = ln->attrs & 127;
            if (attr_levels[key] < 0)
                attr_levels[key] = predicted + next++;
            ln->level = attr_levels[key];
        }
    }
    return !d->arena.error[0];
}
static Str line_text(Document *d, Item *items, size_t n) {
    Vec parts = {0};
    size_t i;
    int fake = n && items[0].fake_table;
    for (i = 0; i < n; i++)
        if (!image(items + i)) {
            Str *p = ds_push(&d->arena, &parts, sizeof(Str));
            if (!p)
                return (Str){0};
            *p = fake ? ds_strip(items[i].run.text, 0) : items[i].run.text;
        }
    return ds_join(&d->arena, parts.p, parts.n, fake ? ds_str(" ") : ds_str(""));
}
static Row *add_row(Document *d, size_t level, Str type, Str klass) {
    Row *r = ds_push(&d->arena, &d->rows, sizeof(Row));
    if (!r)
        return NULL;
    r->level = level;
    r->type = type;
    r->klass = klass;
    r->cleaned = -1;
    return r;
}
static int build(Document *d, Vec *lines) {
    Vec stack = {0};
    int *p;
    size_t i, j;
    Row *r = add_row(d, 0, ds_str("title"), ds_str("introduction"));
    if (!r)
        return 0;
    r->text = ds_str("introduction");
    p = ds_push(&d->arena, &stack, sizeof(int));
    if (!p)
        return 0;
    *p = -1;
    p = ds_push(&d->arena, &stack, sizeof(int));
    if (!p)
        return 0;
    *p = 0;
    for (i = 0; i < lines->n; i++) {
        Line *ln = (Line *)lines->p + i;
        Str text;
        if (ln->matrix.nr) {
            r = add_row(d, stack.n - 1, ds_str("table"), ds_str("table"));
            if (!r)
                return 0;
            r->matrix = ln->matrix;
            continue;
        }
        if (ln->level >= 0) {
            while (stack.n > 1 && ((int *)stack.p)[stack.n - 1] >= ln->level)
                stack.n--;
            r = add_row(d, stack.n - 1, ds_str("title"), ln->klass);
            if (!r)
                return 0;
            r->text = line_text(d, ln->items, ln->nitems);
            r->title = ln->title.n ? ln->title : (Str){0};
            r->items = ln->items;
            r->nitems = 1;
            p = ds_push(&d->arena, &stack, sizeof(int));
            if (!p)
                return 0;
            *p = ln->level;
            continue;
        }
        text = ds_strip(line_text(d, ln->items, ln->nitems), 1);
        if (text.n) {
            Vec items = {0};
            for (j = 0; j < ln->nitems; j++)
                if (!image(ln->items + j) && !append_item(d, &items, ln->items[j]))
                    return 0;
            r = add_row(d, stack.n - 1, ln->klass, ln->klass);
            if (!r)
                return 0;
            r->text = text;
            r->items = items.p;
            r->nitems = items.n;
        }
        for (j = 0; j < ln->nitems; j++)
            if (image(ln->items + j)) {
                r = add_row(d, stack.n - 1, ds_str("image"), ds_str("image"));
                if (!r)
                    return 0;
                r->text = ln->items[j].run.text;
                r->items = ln->items + j;
                r->nitems = 1;
            }
    }
    return !d->arena.error[0];
}
int ds_standardize(Document *d, const Rules *r) {
    Vec lines = {0};
    return group(d, &lines) && clean(d, r, &lines) && split(d, &lines) && classify(d, r, &lines) &&
           build(d, &lines) && ds_tables(d, r);
}
