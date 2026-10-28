#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static int equals(doc2struct_string s, const char *value) {
    return s.n == strlen(value) && !memcmp(s.p, value, s.n);
}
int main(void) {
    doc2struct_error error;
    doc2struct_parser *parser = doc2struct_parser_new(1024 * 1024, &error);
    doc2struct_rules *rules = doc2struct_rules_preset(NULL, &error);
    doc2struct_document *document;
    const doc2struct_run *runs;
    const doc2struct_row *rows;
    size_t count, i, tables = 0;
    char source[] = "<TABLE>\n<S>       <C>\nAlpha     12\nBeta      24\nGamma     36\n</TABLE>";
    doc2struct_string input = {source, sizeof(source)-1};
    CHECK(parser && rules);
    document = doc2struct_partialsgml_instructions(parser, input, 8, &error);
    CHECK(document);
    memset(source, '!', sizeof(source)-1); /* The result must own its strings. */
    runs = doc2struct_document_runs(document, &count);
    CHECK(count == 6 && equals(runs[0].text, "Alpha") && equals(runs[1].text, "12"));
    CHECK(runs[0].in_table && runs[0].row == 0 && runs[1].col == 1);
    CHECK(!runs[0].has_font && runs[0].line == 2);
    CHECK(doc2struct_standardize(document, rules));
    rows = doc2struct_document_rows(document, &count);
    for (i = 0; i < count; i++) if (equals(rows[i].type, "table")) {
        CHECK(rows[i].matrix.nr == 3 && rows[i].matrix.nc == 2);
        CHECK(equals(rows[i].matrix.cells[5], "36")); tables++;
    }
    CHECK(tables == 1);
    doc2struct_document_free(document);
    CHECK(doc2struct_parser_cached_bytes(parser) <= doc2struct_parser_cache_limit(parser));
    input = (doc2struct_string){"literal <PAGE>",14};
    document = doc2struct_text_instructions(parser, input, 8, &error);
    CHECK(document);
    runs = doc2struct_document_runs(document, &count);
    CHECK(count == 1 && equals(runs[0].text, "literal <PAGE>"));
    doc2struct_document_free(document);
    CHECK(!doc2struct_text_instructions(parser, input, 0, &error) && error.message[0]);
    doc2struct_parser_close(parser);
    CHECK(!doc2struct_partialsgml_instructions(parser, input, 8, &error));
    doc2struct_parser_free(parser); doc2struct_rules_free(rules);
    puts("PASS: native text/SGML, standardization, ownership, cache and invalid inputs");
    return 0;
}
