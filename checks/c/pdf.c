#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s (%s)\n",__LINE__,#x,error.message); return 1; } } while (0)
typedef struct { size_t pages, glyphs; int cancel; } Seen;
static int visit(void *context, const doc2struct_pdf_page *page) {
    Seen *seen=context;
    size_t i;
    if(seen->cancel) return 0;
    if(page->index!=seen->pages || page->width<=0 || page->height<=0) return 0;
    for(i=0;i<page->count;i++) {
        const doc2struct_pdf_glyph *g=page->glyphs+i;
        if(g->left>g->right || g->top>g->bottom || g->font<=0) return 0;
    }
    seen->pages++;
    seen->glyphs+=page->count;
    return 1;
}
int main(int argc, char **argv) {
    doc2struct_error error={{0}};
    doc2struct_rules *rules;
    doc2struct_parser *parser;
    doc2struct_document *staged, *fused;
    doc2struct_string input;
    char *data, *a, *b;
    size_t na, nb, count;
    long length;
    FILE *file;
    Seen seen={0};
    CHECK(argc==3);
    CHECK(doc2struct_pdfium_init(argv[1],&error));
    CHECK(doc2struct_pdfium_init(argv[1],&error));
    CHECK(!doc2struct_pdfium_init("different-library",&error));
    file=fopen(argv[2],"rb"); CHECK(file);
    CHECK(!fseek(file,0,SEEK_END)); length=ftell(file); CHECK(length>0);
    rewind(file); data=malloc((size_t)length); CHECK(data);
    CHECK(fread(data,1,(size_t)length,file)==(size_t)length); fclose(file);
    input=(doc2struct_string){data,(size_t)length};
    CHECK(doc2struct_pdf_visit(input,NULL,visit,&seen,&error));
    CHECK(seen.pages==3 && seen.glyphs>20);
    seen.cancel=1;
    CHECK(!doc2struct_pdf_visit(input,NULL,visit,&seen,&error));
    rules=doc2struct_rules_preset("SEC:10-K",&error); CHECK(rules);
    parser=doc2struct_parser_new(1024*1024,&error); CHECK(parser);
    staged=doc2struct_pdf_instructions(parser,input,NULL,&error); CHECK(staged);
    CHECK(doc2struct_document_runs(staged,&count) && count==3);
    CHECK(doc2struct_standardize(staged,rules));
    fused=doc2struct_parse_pdf(NULL,input,rules,NULL,&error); CHECK(fused);
    a=doc2struct_document_json(staged,rules,1,&na,&error); CHECK(a);
    b=doc2struct_document_json(fused,rules,1,&nb,&error); CHECK(b);
    CHECK(na==nb && !memcmp(a,b,na));
    doc2struct_buffer_free(a); doc2struct_buffer_free(b);
    doc2struct_document_free(staged); doc2struct_document_free(fused);
    CHECK(doc2struct_parser_cached_bytes(parser)<=1024*1024);
    CHECK(!doc2struct_parse_pdf(parser,(doc2struct_string){"bad",3},rules,NULL,&error));
    fused=doc2struct_parse_pdf(parser,input,rules,NULL,&error); CHECK(fused);
    doc2struct_document_free(fused);
    doc2struct_parser_close(parser);
    CHECK(!doc2struct_parse_pdf(parser,input,rules,NULL,&error));
    doc2struct_parser_free(parser); doc2struct_rules_free(rules); free(data);
    puts("PASS: native PDF extraction, cancellation, staged/fused parity, cache and errors");
    return 0;
}
