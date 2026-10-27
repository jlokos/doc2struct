#ifndef DOC2STRUCT_PUBLIC_H
#define DOC2STRUCT_PUBLIC_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define DOC2STRUCT_VERSION "0.1.0"
#define DOC2STRUCT_DEFAULT_CACHE_SIZE ((size_t)8 * 1024 * 1024)
typedef struct doc2struct_rules doc2struct_rules;
typedef struct doc2struct_parser doc2struct_parser;
typedef struct doc2struct_document doc2struct_document;
typedef struct doc2struct_item doc2struct_item;
typedef struct doc2struct_regex doc2struct_regex;
typedef struct doc2struct_style doc2struct_style;
typedef struct { const char *p; size_t n; } doc2struct_string;
typedef struct { char message[256]; } doc2struct_error;
typedef struct {
    int hide_hidden_attr, hide_visibility;
    size_t max_span;
} doc2struct_options;

enum { DOC2STRUCT_TEXT, DOC2STRUCT_START, DOC2STRUCT_END };
enum { DOC2STRUCT_STYLE, DOC2STRUCT_COLSPAN, DOC2STRUCT_ROWSPAN, DOC2STRUCT_HREF,
       DOC2STRUCT_SRC, DOC2STRUCT_ALT, DOC2STRUCT_HIDDEN, DOC2STRUCT_ATTRIBUTE_COUNT };
typedef struct {
    doc2struct_string value[DOC2STRUCT_ATTRIBUTE_COUNT];
    doc2struct_style *prepared_style; /* Library-owned; leave NULL on input. */
} doc2struct_attributes;
typedef struct {
    int kind;
    doc2struct_string value;
    doc2struct_attributes *attrs;
} doc2struct_token;
typedef struct { const void *chunk; size_t index; } doc2struct_token_iterator;

/* Records are borrowed views, valid until their document/rules are freed.
 * Only records returned by add_token/add_run may be populated by the caller. */
typedef struct {
    size_t block, line, row, col, rowspan, colspan;
    doc2struct_string text, href, tag, src;
    unsigned flags;
    double font, indent;
    int in_table, has_font, has_indent, font_float, indent_float;
} doc2struct_run;
typedef struct { doc2struct_string *cells; size_t nr, nc; } doc2struct_matrix;
typedef struct { doc2struct_string id, text; } doc2struct_note;
typedef struct {
    size_t id, level;
    doc2struct_string type, klass, title, text, preamble, postamble;
    doc2struct_matrix matrix;
    int cleaned, removed;
    doc2struct_item *items;
    size_t nitems;
    doc2struct_note *notes;
    size_t nnotes;
} doc2struct_row;
typedef struct {
    doc2struct_string name, source, dtype, which;
    doc2struct_string *types;
    size_t ntypes;
    int filter_types;
    doc2struct_regex *rx; /* Opaque compiled pattern; use column_text to match. */
} doc2struct_column;

/* NULL name loads defaults. Names and SEC document aliases are case-insensitive.
 * JSON accepts a partial rules object; defaults and validation live in C.
 * Rules are immutable after creation and may be shared by independent parsers. */
doc2struct_rules *doc2struct_rules_preset(const char *name, doc2struct_error *error);
doc2struct_rules *doc2struct_rules_json(const char *json, size_t size, doc2struct_error *error);
void doc2struct_rules_free(doc2struct_rules *rules);
const doc2struct_column *doc2struct_rules_columns(const doc2struct_rules *, size_t *count);
/* Embedded canonical JSON, valid for the lifetime of the library. */
size_t doc2struct_preset_count(void);
const char *doc2struct_preset_namespace(size_t index);
doc2struct_string doc2struct_preset_pack(size_t index);
doc2struct_string doc2struct_defaults_json(void);
/* Resolve a partial object or preset to a fully defaulted JSON rules object.
 * Free the returned buffer with doc2struct_buffer_free. */
char *doc2struct_rules_resolve(const char *input, size_t size, int preset,
                             size_t *output_size, doc2struct_error *error);
/* Append extra headers/columns. Replace remove/tables only when extra differs
 * from defaults. Inputs are JSON objects; output uses buffer_free. */
char *doc2struct_rules_merge_json(doc2struct_string base, doc2struct_string extra,
                                size_t *output_size, doc2struct_error *error);

doc2struct_options doc2struct_options_default(void);
doc2struct_parser *doc2struct_parser_new(size_t cache_size, doc2struct_error *error);
void doc2struct_parser_clear(doc2struct_parser *);
void doc2struct_parser_close(doc2struct_parser *);
void doc2struct_parser_free(doc2struct_parser *);
size_t doc2struct_parser_cache_limit(const doc2struct_parser *);
size_t doc2struct_parser_cached_bytes(const doc2struct_parser *);

/* Input and rules must outlive the result. A parser must outlive every result
 * using its cache. Each parser is single-owner: serialize its operations,
 * including releasing cached documents. Independent parsers may run in parallel.
 * Pass NULL parser to use an independent document allocation. */
doc2struct_document *doc2struct_parse(doc2struct_parser *, doc2struct_string input,
                                    const doc2struct_rules *, doc2struct_options,
                                    doc2struct_error *error);
void doc2struct_document_free(doc2struct_document *);
void doc2struct_document_detach_cache(doc2struct_document *);
const char *doc2struct_document_error(const doc2struct_document *);
const doc2struct_row *doc2struct_document_rows(const doc2struct_document *, size_t *count);
/* Standard columns only; custom columns return an error. Adapters can obtain
 * their source values through row_item/row_links/column_text below. */
char *doc2struct_document_json(doc2struct_document *, const doc2struct_rules *, int with_rules,
                              size_t *size, doc2struct_error *error);
void doc2struct_buffer_free(void *);

/* Staged parsing API used by adapters and native diagnostic tools. */
doc2struct_document *doc2struct_document_new(doc2struct_error *);
doc2struct_string doc2struct_document_copy(doc2struct_document *, doc2struct_string);
int doc2struct_tokenize(doc2struct_document *, doc2struct_string);
size_t doc2struct_token_count(const doc2struct_document *);
const doc2struct_token *doc2struct_token_next(const doc2struct_document *, doc2struct_token_iterator *);
doc2struct_token *doc2struct_add_token(doc2struct_document *);
doc2struct_attributes *doc2struct_add_attributes(doc2struct_document *);
int doc2struct_normalize(doc2struct_document *, doc2struct_options);
doc2struct_run *doc2struct_add_run(doc2struct_document *);
const doc2struct_run *doc2struct_document_runs(const doc2struct_document *, size_t *count);
int doc2struct_standardize(doc2struct_document *, const doc2struct_rules *);
const doc2struct_run *doc2struct_row_item(const doc2struct_row *, size_t index);
const doc2struct_string *doc2struct_row_links(const doc2struct_row *, size_t index, size_t *count);
int doc2struct_column_text(doc2struct_document *, const doc2struct_column *, doc2struct_string,
                          doc2struct_string *result);
const char *doc2struct_cleanup_name(size_t index);

#ifdef __cplusplus
}
#endif
#endif
