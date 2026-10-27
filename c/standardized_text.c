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
    Str text;
    Run *first, *font, *indent, *href;
    size_t row, col, rs, cs, index;
    unsigned flags;
} Cell;
static int compare_ref(const void *a, const void *b) {
    const Ref *x = a, *y = b;
    if (x->run->row != y->run->row)
        return x->run->row < y->run->row ? -1 : 1;
    if (x->run->col != y->run->col)
        return x->run->col < y->run->col ? -1 : 1;
    if (x->run->line != y->run->line)
        return x->run->line < y->run->line ? -1 : 1;
    return x->index < y->index ? -1 : x->index > y->index;
}
static int compare_cell(const void *a, const void *b) {
    const Cell *x = a, *y = b;
    return x->index < y->index ? -1 : x->index > y->index;
}
static Run *cell_run(Run *runs, Ref *refs, size_t i) { return refs ? refs[i].run : runs + i; }
static Str cell_text(Document *d, Run *runs, Ref *refs, size_t i, size_t end) {
    size_t k, total = 0, pos = 0, parts = 0, last_line = 0;
    Str only = ds_str("");
    char *out;
    for (k = i; k < end; k++) {
        Run *r = cell_run(runs, refs, k);
        size_t add = r->text.n;
        if (k > i && r->line != last_line) {
            if (total == SIZE_MAX)
                goto large;
            total++;
            parts++;
        }
        if (r->src.p) {
            if (add > SIZE_MAX - r->src.n - 14)
                goto large;
            add += r->src.n + 14;
            parts += 5;
        } else if (add) {
            parts++;
            only = r->text;
        }
        if (add > SIZE_MAX - total - 1)
            goto large;
        total += add;
        last_line = r->line;
    }
    if (!total)
        return ds_str("");
    if (parts == 1)
        return ds_strip(only, 1);
    out = ds_alloc_uninit(&d->arena, total + 1);
    if (!out)
        return (Str){0};
    for (k = i; k < end; k++) {
        Run *r = cell_run(runs, refs, k);
        if (k > i && r->line != cell_run(runs, refs, k - 1)->line)
            out[pos++] = '\n';
        if (r->src.p) {
            memcpy(out + pos, "[ALT: ", 6);
            pos += 6;
        }
        if (r->text.n) {
            memcpy(out + pos, r->text.p, r->text.n);
            pos += r->text.n;
        }
        if (r->src.p) {
            memcpy(out + pos, ". SRC: ", 7);
            pos += 7;
            if (r->src.n) {
                memcpy(out + pos, r->src.p, r->src.n);
                pos += r->src.n;
            }
            out[pos++] = ']';
        }
    }
    out[pos] = 0;
    return ds_strip((Str){out, pos}, 1);
large:
    snprintf(d->arena.error, sizeof(d->arena.error), "table cell text too large");
    return (Str){0};
}
static int table_line(Document *d, Run *runs, size_t n, Line *out) {
    Ref *refs = NULL;
    Cell *cells, **grid;
    size_t ncells = 0, i, j, k, maxr = 0, maxc = 0, meaningful = 0, lastrow = 0;
    for (i = 1; i < n; i++) {
        Run *a = runs + i - 1, *b = runs + i;
        if (a->row > b->row ||
            (a->row == b->row && (a->col > b->col || (a->col == b->col && a->line > b->line))))
            break;
    }
    if (i < n) {
        refs = ds_alloc_uninit(&d->arena, n * sizeof(Ref));
        if (!refs)
            return 0;
        for (i = 0; i < n; i++)
            refs[i] = (Ref){runs + i, i};
        qsort(refs, n, sizeof(Ref), compare_ref);
    }
    for (i = 0; i < n; i = j) {
        Run *r = cell_run(runs, refs, i);
        for (j = i + 1; j < n; j++) {
            Run *x = cell_run(runs, refs, j);
            if (x->row != r->row || x->col != r->col)
                break;
        }
        ncells++;
    }
    cells = ds_alloc(&d->arena, ncells * sizeof(Cell));
    if (!cells)
        return 0;
    for (i = 0, k = 0; i < n; i = j, k++) {
        Run *first = cell_run(runs, refs, i);
        Cell *c = cells + k;
        c->first = first;
        c->row = first->row;
        c->col = first->col;
        c->rs = first->rowspan;
        c->cs = first->colspan;
        c->index = refs ? refs[i].index : i;
        for (j = i; j < n; j++) {
            Run *r = cell_run(runs, refs, j);
            size_t index = refs ? refs[j].index : j;
            if (r->row != c->row || r->col != c->col)
                break;
            if (index < c->index) {
                c->index = index;
                c->rs = r->rowspan;
                c->cs = r->colspan;
            }
            c->flags |= r->flags;
            if (r->has_font)
                c->font = r;
            if (r->has_indent)
                c->indent = r;
            if (r->href.p)
                c->href = r;
        }
        c->text = cell_text(d, runs, refs, i, j);
        if (!c->text.p)
            return 0;
        if (c->row > SIZE_MAX - c->rs || c->col > SIZE_MAX - c->cs)
            goto large;
        if (c->row + c->rs > maxr)
            maxr = c->row + c->rs;
        if (c->col + c->cs > maxc)
            maxc = c->col + c->cs;
    }
    if (maxc && maxr > SIZE_MAX / maxc / sizeof(Str))
        goto large;
    grid = ds_alloc(&d->arena, maxr * maxc * sizeof(Cell *));
    if (!grid)
        return 0;
    for (i = 1; i < ncells; i++)
        if (cells[i - 1].index > cells[i].index)
            break;
    if (i < ncells)
        qsort(cells, ncells, sizeof(Cell), compare_cell);
    for (i = 0; i < ncells; i++)
        if (ds_strip(cells[i].text, 1).n)
            break;
    if (i < ncells) {
        size_t length;
        Str text = ds_strip(cells[i].text, 1);
        if (ds_list_marker(text, &length) && length == text.n) {
            Item *items = ds_alloc(&d->arena, ncells * sizeof(Item));
            if (!items)
                return 0;
            for (i = 0; i < ncells; i++) {
                Cell *c = cells + i;
                items[i].run = *c->first;
                items[i].run.text = c->text;
                items[i].run.flags = c->flags;
                items[i].run.href = c->href ? c->href->href : (Str){0};
                if (c->font) {
                    items[i].run.font = c->font->font;
                    items[i].run.has_font = 1;
                }
                if (c->indent) {
                    items[i].run.indent = c->indent->indent;
                    items[i].run.has_indent = 1;
                }
            }
            if (!ds_list_table(d, out, items, ncells))
                return 0;
        }
    }
    for (i = 0; i < ncells; i++) {
        Cell *c = cells + i;
        size_t y, x;
        for (y = 0; y < c->rs; y++)
            for (x = 0; x < c->cs; x++)
                grid[(c->row + y) * maxc + c->col + x] = c;
    }
    for (i = 0; i < maxr; i++) {
        for (j = 0; j < maxc; j++)
            if (grid[i * maxc + j] && grid[i * maxc + j]->text.n)
                break;
        if (j < maxc) {
            meaningful++;
            lastrow = i;
        }
    }
    if (meaningful == 1) {
        size_t count = 0;
        Item *items;
        for (j = 0; j < maxc; j++)
            if (grid[lastrow * maxc + j] && grid[lastrow * maxc + j]->text.n)
                count++;
        items = ds_alloc(&d->arena, count * sizeof(Item));
        if (!items)
            return 0;
        for (j = 0, k = 0; j < maxc; j++) {
            Cell *c = grid[lastrow * maxc + j];
            Item *item;
            if (!c || !c->text.n)
                continue;
            item = items + k++;
            item->fake_table = 1;
            item->run = *c->first;
            item->run.text = c->text;
            item->run.src = (Str){0};
            item->run.flags = c->flags;
            item->run.has_font = c->font != NULL;
            item->run.has_indent = c->indent != NULL;
            item->run.href = c->href ? c->href->href : (Str){0};
            if (c->font) {
                item->run.font = c->font->font;
                item->run.font_float = c->font->font_float;
            }
            if (c->indent) {
                item->run.indent = c->indent->indent;
                item->run.indent_float = c->indent->indent_float;
            }
        }
        out->items = items;
        out->nitems = count;
    } else if (meaningful) {
        Str *texts = ds_alloc_uninit(&d->arena, maxr * maxc * sizeof(Str));
        if (!texts)
            return 0;
        for (i = 0; i < maxr * maxc; i++)
            texts[i] = grid[i] ? grid[i]->text : ds_str("");
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
            if (!text.n || image(it) || all[i].listitem)
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
        if (line.matrix.nr || line.listitem) {
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
        if (!line.listitem && line.nitems > 1 && !image(line.items) &&
            ((attrs(line.items) & ~FAKE_TABLE) ||
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
        if (ln->listitem) {
            ln->klass = ds_str("listitem");
            continue;
        }
        if (first && !image(first)) {
            int big = dominant && first->run.has_font && first->run.font > 1.2 * common;
            ln->attrs = attrs(first);
            if (dominant && first->run.has_font && first->run.font < common) {
                ln->level = -2;
                ln->klass = ds_str("textsmall");
                ln->attrs = 0;
            } else if (big || (ln->attrs & ~FAKE_TABLE)) {
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
        if (ln->listitem)
            continue;
        if (!ln->predicted && !ds_is(ln->klass, "text") && !ds_is(ln->klass, "textsmall")) {
            if (ln->level <= section) {
                for (j = 0; j < 128; j++)
                    attr_levels[j] = -1;
                next = 0;
            }
            section = ln->level;
        } else if (ln->predicted) {
            unsigned key = ln->attrs & (127 & ~FAKE_TABLE);
            if (attr_levels[key] < 0)
                attr_levels[key] = predicted + next++;
            ln->level = attr_levels[key];
        }
    }
    return !d->arena.error[0];
}
static Str line_text(Document *d, Item *items, size_t n) {
    size_t i, count = 0;
    Str *parts;
    int fake = n && items[0].fake_table;
    for (i = 0; i < n; i++)
        if (!image(items + i))
            count++;
    if (!count)
        return ds_str("");
    if (count == 1) {
        for (i = 0; i < n; i++)
            if (!image(items + i))
                return fake ? ds_strip(items[i].run.text, 0) : items[i].run.text;
    }
    parts = ds_alloc_uninit(&d->arena, count * sizeof(Str));
    if (!parts)
        return (Str){0};
    for (i = 0, count = 0; i < n; i++)
        if (!image(items + i))
            parts[count++] = fake ? ds_strip(items[i].run.text, 0) : items[i].run.text;
    return ds_join(&d->arena, parts, count, fake ? ds_str(" ") : ds_str(""));
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
    Vec indents = {0};
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
        size_t content_level = stack.n - 1;
        Str text;
        if (ln->listitem) {
            double *indent;
            while (indents.n > 1 &&
                   ln->list_indent < ((double *)indents.p)[indents.n - 1] - 2)
                indents.n--;
            if (!indents.n || ln->list_indent > ((double *)indents.p)[indents.n - 1] + 2) {
                indent = ds_push(&d->arena, &indents, sizeof(double));
                if (!indent)
                    return 0;
                *indent = ln->list_indent;
            } else if (indents.n == 1)
                ((double *)indents.p)[0] = ln->list_indent;
            content_level += indents.n - 1;
        } else
            indents.n = 0;
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
                if (image(ln->items + j))
                    break;
            if (j == ln->nitems) {
                items.p = ln->items;
                items.n = ln->nitems;
            } else
                for (j = 0; j < ln->nitems; j++)
                    if (!image(ln->items + j) && !append_item(d, &items, ln->items[j]))
                        return 0;
            r = add_row(d, content_level, ln->klass, ln->klass);
            if (!r)
                return 0;
            r->text = text;
            r->items = items.p;
            r->nitems = items.n;
        }
        for (j = 0; j < ln->nitems; j++)
            if (image(ln->items + j)) {
                r = add_row(d, content_level, ds_str("image"), ds_str("image"));
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
    Vec lines = d->flow ? d->lines : (Vec){0};
    return (d->flow || group(d, &lines)) && ds_lists(d, &lines) &&
           clean(d, r, &lines) && split(d, &lines) &&
           classify(d, r, &lines) && build(d, &lines) && ds_list_blocks(d) && ds_tables(d, r);
}
