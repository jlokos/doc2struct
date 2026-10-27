#include "doc2struct.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <ctype.h>
#include "unicode_data.h"

uint32_t ds_utf8(const char *p, size_t n, size_t *step) {
    const unsigned char *s = (const unsigned char *)p;
    uint32_t c;
    size_t k, i;
    if (!n) {
        *step = 0;
        return 0;
    }
    c = s[0];
    if (c < 128) {
        *step = 1;
        return c;
    }
    k = c >= 0xc2 && c <= 0xdf ? 2 : c >= 0xe0 && c <= 0xef ? 3 : c >= 0xf0 && c <= 0xf4 ? 4 : 0;
    if (!k || k > n) {
        *step = 1;
        return 0xfffd;
    }
    c &= (1u << (7 - k)) - 1;
    for (i = 1; i < k; i++) {
        if ((s[i] & 0xc0) != 0x80) {
            *step = 1;
            return 0xfffd;
        }
        c = (c << 6) | (s[i] & 63);
    }
    if ((k == 3 && c < 0x800) || (k == 4 && c < 0x10000) || c > 0x10ffff ||
        (c >= 0xd800 && c <= 0xdfff)) {
        *step = 1;
        return 0xfffd;
    }
    *step = k;
    return c;
}
static size_t encode(char *p, uint32_t c) {
    if (c < 0x80) {
        p[0] = (char)c;
        return 1;
    }
    if (c < 0x800) {
        p[0] = (char)(0xc0 | (c >> 6));
        p[1] = (char)(0x80 | (c & 63));
        return 2;
    }
    if (c < 0x10000) {
        p[0] = (char)(0xe0 | (c >> 12));
        p[1] = (char)(0x80 | ((c >> 6) & 63));
        p[2] = (char)(0x80 | (c & 63));
        return 3;
    }
    p[0] = (char)(0xf0 | (c >> 18));
    p[1] = (char)(0x80 | ((c >> 12) & 63));
    p[2] = (char)(0x80 | ((c >> 6) & 63));
    p[3] = (char)(0x80 | (c & 63));
    return 4;
}
static const UnicodeEntry *entry(uint32_t cp) {
    size_t l = 0, r = sizeof(unicode_entries) / sizeof(*unicode_entries);
    while (l < r) {
        size_t m = l + (r - l) / 2;
        if (unicode_entries[m].cp < cp)
            l = m + 1;
        else
            r = m;
    }
    return l < sizeof(unicode_entries) / sizeof(*unicode_entries) && unicode_entries[l].cp == cp
               ? unicode_entries + l
               : NULL;
}
static unsigned uflags(uint32_t cp) {
    const UnicodeEntry *e;
    if (cp < 128)
        return (cp == ' ' || (cp >= 9 && cp <= 13) || (cp >= 28 && cp <= 31) ? 1 : 0) |
               (cp >= 'A' && cp <= 'Z' ? 2 : 0) | (cp >= 'a' && cp <= 'z' ? 4 : 0);
    e = entry(cp);
    return e ? e->flags : 0;
}
int ds_space(uint32_t cp) { return (uflags(cp) & 1) != 0; }
static int empty_char(uint32_t c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == 0xa0 || c == 0x200b;
}
Str ds_strip(Str s, int custom) {
    size_t i = 0, j = 0, k;
    uint32_t c;
    while (i < s.n) {
        c = ds_utf8(s.p + i, s.n - i, &k);
        if (!(custom ? empty_char(c) : ds_space(c)))
            break;
        i += k;
    }
    j = s.n;
    while (j > i) {
        size_t start = j - 1;
        while (start > i && ((unsigned char)s.p[start] & 0xc0) == 0x80)
            start--;
        c = ds_utf8(s.p + start, j - start, &k);
        if (!(custom ? empty_char(c) : ds_space(c)))
            break;
        j = start;
    }
    return (Str){s.p ? s.p + i : NULL, j - i};
}
Str ds_input(Arena *a, Str s) {
    size_t i = 0, k, j;
    uint32_t cp;
    char *p;
    static const uint32_t cp1252[] = {
        0x20ac, 0xfffd, 0x201a, 0x192,  0x201e, 0x2026, 0x2020, 0x2021, 0x2c6,  0x2030, 0x160,
        0x2039, 0x152,  0xfffd, 0x17d,  0xfffd, 0xfffd, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022,
        0x2013, 0x2014, 0x2dc,  0x2122, 0x161,  0x203a, 0x153,  0xfffd, 0x17e,  0x178};
    while (i < s.n) {
        cp = ds_utf8(s.p + i, s.n - i, &k);
        if (cp == 0xfffd && k == 1)
            break;
        i += k;
    }
    if (i == s.n)
        return s;
    if (s.n > (SIZE_MAX - 1) / 3) {
        snprintf(a->error, sizeof(a->error), "input too large");
        return (Str){0};
    }
    p = ds_alloc(a, s.n * 3 + 1);
    if (!p)
        return (Str){0};
    for (i = 0, j = 0; i < s.n; i++) {
        cp = (unsigned char)s.p[i];
        if (cp >= 128 && cp < 160)
            cp = cp1252[cp - 128];
        j += encode(p + j, cp);
    }
    return (Str){p, j};
}
int ds_upper(Str s) {
    size_t i, k;
    int found = 0;
    for (i = 0; i < s.n; i += k) {
        unsigned f = uflags(ds_utf8(s.p + i, s.n - i, &k));
        if (f & 4)
            return 0;
        if (f & 2)
            found = 1;
    }
    return found;
}
Str ds_lower(Arena *a, Str s) {
    size_t i, k, j = 0;
    char *p;
    int preceding = 0, changed = 0;
    if (s.n > (SIZE_MAX - 1) / 3) {
        snprintf(a->error, sizeof(a->error), "text too large");
        return (Str){0};
    }
    p = ds_alloc(a, s.n * 3 + 1);
    if (!p)
        return (Str){0};
    for (i = 0; i < s.n; i += k) {
        uint32_t cp = ds_utf8(s.p + i, s.n - i, &k);
        const UnicodeEntry *e = cp >= 128 ? entry(cp) : NULL;
        unsigned f = uflags(cp);
        const char *lower = e ? e->lower : NULL;
        if (cp == 0x3a3 && preceding) {
            size_t x = i + k, step;
            int following = 0;
            while (x < s.n) {
                uint32_t next = ds_utf8(s.p + x, s.n - x, &step);
                unsigned nf = uflags(next);
                if (nf & 8) {
                    x += step;
                    continue;
                }
                following = (nf & 6) != 0;
                break;
            }
            lower = following ? "\317\203" : "\317\202";
        }
        if (cp >= 'A' && cp <= 'Z') {
            p[j++] = (char)(cp + 32);
            changed = 1;
        } else if (lower) {
            size_t len = strlen(lower);
            memcpy(p + j, lower, len);
            j += len;
            changed = 1;
        } else {
            memcpy(p + j, s.p + i, k);
            j += k;
        }
        if (!(f & 8))
            preceding = (f & 6) != 0;
    }
    return changed ? (Str){p, j} : s;
}
int ds_proper(Str s) {
    size_t i = 0, k, start;
    int words = 0;
    static const char *stops[] = {"and", "or",  "of",   "the", "in", "on", "at",
                                  "to",  "for", "with", "by",  "a",  "an", NULL};
    while (i < s.n) {
        size_t j;
        int stop = 0;
        start = i;
        while (i < s.n && ((s.p[i] >= 'A' && s.p[i] <= 'Z') || (s.p[i] >= 'a' && s.p[i] <= 'z')))
            i++;
        if (i == start)
            return 0;
        for (j = 0; stops[j]; j++) {
            size_t n = strlen(stops[j]), q;
            if (n != i - start)
                continue;
            for (q = 0; q < n; q++)
                if (tolower((unsigned char)s.p[start + q]) != stops[j][q])
                    break;
            if (q == n) {
                stop = 1;
                break;
            }
        }
        if (!stop && !(s.p[start] >= 'A' && s.p[start] <= 'Z'))
            return 0;
        words++;
        if (i == s.n)
            break;
        if (!ds_space(ds_utf8(s.p + i, s.n - i, &k)))
            return 0;
        do {
            i += k;
            if (i == s.n)
                return 0;
        } while (ds_space(ds_utf8(s.p + i, s.n - i, &k)));
    }
    return words > 0;
}
static const Entity *entity(Str key) {
    size_t l = 0, r = sizeof(entities) / sizeof(*entities);
    while (l < r) {
        size_t m = l + (r - l) / 2, n = key.n < entities[m].length ? key.n : entities[m].length;
        int c = memcmp(key.p, entities[m].name, n);
        if (!c)
            c = key.n < entities[m].length ? -1 : key.n > entities[m].length ? 1 : 0;
        if (c > 0)
            l = m + 1;
        else if (c < 0)
            r = m;
        else
            return entities + m;
    }
    return NULL;
}
Str ds_unescape(Arena *a, Str s) {
    char *out;
    size_t i = 0, j = 0;
    if (!memchr(s.p, '&', s.n))
        return s;
    if (s.n > (SIZE_MAX - 1) / 3) {
        snprintf(a->error, sizeof(a->error), "text too large");
        return (Str){0};
    }
    out = ds_alloc(a, s.n * 3 + 1);
    if (!out)
        return (Str){0};
    while (i < s.n) {
        if (s.p[i] != '&') {
            out[j++] = s.p[i++];
            continue;
        }
        if (i + 2 < s.n && s.p[i + 1] == '#') {
            size_t q = i + 2, start;
            uint32_t cp = 0;
            int base = 10, overflow = 0;
            if (s.p[q] == 'x' || s.p[q] == 'X') {
                base = 16;
                q++;
            }
            start = q;
            while (q < s.n) {
                unsigned char c = (unsigned char)s.p[q];
                int v = c >= '0' && c <= '9'   ? c - '0'
                        : c >= 'a' && c <= 'f' ? c - 'a' + 10
                        : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                               : 99;
                if (v >= base)
                    break;
                if (cp > 0x110000)
                    overflow = 1;
                else
                    cp = cp * (unsigned)base + (unsigned)v;
                q++;
            }
            if (q > start) {
                Str raw;
                size_t z;
                if (q < s.n && s.p[q] == ';')
                    q++;
                if (overflow || !cp || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff))
                    cp = 0xfffd;
                else if (cp == 129 || cp == 141 || cp == 143 || cp == 144 || cp == 157) {
                    j += encode(out + j, cp);
                    i = q;
                    continue;
                } else if (cp >= 128 && cp <= 159) {
                    char b = (char)cp;
                    raw = ds_input(a, (Str){&b, 1});
                    if (!raw.p)
                        return (Str){0};
                    for (z = 0; z < raw.n; z++)
                        out[j++] = raw.p[z];
                    i = q;
                    continue;
                } else if ((cp >= 1 && cp <= 8) || cp == 11 || (cp >= 14 && cp <= 31) ||
                           cp == 127 || (cp >= 0xfdd0 && cp <= 0xfdef) || (cp & 0xffff) == 0xfffe ||
                           (cp & 0xffff) == 0xffff) {
                    i = q;
                    continue;
                }
                j += encode(out + j, cp);
                i = q;
                continue;
            }
        }
        {
            size_t q = i + 1, limit;
            const Entity *e = NULL;
            while (q < s.n && q - i <= 32 && !strchr("\t\n\f <&#;", s.p[q]) && s.p[q] != 0)
                q++;
            if (q < s.n && s.p[q] == ';')
                q++;
            limit = q - i - 1;
            while (limit) {
                e = entity((Str){s.p + i + 1, limit});
                if (e)
                    break;
                limit--;
            }
            if (e) {
                size_t n = strlen(e->value);
                memcpy(out + j, e->value, n);
                j += n;
                i += limit + 1;
                continue;
            }
        }
        out[j++] = s.p[i++];
    }
    return (Str){out, j};
}
