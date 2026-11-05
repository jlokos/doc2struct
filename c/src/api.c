#include "doc2struct.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static void error(doc2struct_error *e,const char *message) {
    if(e)snprintf(e->message,sizeof(e->message),"%s",message);
}
doc2struct_parser *doc2struct_parser_new(size_t cache_size,doc2struct_error *e) {
    ParserContext *p=malloc(sizeof(*p));if(e)e->message[0]=0;
    if(!p){error(e,"out of memory");return NULL;}ds_parser_init(p,cache_size);return p;
}
void doc2struct_parser_clear(doc2struct_parser *p) { if(p)ds_parser_clear(p); }
void doc2struct_parser_close(doc2struct_parser *p) { if(p){p->pool.limit=0;p->closed=1;ds_parser_clear(p);} }
void doc2struct_parser_free(doc2struct_parser *p) { if(p){ds_parser_clear(p);free(p);} }
size_t doc2struct_parser_cache_limit(const doc2struct_parser *p) { return p?p->pool.limit:0; }
size_t doc2struct_parser_cached_bytes(const doc2struct_parser *p) { return p?p->pool.bytes:0; }
doc2struct_document *doc2struct_document_new(doc2struct_error *e) {
    Document *d=calloc(1,sizeof(*d));if(e)e->message[0]=0;if(!d)error(e,"out of memory");return d;
}
void doc2struct_document_free(doc2struct_document *d) { if(d){ds_document_free(d);free(d);} }
void doc2struct_document_detach_cache(doc2struct_document *d) { if(d)d->arena.pool=NULL; }
const char *doc2struct_document_error(const doc2struct_document *d) { return d?d->arena.error:"out of memory"; }
Str doc2struct_document_copy(doc2struct_document *d,Str text) { return d?ds_copy(&d->arena,text):(Str){0}; }
doc2struct_document *doc2struct_parse(doc2struct_parser *p,Str input,const doc2struct_rules *r,
                                    doc2struct_error *e) {
    Document *d;int ok;
    if(e)e->message[0]=0;
    if(!r||(!input.p&&input.n)||(p&&p->closed)) {
        error(e,"invalid parser, rules or input");return NULL;
    }
    if(!input.p)input=ds_str("");
    d=doc2struct_document_new(e);if(!d)return NULL;
    ok=p?ds_parser_parse(p,d,input,r):ds_parse(d,input,r);
    if(!ok){error(e,d->arena.error[0]?d->arena.error:"parsing failed");doc2struct_document_free(d);return NULL;}
    return d;
}
const doc2struct_row *doc2struct_document_rows(const doc2struct_document *d,size_t *count) {
    if(count)*count=d?d->rows.n:0;return d?d->rows.p:NULL;
}
const doc2struct_run *doc2struct_document_runs(const doc2struct_document *d,size_t *count) {
    if(count)*count=d?d->runs.n:0;return d?d->runs.p:NULL;
}
static int token_sink(void *ctx,int kind,Str value,const Attrs *attrs) { return ds_store_token(ctx,kind,value,attrs); }
int doc2struct_tokenize(doc2struct_document *d,Str input) {
    Str text;
    if(!d||(!input.p&&input.n))return 0;
    if(!input.p)input=ds_str("");
    text=ds_input(&d->arena,input);return text.p&&ds_tokenize(d,text,token_sink,d);
}
size_t doc2struct_token_count(const doc2struct_document *d) { return d?d->tokens.n:0; }
const doc2struct_token *doc2struct_token_next(const doc2struct_document *d,doc2struct_token_iterator *it) {
    const TokenChunk *c=it->chunk;
    if(!c){if(it->index)return NULL;c=d->tokens.first;}
    else if(it->index==c->used){c=c->next;it->index=0;}
    it->chunk=c;
    if(!c){it->index=1;return NULL;}
    return c->data+it->index++;
}
doc2struct_token *doc2struct_add_token(doc2struct_document *d) {
    Token *t=ds_new_token(d);if(t)*t=(Token){0};return t;
}
doc2struct_attributes *doc2struct_add_attributes(doc2struct_document *d) { return ds_alloc(&d->arena,sizeof(Attrs)); }
int doc2struct_normalize(doc2struct_document *d,const Rules *r) {
    void *normalizer;TokenChunk *chunk;size_t i;Attrs empty={0};
    if(!d||!r)return 0;
    d->no_fonts=0;
    normalizer=ds_normalizer(d,r->html);if(!normalizer)return 0;
    for(chunk=d->tokens.first;chunk;chunk=chunk->next)
        for(i=0;i<chunk->used;i++) {
            Token *t=chunk->data+i;
            if(!ds_normalize_token(normalizer,t->kind,t->value,t->attrs?t->attrs:&empty))return 0;
        }
    return ds_normalize_finish(normalizer);
}
doc2struct_run *doc2struct_add_run(doc2struct_document *d) { d->no_fonts=0; return ds_push(&d->arena,&d->runs,sizeof(Run)); }
int doc2struct_standardize(doc2struct_document *d,const doc2struct_rules *r) { return d&&r&&ds_standardize(d,r); }
const doc2struct_run *doc2struct_row_item(const doc2struct_row *r,size_t i) { return i<r->nitems?&r->items[i].run:NULL; }
const Str *doc2struct_row_links(const doc2struct_row *r,size_t i,size_t *count) {
    Vec *links=i<r->nitems?r->items[i].hrefs:NULL;
    if(count)*count=links?links->n:0;return links?links->p:NULL;
}
int doc2struct_column_applies(const doc2struct_column *c,const doc2struct_row *r) {
    size_t i;
    if(ds_is(r->type,"table"))return 0;
    if(c->filter_types) {
        for(i=0;i<c->ntypes;i++)if(ds_eq(r->type,c->types[i]))break;
        if(i==c->ntypes)return 0;
    }
    if(c->filter_classes) {
        for(i=0;i<c->nclasses;i++)if(ds_eq(r->klass,c->classes[i]))break;
        if(i==c->nclasses)return 0;
    }
    return 1;
}
int doc2struct_column_text(doc2struct_document *d,const doc2struct_column *c,Str input,Str *result) {
    *result=input;
    if(input.p) {
        if(c->rx) {
            if(ds_match(d,c->rx,input,1))
                *result=c->value.p?ds_column_replace(d,c,input):ds_group(d,input,c->rx->groups?1:0);
            else *result=(Str){0};
        } else if(c->value.p) *result=c->value;
    }
    return !d->arena.error[0];
}
const char *doc2struct_cleanup_name(size_t i) { return i<11?ds_cleanup_names[i]:NULL; }
char *doc2struct_document_json(doc2struct_document *d,const doc2struct_rules *r,int with_rules,
                              size_t *size,doc2struct_error *e) {
    Arena arena={0};Str json;char *out=NULL;size_t i;
    if(size)*size=0;if(e)e->message[0]=0;
    if(!d||!r){error(e,"document and rules are required");return NULL;}
    for(i=0;i<r->ncolumns;i++)
        if((!ds_is(r->columns[i].source,"header_title")&&!ds_is(r->columns[i].source,"text"))||
           !ds_is(r->columns[i].dtype,"str")) {
            error(e,"native JSON supports only string text/header_title custom columns; use row and column views");return NULL;
        }
    json=ds_json(d,r,with_rules,&arena);
    if(json.p) {
        out=malloc(json.n+1);
        if(out){memcpy(out,json.p,json.n+1);if(size)*size=json.n;}else error(e,"out of memory");
    }else error(e,arena.error);
    ds_arena_free(&arena);return out;
}
void doc2struct_buffer_free(void *p) { free(p); }
