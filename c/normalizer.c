#include "doc2struct.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include <stdio.h>

typedef struct {
    Str tag, href;
    unsigned flags;
    double font, indent;
    int has_font, has_indent, suppressed, hides, act, root;
} Frame;
typedef struct {
    Document *d;
    Options options;
    Vec stack;
    int in_body, hidden, line_open, table, cell, emitted;
    size_t table_depth, next_block, cur_block, line, table_block, row, col, cell_row, cell_col, rs,
        cs;
    size_t *occupied, occupied_cap;
} Normalizer;
static int member(Str t, const char *names) {
    const char *p = names;
    while (*p) {
        const char *e = strchr(p, ' ');
        size_t n = e ? (size_t)(e - p) : strlen(p);
        if (ds_eq(t, (Str){p, n}))
            return 1;
        if (!e)
            break;
        p = e + 1;
    }
    return 0;
}
static int line_end(Str t) { return member(t, "p div h1 h2 h3 h4 h5 h6 li"); }
static double px(Str s) {
    char buf[96];
    size_t i = 0, n;
    double value;
    Str unit;
    s = ds_strip(s, 1);
    if (!s.n)
        return 0;
    while (i < s.n &&
           ((s.p[i] >= '0' && s.p[i] <= '9') || s.p[i] == '.' || (i == 0 && s.p[i] == '-')))
        i++;
    n = i < sizeof(buf) - 1 ? i : sizeof(buf) - 1;
    memcpy(buf, s.p, n);
    buf[n] = 0;
    {
        char *end;
        value = strtod(buf, &end);
        if ((size_t)(end - buf) != n)
            value = 0;
    }
    unit = i < s.n ? ds_strip((Str){s.p + i, s.n - i}, 1) : ds_str("px");
    if (member(unit, "auto inherit initial"))
        return 0;
    if (ds_is(unit, "pt"))
        return value * 1.333;
    if (member(unit, "em rem pc"))
        return value * 16;
    if (ds_is(unit, "%"))
        return value * .16;
    if (member(unit, "ex ch"))
        return value * 8;
    if (ds_is(unit, "cm"))
        return value * 37.8;
    if (ds_is(unit, "mm"))
        return value * 3.78;
    if (ds_is(unit, "in"))
        return value * 96;
    return value;
}
static size_t words(Str s, Str *parts, size_t cap) {
    size_t i = 0, k, n = 0, start;
    while (i < s.n) {
        while (i < s.n && ds_space(ds_utf8(s.p + i, s.n - i, &k)))
            i += k;
        start = i;
        while (i < s.n && !ds_space(ds_utf8(s.p + i, s.n - i, &k)))
            i += k;
        if (i > start) {
            if (n < cap)
                parts[n] = (Str){s.p + start, i - start};
            n++;
        }
    }
    return n;
}
static double left_box(Str s) {
    Str p[5];
    size_t n = words(s, p, 5);
    return n == 4 ? px(p[3]) : n == 2 || n == 3 ? px(p[1]) : px(s);
}
static Style *style(Document *d, Str raw) {
    static const char *keys[] = {"font-weight", "font-style",  "text-decoration", "text-align",
                                 "font-size",   "text-indent", "padding",         "padding-left",
                                 "margin",      "margin-left", "display",         "visibility",
                                 "font"};
    Str values[13] = {{0}}, lower;
    size_t i = 0, j, k;
    Style *st = ds_map_get(&d->styles, raw);
    if (st)
        return st;
    st = ds_alloc(&d->arena, sizeof(*st));
    if (!st)
        return NULL;
    lower = ds_lower(&d->arena, raw);
    if (!lower.p)
        return NULL;
    while (i < lower.n) {
        size_t start = i, colon = SIZE_MAX;
        Str name, value;
        while (i < lower.n && lower.p[i] != ';') {
            if (colon == SIZE_MAX && lower.p[i] == ':')
                colon = i;
            i++;
        }
        if (colon != SIZE_MAX) {
            name = ds_strip((Str){lower.p + start, colon - start}, 1);
            value = ds_strip((Str){lower.p + colon + 1, i - colon - 1}, 1);
            for (j = 0; j < 13; j++)
                if (ds_is(name, keys[j])) {
                    values[j] = value;
                    break;
                }
        }
        if (i < lower.n)
            i++;
    }
    if (values[12].p) {
        Str parts[32];
        size_t n = words(values[12], parts, 32), q = 0;
        if (n >= 2) {
            if (member(parts[q], "italic oblique normal")) {
                if (ds_is(parts[q], "italic"))
                    values[1] = ds_str("italic");
                q++;
            }
            if (q < n && member(parts[q], "small-caps normal"))
                q++;
            if (q < n && q < 32 &&
                member(parts[q],
                       "bold 700 normal 400 100 200 300 500 600 800 900 lighter bolder")) {
                values[0] = parts[q];
                q++;
            }
            if (q < n && q < 32) {
                values[4] = parts[q];
                for (k = 0; k < values[4].n; k++)
                    if (values[4].p[k] == '/') {
                        values[4].n = k;
                        break;
                    }
            }
        }
    }
    if (member(values[0], "bold 700"))
        st->flags |= BOLD;
    if (ds_is(values[1], "italic"))
        st->flags |= ITALIC;
    if (ds_is(values[2], "underline"))
        st->flags |= UNDERLINE;
    if (ds_is(values[3], "center"))
        st->flags |= CENTERED;
    st->has_font = values[4].p != NULL;
    st->font = px(values[4]);
    st->indent =
        px(values[5]) + left_box(values[6]) + px(values[7]) + left_box(values[8]) + px(values[9]);
    st->display_none = ds_is(values[10], "none");
    st->vis_hidden = member(values[11], "hidden collapse");
    if (!ds_map_put(&d->arena, &d->styles, raw, st))
        return NULL;
    return st;
}
static double rounded(double v) {
    double x = floor(v), delta = v - x;
    if (delta > .5 || (delta == .5 && fmod(x, 2) != 0))
        x++;
    return x == 0 ? 0 : x;
}
static void break_line(Normalizer *n) {
    if (n->line_open) {
        n->line_open = 0;
        n->line++;
    }
}
static int emit(Normalizer *n, Str text, Str src, int blank) {
    Run *r;
    Frame *frames = n->stack.p, *f = n->stack.n ? frames + n->stack.n - 1 : NULL;
    size_t i;
    if (!n->line_open) {
        n->line_open = 1;
        if (!n->cell)
            n->cur_block = n->next_block++;
    }
    r = ds_push(&n->d->arena, &n->d->runs, sizeof(Run));
    if (!r)
        return 0;
    r->block = n->cell ? n->table_block : n->cur_block;
    r->line = n->line;
    r->text = text;
    r->src = src;
    r->rowspan = r->colspan = 1;
    if (n->cell) {
        r->in_table = 1;
        r->row = n->cell_row;
        r->col = n->cell_col;
        r->rowspan = n->rs;
        r->colspan = n->cs;
        n->emitted = 1;
    }
    if (!blank && f) {
        r->flags = f->flags;
        r->font = rounded(f->font);
        r->indent = rounded(f->indent);
        r->has_font = f->has_font;
        r->has_indent = f->has_indent;
        r->href = f->href;
        for (i = n->stack.n; i; i--)
            if (line_end(frames[i - 1].tag) || member(frames[i - 1].tag, "td th")) {
                r->tag = frames[i - 1].tag;
                break;
            }
    }
    return 1;
}
static int pop(Normalizer *n) {
    Frame f = ((Frame *)n->stack.p)[--n->stack.n];
    if (f.hides)
        n->hidden--;
    if (f.suppressed)
        return 1;
    if (line_end(f.tag))
        break_line(n);
    else if (member(f.tag, "td th")) {
        if (f.act && n->table && n->cell) {
            if (!n->emitted && !emit(n, ds_str(""), (Str){0}, 1))
                return 0;
            n->cell = 0;
            break_line(n);
        }
    } else if (ds_is(f.tag, "tr")) {
        if (f.act && n->table) {
            n->row++;
            n->col = 0;
        }
    } else if (ds_is(f.tag, "table")) {
        n->table_depth--;
        break_line(n);
        if (f.root) {
            n->table = 0;
            n->cell = 0;
        }
    }
    return 1;
}
static int pop_open(Normalizer *n, const char *names, const char *stop) {
    Frame *frames = n->stack.p;
    size_t i;
    for (i = n->stack.n; i; i--) {
        Str tag = frames[i - 1].tag;
        if (member(tag, names)) {
            while (n->stack.n >= i)
                if (!pop(n))
                    return 0;
            return 1;
        }
        if (member(tag, stop))
            return 1;
    }
    return 1;
}
static int implied(Normalizer *n, Str t) {
    if (member(t, "address article aside blockquote center details dialog dir div dl dd dt "
                  "fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr li "
                  "main menu nav ol p pre section summary table ul") &&
        !pop_open(n, "p", "table td th body html"))
        return 0;
    if (ds_is(t, "li"))
        return pop_open(n, "li", "ul ol table");
    if (member(t, "dt dd"))
        return pop_open(n, "dt dd", "dl table");
    if (member(t, "td th"))
        return pop_open(n, "td th", "tr table");
    if (ds_is(t, "tr"))
        return pop_open(n, "td th", "tr table") && pop_open(n, "tr", "table");
    if (member(t, "thead tbody tfoot"))
        return pop_open(n, "td th", "tr table") && pop_open(n, "tr", "table") &&
               pop_open(n, "thead tbody tfoot", "table");
    return 1;
}
static size_t span(Str s, size_t cap) {
    char buf[64], *end;
    long long v;
    if (!s.p || !s.n)
        return 1;
    s = ds_strip(s, 0);
    if (s.n >= sizeof(buf))
        return s.p[0] == '-' ? 1 : cap;
    memcpy(buf, s.p, s.n);
    buf[s.n] = 0;
    v = strtoll(buf, &end, 10);
    if (end == buf || *end)
        return 1;
    if (v < 1)
        return 1;
    return (uint64_t)v > cap ? cap : (size_t)v;
}
void *ds_normalizer(Document *d, Options o) {
    Normalizer *n = ds_alloc(&d->arena, sizeof(*n));
    if (n) {
        n->d = d;
        n->options = o;
    }
    return n;
}
int ds_normalize_token(void *ctx, int kind, Str tag, const Attrs *a) {
    Normalizer *n = ctx;
    Document *d = n->d;
    Style *st = NULL;
    Frame *f;
    int hides;
    size_t i;
    if (d->arena.error[0])
        return 0;
    if (kind == TEXT) {
        if (!n->in_body || n->hidden || !tag.n || (!n->line_open && !ds_strip(tag, 1).n))
            return 1;
        return emit(n, tag, (Str){0}, 0);
    }
    if (kind == END) {
        const char *stop;
        if (!n->in_body || ds_void(tag) || member(tag, "body html"))
            return 1;
        stop = member(tag, "td th")                  ? "tr table"
               : member(tag, "tr thead tbody tfoot") ? "table"
               : ds_is(tag, "table")                 ? ""
                                                     : "table td th";
        for (i = n->stack.n; i; i--) {
            Str t = ((Frame *)n->stack.p)[i - 1].tag;
            if (ds_eq(t, tag)) {
                while (n->stack.n >= i)
                    if (!pop(n))
                        return 0;
                return 1;
            }
            if (member(t, stop))
                return 1;
        }
        return 1;
    }
    if (!n->in_body) {
        if (member(tag, "html head title meta link base style script noscript"))
            return 1;
        n->in_body = 1;
    }
    if (a->value[A_STYLE].n) {
        st = style(d, a->value[A_STYLE]);
        if (!st)
            return 0;
    }
    hides = (st && (st->display_none || (n->options.hide_visibility && st->vis_hidden))) ||
            (n->options.hide_hidden_attr && a->value[A_HIDDEN].p);
    if (ds_void(tag)) {
        if (n->hidden || hides)
            return 1;
        if (ds_is(tag, "br"))
            break_line(n);
        else if (ds_is(tag, "img"))
            return emit(n, a->value[A_ALT].p ? a->value[A_ALT] : ds_str(""),
                        a->value[A_SRC].p ? a->value[A_SRC] : ds_str(""), 0);
        return 1;
    }
    if (!implied(n, tag))
        return 0;
    {
        Frame inherited = {0};
        if (n->stack.n)
            inherited = ((Frame *)n->stack.p)[n->stack.n - 1];
        f = ds_push(&d->arena, &n->stack, sizeof(Frame));
        if (!f)
            return 0;
        *f = (Frame){0};
        f->flags = inherited.flags;
        f->font = inherited.font;
        f->indent = inherited.indent;
        f->has_font = inherited.has_font;
        f->has_indent = inherited.has_indent;
        f->href = inherited.href;
        f->tag = tag;
    }
    if (n->hidden) {
        f->suppressed = 1;
        return 1;
    }
    if (hides) {
        f->suppressed = f->hides = 1;
        n->hidden++;
        return 1;
    }
    if (st) {
        f->flags |= st->flags;
        if (st->has_font) {
            f->font = st->font;
            f->has_font = 1;
        }
        if (st->indent != 0) {
            f->indent = st->indent;
            f->has_indent = 1;
        }
    }
    if (member(tag, "b strong"))
        f->flags |= BOLD;
    else if (member(tag, "i em"))
        f->flags |= ITALIC;
    else if (member(tag, "u ins"))
        f->flags |= UNDERLINE;
    else if (ds_is(tag, "a"))
        f->href = a->value[A_HREF].p ? a->value[A_HREF] : ds_str("");
    if (ds_is(tag, "table")) {
        n->table_depth++;
        break_line(n);
        if (n->table_depth == 1) {
            f->root = 1;
            n->table = 1;
            n->table_block = n->next_block++;
            n->row = n->col = 0;
            n->cell = 0;
            if (n->occupied)
                memset(n->occupied, 0, n->occupied_cap * sizeof(size_t));
        }
    } else if (member(tag, "tr td th")) {
        f->act = n->table && n->table_depth == 1;
        if (f->act && !ds_is(tag, "tr")) {
            size_t needed;
            break_line(n);
            while (n->col < n->occupied_cap && n->occupied[n->col] > n->row)
                n->col++;
            n->rs = span(a->value[A_ROWSPAN], n->options.max_span);
            n->cs = span(a->value[A_COLSPAN], n->options.max_span);
            if (n->col > SIZE_MAX - n->cs || n->row > SIZE_MAX - n->rs) {
                snprintf(d->arena.error, sizeof(d->arena.error), "table dimensions overflow");
                return 0;
            }
            needed = n->col + n->cs;
            if (needed > n->occupied_cap) {
                size_t cap = needed < 32 ? 32 : needed;
                size_t *p;
                if (cap > SIZE_MAX / sizeof(size_t)) {
                    snprintf(d->arena.error, sizeof(d->arena.error), "table too large");
                    return 0;
                }
                p = ds_alloc(&d->arena, cap * sizeof(size_t));
                if (!p)
                    return 0;
                if (n->occupied_cap)
                    memcpy(p, n->occupied, n->occupied_cap * sizeof(size_t));
                n->occupied = p;
                n->occupied_cap = cap;
            }
            for (i = n->col; i < needed; i++)
                if (n->occupied[i] < n->row + n->rs)
                    n->occupied[i] = n->row + n->rs;
            n->cell = 1;
            n->cell_row = n->row;
            n->cell_col = n->col;
            n->emitted = 0;
            n->col = needed;
        }
    }
    return !d->arena.error[0];
}
int ds_normalize_finish(void *ctx) {
    Normalizer *n = ctx;
    while (n->stack.n)
        if (!pop(n))
            return 0;
    return !n->d->arena.error[0];
}
