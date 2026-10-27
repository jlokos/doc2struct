#ifndef DOC2STRUCT_H
#define DOC2STRUCT_H
#include <stddef.h>
#include <stdint.h>
#define PCRE2_CODE_UNIT_WIDTH 8
#include "pcre2.h"

typedef struct {
    const char *p;
    size_t n;
} Str;
typedef struct Block Block;
typedef struct {
    Block *blocks;
    char error[256];
} Arena;
typedef struct {
    Str key;
    void *value;
    uint64_t hash;
} Entry;
typedef struct {
    Entry *entries;
    size_t n, cap;
} Map;
typedef struct {
    void *p;
    size_t n, cap;
} Vec;
typedef struct {
    unsigned flags;
    double font, indent;
    int has_font, display_none, vis_hidden;
} Style;
enum { A_STYLE, A_COLSPAN, A_ROWSPAN, A_HREF, A_SRC, A_ALT, A_HIDDEN, A_COUNT };
typedef struct {
    Str value[A_COUNT];
} Attrs;
enum { TEXT, START, END };
enum {
    BOLD = 1,
    ITALIC = 2,
    UNDERLINE = 4,
    CENTERED = 8,
    ALL_CAPS = 16,
    PROPER_CASE = 32,
    FAKE_TABLE = 64
};
typedef struct {
    size_t block, line, row, col, rowspan, colspan;
    Str text, href, tag, src;
    unsigned flags;
    double font, indent;
    int in_table, has_font, has_indent, font_float, indent_float;
} Run;
typedef struct {
    int kind;
    Str value;
    Attrs attrs;
} Token;
typedef struct {
    int hide_hidden_attr, hide_visibility;
    size_t max_span;
} Options;
typedef struct Regex {
    pcre2_code *code;
    unsigned groups;
    struct Regex *next;
} Regex;
typedef struct {
    Str name;
    Regex *rx;
    int level;
    unsigned
        requires;
} Header;
typedef struct {
    Regex *rx;
    int needs_href;
} Remove;
typedef struct {
    Str name, source, dtype, which;
    Str *types;
    size_t ntypes;
    int filter_types;
    Regex *rx;
} Column;
typedef struct {
    Arena arena;
    Regex *regexes;
    Header *headers;
    size_t nheaders;
    Remove *remove;
    size_t nremove;
    Column *columns;
    size_t ncolumns;
    long repeat_threshold;
    unsigned table_steps;
    int single_row_to_text, title_from_section;
    long footnote_lines, preamble_lines, postamble_lines;
    Regex *footnote;
} Rules;
typedef struct {
    Run run;
    int fake_table;
} Item;
typedef struct {
    Str *cells;
    size_t nr, nc;
} Matrix;
typedef struct {
    Item *items;
    size_t nitems;
    Matrix matrix;
    int level, predicted;
    unsigned attrs;
    Str klass, title;
} Line;
typedef struct {
    Str id, text;
} Note;
typedef struct {
    size_t id, level;
    Str type, klass, title, text, preamble, postamble;
    Matrix matrix;
    int cleaned, removed;
    Item *items;
    size_t nitems;
    Note *notes;
    size_t nnotes;
} Row;
typedef struct {
    Arena arena;
    Vec runs, tokens, rows;
    Map styles, tags;
    pcre2_match_data *match;
    size_t match_pairs;
} Document;
typedef int (*TokenSink)(void *, int, Str, const Attrs *);

Str ds_str(const char *s);
int ds_eq(Str a, Str b);
int ds_is(Str a, const char *s);
void *ds_alloc(Arena *, size_t);
void ds_arena_free(Arena *);
void *ds_push(Arena *, Vec *, size_t);
void *ds_map_get(Map *, Str);
int ds_map_put(Arena *, Map *, Str, void *);
Str ds_copy(Arena *, Str);
Str ds_cat(Arena *, Str, Str);
Str ds_join(Arena *, Str *, size_t, Str);
Str ds_strip(Str, int);
Str ds_lower(Arena *, Str);
int ds_space(uint32_t);
int ds_upper(Str);
int ds_proper(Str);
uint32_t ds_utf8(const char *, size_t, size_t *);
Str ds_input(Arena *, Str);
Str ds_unescape(Arena *, Str);
int ds_tokenize(Document *, Str, TokenSink, void *);
int ds_void(Str);
void *ds_normalizer(Document *, Options);
int ds_normalize_token(void *, int, Str, const Attrs *);
int ds_normalize_finish(void *);
int ds_standardize(Document *, const Rules *);
int ds_tables(Document *, const Rules *);
Regex *ds_regex(Rules *, Str, int);
int ds_match(Document *, Regex *, Str, int);
Str ds_group(Document *, Str, unsigned);
void ds_rules_free(Rules *);
void ds_document_free(Document *);
unsigned ds_style_bit(Str);
extern const char *ds_table_steps[];
#endif
