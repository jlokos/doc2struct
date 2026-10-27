#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if(!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static doc2struct_string view(const char *s) { return (doc2struct_string){s,strlen(s)}; }
static int equals(doc2struct_string s,const char *value) { return s.n==strlen(value)&&!memcmp(s.p,value,s.n); }

int main(void) {
    const char *html="<h1>Item 1. Business</h1><p>Revenue &amp; growth.</p>"
        "<table><tr><td>Year</td><td>Amount</td></tr><tr><td>2025</td><td>123</td></tr></table>";
    const char *custom="{\"columns\":[{\"name\":\"revenue\",\"source\":\"text\",\"pattern\":\"(Revenue)\"}]}";
    const char *invalid[]={"{", "[]", "{\"headers\":null}", "{\"name\":\"x\",\"name\":\"y\"}",
        "{\"name\":\"\\ud800\"}", "{\"headers\":[{\"name\":\"x\",\"level\":0,\"regex\":\"(\"}]}",
        "{\"tables\":{\"steps\":[\"unknown\"]}}", "{\"columns\":[{\"name\":\"text\",\"source\":\"text\"}]}",
        "{\"tables\":{\"preamble_lines\":999999999999999999999999}}", "{} trailing"};
    doc2struct_error e;doc2struct_options options=doc2struct_options_default();
    doc2struct_rules *rules=doc2struct_rules_preset(" sec:10-k ",&e),*extra;
    doc2struct_parser *parser=doc2struct_parser_new(1024*1024,&e);
    doc2struct_document *d,*staged;const doc2struct_row *rows;size_t n,i,size;char *json,*other;
    CHECK(rules&&parser);CHECK(doc2struct_preset_count()>0);
    d=doc2struct_parse(parser,view(html),rules,options,&e);CHECK(d);
    rows=doc2struct_document_rows(d,&n);CHECK(rows&&n>=3);
    for(i=0;i<n;i++)if(equals(rows[i].klass,"item"))break;
    CHECK(i<n);
    json=doc2struct_document_json(d,rules,1,&size,&e);CHECK(json&&size&&strstr(json,"Revenue & growth."));
    staged=doc2struct_document_new(&e);CHECK(staged);
    CHECK(doc2struct_tokenize(staged,view(html))&&doc2struct_token_count(staged)>0);
    {doc2struct_token_iterator it={0};size_t count=0;
     while(doc2struct_token_next(staged,&it))count++;
     CHECK(count==doc2struct_token_count(staged));CHECK(!doc2struct_token_next(staged,&it));}
    CHECK(doc2struct_normalize(staged,options));CHECK(doc2struct_standardize(staged,rules));
    other=doc2struct_document_json(staged,rules,1,&size,&e);CHECK(other&&!strcmp(json,other));
    doc2struct_buffer_free(json);doc2struct_buffer_free(other);doc2struct_document_free(staged);
    doc2struct_document_free(d);CHECK(doc2struct_parser_cached_bytes(parser)>0);
    doc2struct_parser_clear(parser);CHECK(!doc2struct_parser_cached_bytes(parser));
    extra=doc2struct_rules_json(custom,strlen(custom),&e);CHECK(extra);
    d=doc2struct_parse(parser,view("<p>Revenue &amp; growth.</p>"),extra,options,&e);CHECK(d);
    {size_t nc;const doc2struct_column *columns=doc2struct_rules_columns(extra,&nc);int found=0;
     CHECK(nc==1);rows=doc2struct_document_rows(d,&n);
     for(i=0;i<n;i++)if(rows[i].text.p){doc2struct_string result;
        CHECK(doc2struct_column_text(d,columns,rows[i].text,&result));if(equals(result,"Revenue"))found=1;}
     CHECK(found);CHECK(!doc2struct_document_json(d,extra,1,&size,&e));CHECK(e.message[0]);}
    doc2struct_parser_close(parser);CHECK(doc2struct_parser_cache_limit(parser)==0);
    doc2struct_document_free(d);CHECK(!doc2struct_parser_cached_bytes(parser));
    CHECK(!doc2struct_parse(parser,view(html),rules,options,&e));
    doc2struct_parser_free(parser);doc2struct_rules_free(extra);doc2struct_rules_free(rules);
    for(i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        rules=doc2struct_rules_json(invalid[i],strlen(invalid[i]),&e);CHECK(!rules&&e.message[0]);
    }
    CHECK(!doc2struct_rules_preset("SEC:not-a-type",&e));
    json=doc2struct_rules_merge_json(view("{}"),view(custom),&size,&e);CHECK(json);
    rules=doc2struct_rules_json(json,size,&e);CHECK(rules);doc2struct_rules_columns(rules,&n);CHECK(n==1);
    doc2struct_rules_free(rules);doc2struct_buffer_free(json);
    /* Unicode and embedded NUL strings must survive resolution. */
    {
        const char *unicode="{\"name\":\"\\ud83d\\ude80\\u0000\"}";
        json=doc2struct_rules_resolve(unicode,strlen(unicode),0,&size,&e);
    }
    CHECK(json&&strstr(json,"\\u0000"));doc2struct_buffer_free(json);
    puts("native end-to-end checks passed");return 0;
}
