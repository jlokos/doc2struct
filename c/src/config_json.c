#include "config_json.h"
#include <stdio.h>
#include <string.h>

/* A bounded JSON reader for configuration, independent of Python and locale. */
typedef struct { Arena *a; Str input; size_t pos; } Reader;
static void fail(Reader *r, const char *message) {
    if (!r->a->error[0])
        snprintf(r->a->error, sizeof(r->a->error), "JSON at byte %zu: %s", r->pos, message);
}
static void whitespace(Reader *r) {
    while (r->pos < r->input.n && strchr(" \t\r\n", r->input.p[r->pos]) && r->input.p[r->pos]) r->pos++;
}
static int hex4(Reader *r, uint32_t *out) {
    size_t i; uint32_t value = 0;
    if (r->input.n - r->pos < 4) return 0;
    for (i = 0; i < 4; i++) {
        unsigned c = (unsigned char)r->input.p[r->pos++], digit;
        if (c >= '0' && c <= '9') digit = c - '0';
        else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
        else return 0;
        value = value * 16 + digit;
    }
    *out = value; return 1;
}
static size_t utf8(char *p, uint32_t c) {
    if (c < 128) { p[0] = (char)c; return 1; }
    if (c < 2048) { p[0] = (char)(0xc0 | (c >> 6)); p[1] = (char)(0x80 | (c & 63)); return 2; }
    if (c < 65536) {
        p[0] = (char)(0xe0 | (c >> 12)); p[1] = (char)(0x80 | ((c >> 6) & 63));
        p[2] = (char)(0x80 | (c & 63)); return 3;
    }
    p[0] = (char)(0xf0 | (c >> 18)); p[1] = (char)(0x80 | ((c >> 12) & 63));
    p[2] = (char)(0x80 | ((c >> 6) & 63)); p[3] = (char)(0x80 | (c & 63)); return 4;
}
static Str read_string(Reader *r) {
    size_t start = ++r->pos, end = start, j = 0;
    char *out;
    /* Bound allocation by this string, not by the rest of the configuration. */
    while (end < r->input.n) {
        if (r->input.p[end] == '"') break;
        if (r->input.p[end++] == '\\' && end < r->input.n) end++;
    }
    if (end == r->input.n) { fail(r, "unterminated string"); return (Str){0}; }
    out = ds_alloc_uninit(r->a, end - start + 1);
    if (!out) return (Str){0};
    while (r->pos < end) {
        unsigned c = (unsigned char)r->input.p[r->pos++];
        if (c < 32) { fail(r, "control byte in string"); return (Str){0}; }
        if (c == '\\') {
            uint32_t cp, low;
            c = (unsigned char)r->input.p[r->pos++];
            switch (c) {
            case '"': case '/': case '\\': out[j++] = (char)c; break;
            case 'b': out[j++] = '\b'; break; case 'f': out[j++] = '\f'; break;
            case 'n': out[j++] = '\n'; break; case 'r': out[j++] = '\r'; break;
            case 't': out[j++] = '\t'; break;
            case 'u':
                if (!hex4(r, &cp)) { fail(r, "invalid Unicode escape"); return (Str){0}; }
                if (cp >= 0xd800 && cp <= 0xdbff) {
                    if (r->input.n - r->pos < 6 || memcmp(r->input.p + r->pos, "\\u", 2)) {
                        fail(r, "unpaired surrogate"); return (Str){0};
                    }
                    r->pos += 2;
                    if (!hex4(r, &low) || low < 0xdc00 || low > 0xdfff) {
                        fail(r, "unpaired surrogate"); return (Str){0};
                    }
                    cp = 0x10000 + ((cp - 0xd800) << 10) + low - 0xdc00;
                } else if (cp >= 0xdc00 && cp <= 0xdfff) {
                    fail(r, "unpaired surrogate"); return (Str){0};
                }
                if (r->pos > end) { fail(r, "invalid Unicode escape"); return (Str){0}; }
                j += utf8(out + j, cp); break;
            default: fail(r, "unknown escape"); return (Str){0};
            }
        } else if (c >= 128) {
            size_t k; uint32_t cp = ds_utf8(r->input.p + r->pos - 1, end - r->pos + 1, &k);
            if (cp == 0xfffd && k == 1) { fail(r, "invalid UTF-8"); return (Str){0}; }
            memcpy(out + j, r->input.p + r->pos - 1, k); j += k; r->pos += k - 1;
        } else out[j++] = (char)c;
    }
    out[j] = 0; r->pos = end + 1; return (Str){out, j};
}
static JValue *value(Reader *r, unsigned depth) {
    JValue *v; size_t start;
    whitespace(r);
    if (depth > 64 || r->pos == r->input.n) { fail(r, "missing value or nesting too deep"); return NULL; }
    v = ds_alloc(r->a, sizeof(*v)); if (!v) return NULL;
    start = r->pos;
    if (r->input.p[start] == '"') {
        v->type = J_STRING; v->text = read_string(r); return v->text.p ? v : NULL;
    }
    if (r->input.p[start] == '{' || r->input.p[start] == '[') {
        char close = r->input.p[r->pos++] == '{' ? '}' : ']';
        JValue **tail = &v->child;
        v->type = close == '}' ? J_OBJECT : J_ARRAY;
        whitespace(r);
        if (r->pos < r->input.n && r->input.p[r->pos] == close) { r->pos++; return v; }
        while (r->pos < r->input.n) {
            Str key = {0}; JValue *child, *previous;
            if (v->type == J_OBJECT) {
                whitespace(r);
                if (r->pos == r->input.n || r->input.p[r->pos] != '"') break;
                key = read_string(r); if (!key.p) return NULL;
                for (previous = v->child; previous; previous = previous->next)
                    if (ds_eq(previous->key, key)) { fail(r, "duplicate object key"); return NULL; }
                whitespace(r);
                if (r->pos == r->input.n || r->input.p[r->pos++] != ':') break;
            }
            child = value(r, depth + 1); if (!child) return NULL;
            child->key = key; *tail = child; tail = &child->next; v->count++;
            whitespace(r);
            if (r->pos == r->input.n) break;
            if (r->input.p[r->pos] == close) { r->pos++; return v; }
            if (r->input.p[r->pos++] != ',') break;
        }
        fail(r, "invalid object or array"); return NULL;
    }
    if (r->input.n - start >= 4 && !memcmp(r->input.p + start, "null", 4)) { r->pos += 4; return v; }
    if (r->input.n - start >= 4 && !memcmp(r->input.p + start, "true", 4)) {
        v->type = J_BOOL; v->boolean = 1; r->pos += 4; return v;
    }
    if (r->input.n - start >= 5 && !memcmp(r->input.p + start, "false", 5)) {
        v->type = J_BOOL; r->pos += 5; return v;
    }
    if (r->input.p[r->pos] == '-') r->pos++;
    if (r->pos < r->input.n && r->input.p[r->pos] == '0') r->pos++;
    else {
        size_t digit = r->pos;
        while (r->pos < r->input.n && r->input.p[r->pos] >= '0' && r->input.p[r->pos] <= '9') r->pos++;
        if (r->pos == digit) { fail(r, "invalid value"); return NULL; }
    }
    if (r->pos < r->input.n && r->input.p[r->pos] == '.') {
        size_t digit = ++r->pos;
        while (r->pos < r->input.n && r->input.p[r->pos] >= '0' && r->input.p[r->pos] <= '9') r->pos++;
        if (r->pos == digit) { fail(r, "invalid number"); return NULL; }
    }
    if (r->pos < r->input.n && (r->input.p[r->pos] == 'e' || r->input.p[r->pos] == 'E')) {
        size_t digit; r->pos++;
        if (r->pos < r->input.n && (r->input.p[r->pos] == '+' || r->input.p[r->pos] == '-')) r->pos++;
        digit = r->pos;
        while (r->pos < r->input.n && r->input.p[r->pos] >= '0' && r->input.p[r->pos] <= '9') r->pos++;
        if (r->pos == digit) { fail(r, "invalid exponent"); return NULL; }
    }
    v->type = J_NUMBER; v->text = ds_copy(r->a, (Str){r->input.p + start, r->pos - start});
    return v->text.p ? v : NULL;
}
JValue *ds_config_parse(Arena *a, Str input) {
    Reader r = {a, input, 0}; JValue *v;
    if (!input.p || input.n == SIZE_MAX) { snprintf(a->error, sizeof(a->error), "invalid JSON input"); return NULL; }
    v = value(&r, 0); whitespace(&r);
    if (r.pos != input.n) fail(&r, "trailing data");
    return a->error[0] ? NULL : v;
}
JValue *ds_config_get(JValue *v, const char *key) {
    JValue *c;
    if (!v || v->type != J_OBJECT) return NULL;
    for (c = v->child; c; c = c->next) if (ds_is(c->key, key)) return c;
    return NULL;
}
void ds_config_merge(Arena *a, JValue *base, const JValue *extra) {
    const JValue *c;
    for (c = extra->child; c && !a->error[0]; c = c->next) {
        JValue **link = &base->child, *copy;
        while (*link && !ds_eq((*link)->key, c->key)) link = &(*link)->next;
        if (*link && (*link)->type == J_OBJECT && c->type == J_OBJECT) ds_config_merge(a, *link, c);
        else {
            copy = ds_alloc(a, sizeof(*copy)); if (!copy) return;
            *copy = *c; copy->next = *link ? (*link)->next : NULL;
            if (!*link) base->count++;
            *link = copy;
        }
    }
}
int ds_config_equal(const JValue *a, const JValue *b) {
    const JValue *x, *y;
    if (!a || !b || a->type != b->type || a->count != b->count || a->boolean != b->boolean || !ds_eq(a->text,b->text)) return 0;
    for (x = a->child, y = b->child; x; x = x->next) {
        if (a->type == J_OBJECT) {
            for (y = b->child; y && !ds_eq(x->key,y->key); y = y->next) {}
        }
        if (!ds_config_equal(x,y)) return 0;
        if (a->type != J_OBJECT) y = y->next;
    }
    return 1;
}
/* Configuration serialization reuses a growable arena vector, including NULs
 * in escaped strings. Counts are lengths, never strlen of user input. */
static int put(Arena *a, Vec *v, char c) { char *p = ds_push(a,v,1); if (!p) return 0; *p=c; return 1; }
static int bytes(Arena *a, Vec *v, Str s) { size_t i; for (i=0;i<s.n;i++) if(!put(a,v,s.p[i]))return 0; return 1; }
static int quoted(Arena *a, Vec *v, Str s) {
    static const char hex[]="0123456789abcdef"; size_t i;
    if (!put(a,v,'"')) return 0;
    for(i=0;i<s.n;i++) {
        unsigned char c=(unsigned char)s.p[i];
        if(c=='"'||c=='\\') { if(!put(a,v,'\\')||!put(a,v,(char)c))return 0; }
        else if(c<32) { char x[]={'\\','u','0','0',hex[c>>4],hex[c&15]}; if(!bytes(a,v,(Str){x,6}))return 0; }
        else if(!put(a,v,(char)c)) return 0;
    }
    return put(a,v,'"');
}
static int emit(Arena *a, Vec *v, const JValue *j) {
    const JValue *c;
    if(j->type==J_STRING)return quoted(a,v,j->text);
    if(j->type==J_NUMBER)return bytes(a,v,j->text);
    if(j->type==J_NULL)return bytes(a,v,ds_str("null"));
    if(j->type==J_BOOL)return bytes(a,v,ds_str(j->boolean?"true":"false"));
    if(!put(a,v,j->type==J_ARRAY?'[':'{'))return 0;
    for(c=j->child;c;c=c->next) {
        if(c!=j->child&&!put(a,v,','))return 0;
        if(j->type==J_OBJECT&&(!quoted(a,v,c->key)||!put(a,v,':')))return 0;
        if(!emit(a,v,c))return 0;
    }
    return put(a,v,j->type==J_ARRAY?']':'}');
}
Str ds_config_write(Arena *a,const JValue *j) {
    Vec v={0}; if(!emit(a,&v,j)||!put(a,&v,0))return(Str){0}; return(Str){v.p,v.n-1};
}
