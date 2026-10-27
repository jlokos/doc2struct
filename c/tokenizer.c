#include "doc2struct.h"
#include <string.h>
#include <ctype.h>

static int space_at(Str s, size_t i, size_t *k) { return ds_space(ds_utf8(s.p + i, s.n - i, k)); }
static Str intern_tag(Document *d, Str tag) {
    Str lower = ds_lower(&d->arena, tag), *cached;
    if (!lower.p)
        return (Str){0};
    cached = ds_map_get(&d->tags, lower);
    if (cached)
        return *cached;
    cached = ds_alloc(&d->arena, sizeof(Str));
    if (!cached)
        return (Str){0};
    *cached = lower;
    if (!ds_map_put(&d->arena, &d->tags, lower, cached))
        return (Str){0};
    return lower;
}
int ds_void(Str t) {
    static const char *names[] = {"area", "base", "br",    "col",    "embed", "hr",  "img", "input",
                                  "link", "meta", "param", "source", "track", "wbr", NULL};
    size_t i;
    for (i = 0; names[i]; i++)
        if (ds_is(t, names[i]))
            return 1;
    return 0;
}
static int wanted(Str s) {
    static const char *names[] = {"style", "colspan", "rowspan", "href", "src", "alt", "hidden"};
    size_t i;
    for (i = 0; i < A_COUNT; i++)
        if (ds_is(s, names[i]))
            return (int)i;
    return -1;
}
static int attrs(Document *d, Str rest, Attrs *out) {
    size_t i = 0, k, start, end;
    memset(out, 0, sizeof(*out));
    while (i < rest.n) {
        Str name, value;
        int index;
        while (i < rest.n) {
            unsigned char c = (unsigned char)rest.p[i];
            if (!space_at(rest, i, &k) && !strchr("=/>\"'", c))
                break;
            i += k;
        }
        start = i;
        while (i < rest.n) {
            unsigned char c = (unsigned char)rest.p[i];
            if (space_at(rest, i, &k) || strchr("=/>\"'", c))
                break;
            i += k;
        }
        if (i == start)
            break;
        name = ds_lower(&d->arena, (Str){rest.p + start, i - start});
        index = wanted(name);
        while (i < rest.n && space_at(rest, i, &k))
            i += k;
        value = ds_str("");
        if (i < rest.n && rest.p[i] == '=') {
            i++;
            while (i < rest.n && space_at(rest, i, &k))
                i += k;
            start = i;
            if (i < rest.n && (rest.p[i] == '\'' || rest.p[i] == '\"')) {
                char quote = rest.p[i++];
                start = i;
                while (i < rest.n && rest.p[i] != quote)
                    i++;
                end = i;
                if (i < rest.n)
                    i++;
                else
                    end = end > start ? end - 1 : end;
            } else {
                while (i < rest.n && rest.p[i] != '>' && !space_at(rest, i, &k))
                    i += k;
                end = i;
            }
            value = (Str){rest.p + start, end - start};
        }
        if (index >= 0)
            out->value[index] = ds_unescape(&d->arena, value);
        if (d->arena.error[0])
            return 0;
    }
    return 1;
}
int ds_tokenize(Document *d, Str html, TokenSink sink, void *ctx) {
    size_t i = 0, pos = 0, n = html.n;
    while (i < n) {
        size_t start = i, j, k, name_start, name_end, rest_start, end;
        int closing = 0, selfclosed = 0;
        Str tag;
        Attrs at;
        if (html.p[i] != '<') {
            i++;
            continue;
        }
        if (i + 4 <= n && !memcmp(html.p + i, "<!--", 4)) {
            j = i + 4;
            while (j + 3 <= n && memcmp(html.p + j, "-->", 3))
                j++;
            end = j + 3 <= n ? j + 3 : n;
            if (start > pos &&
                !sink(ctx, TEXT, ds_unescape(&d->arena, (Str){html.p + pos, start - pos}), NULL))
                return 0;
            pos = i = end;
            continue;
        }
        if (i + 1 < n && (html.p[i + 1] == '!' || html.p[i + 1] == '?')) {
            j = i + 2;
            while (j < n && html.p[j] != '>')
                j++;
            end = j < n ? j + 1 : n;
            if (start > pos &&
                !sink(ctx, TEXT, ds_unescape(&d->arena, (Str){html.p + pos, start - pos}), NULL))
                return 0;
            pos = i = end;
            continue;
        }
        j = i + 1;
        if (j < n && html.p[j] == '/') {
            closing = 1;
            j++;
        }
        if (j >= n ||
            !((html.p[j] >= 'a' && html.p[j] <= 'z') || (html.p[j] >= 'A' && html.p[j] <= 'Z'))) {
            i++;
            continue;
        }
        name_start = j++;
        while (j < n && html.p[j] != '/' && html.p[j] != '>' && !space_at(html, j, &k))
            j += k;
        name_end = j;
        rest_start = j;
        while (j < n) {
            char c = html.p[j];
            if (c == '\'' || c == '\"') {
                char quote = c;
                j++;
                while (j < n && html.p[j] != quote)
                    j++;
                if (j < n)
                    j++;
                else
                    break;
            } else if (c == '>')
                break;
            else
                j++;
        }
        if (j >= n) {
            i++;
            continue;
        }
        end = j + 1;
        if (start > pos &&
            !sink(ctx, TEXT, ds_unescape(&d->arena, (Str){html.p + pos, start - pos}), NULL))
            return 0;
        tag = intern_tag(d, (Str){html.p + name_start, name_end - name_start});
        if (!tag.p)
            return 0;
        pos = end;
        if (closing) {
            if (!sink(ctx, END, tag, NULL))
                return 0;
            i = end;
            continue;
        }
        {
            Str rest = {html.p + rest_start, j - rest_start}, trim = ds_strip(rest, 0);
            selfclosed = trim.n && trim.p[trim.n - 1] == '/';
            if (!attrs(d, rest, &at))
                return 0;
        }
        if (!sink(ctx, START, tag, &at))
            return 0;
        if (!selfclosed && (ds_is(tag, "script") || ds_is(tag, "style") || ds_is(tag, "title"))) {
            size_t q = end;
            int found = 0;
            while (q + 2 + tag.n <= n) {
                if (html.p[q] == '<' && html.p[q + 1] == '/') {
                    size_t x;
                    for (x = 0; x < tag.n; x++)
                        if (tolower((unsigned char)html.p[q + 2 + x]) != (unsigned char)tag.p[x])
                            break;
                    if (x == tag.n) {
                        size_t z = q + 2 + tag.n;
                        while (z < n && space_at(html, z, &k))
                            z += k;
                        if (z < n && html.p[z] == '>') {
                            pos = z + 1;
                            found = 1;
                            break;
                        }
                    }
                }
                q++;
            }
            if (!found)
                pos = n;
            if (!sink(ctx, END, tag, NULL))
                return 0;
        } else if (selfclosed && !ds_void(tag)) {
            if (!sink(ctx, END, tag, NULL))
                return 0;
        }
        i = pos;
    }
    if (pos < n && !sink(ctx, TEXT, ds_unescape(&d->arena, (Str){html.p + pos, n - pos}), NULL))
        return 0;
    return !d->arena.error[0];
}
