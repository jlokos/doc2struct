/* Exhaust every byte at each position around SIMD boundaries and alignments.
 * Exact-sized input/output allocations let ASan detect overreads and writes.
 * This target needs neither the PDFium runtime nor Python. */
#include "scan.h"
#include <stdio.h>
#include <stdlib.h>

static void check(const char *name, size_t actual, size_t expected,
                  size_t n, size_t offset, size_t pos, unsigned byte) {
    if (actual != expected) {
        fprintf(stderr, "%s: got %zu, wanted %zu (n=%zu offset=%zu pos=%zu byte=%u)\n",
                name, actual, expected, n, offset, pos, byte);
        exit(1);
    }
}

int main(void) {
    static const size_t lengths[] = {0, 1, 2, 7, 8, 15, 16, 17, 31, 32, 33,
                                     47, 48, 49, 63, 64, 65, 95, 96, 97, 127, 128, 129};
    size_t length, offset, pos, tests = 0;
    unsigned byte;
    for (length = 0; length < sizeof(lengths) / sizeof(*lengths); length++) {
        size_t n = lengths[length];
        for (offset = 0; offset < 32; offset++) {
            size_t allocation = n + offset ? n + offset : 1;
            char *base = malloc(allocation), *out_base = malloc(allocation), *p, *out;
            if (!base || !out_base) return 2;
            p = base + offset;
            out = out_base + offset;
            memset(p, 'a', n);
#define CHECK(name, actual, expected) check(name, actual, expected, n, offset, pos, byte)
            for (pos = 0; pos <= n; pos++) {
                for (byte = 0; byte < 256; byte++) {
                    int present = pos < n, upper = byte >= 'A' && byte <= 'Z';
                    size_t i;
                    if (present) p[pos] = (char)byte;
                    memcpy(out, p, n);
                    CHECK("equal bytes", ds_bytes_equal(p, out, n), 1);
                    if (present) {
                        out[pos] ^= 1;
                        CHECK("different bytes", ds_bytes_equal(p, out, n), 0);
                    }
                    CHECK("nonascii", ds_nonascii(p, n), present && byte >= 128 ? pos : n);
                    CHECK("upper", ds_upper_or_nonascii(p, n), present && (upper || byte >= 128) ? pos : n);
                    CHECK("line", ds_text_line_end(p, n), present && (byte == '\n' || byte == '\r' || byte == '\f') ? pos : n);
                    CHECK("span", ds_text_span(p, n, 0), present && (byte < 32 || byte >= 128) ? pos : n);
                    CHECK("markup", ds_text_span(p, n, 1), present && (byte < 32 || byte >= 128 || byte == '<') ? pos : n);
                    CHECK("tag", ds_tag_mark(p, n), present && (byte == '>' || byte == '"' || byte == '\'') ? pos : n);
                    CHECK("quote", ds_quote_or_amp(p, n, '"'), present && (byte == '"' || byte == '&') ? pos : n);
                    CHECK("apostrophe", ds_quote_or_amp(p, n, '\''), present && (byte == '\'' || byte == '&') ? pos : n);
                    CHECK("json", ds_json_escape(p, n), present && (byte < 32 || byte == '"' || byte == '\\') ? pos : n);
                    CHECK("lower changed", ds_ascii_lower(out, p, n), present && upper);
                    for (i = 0; i < n; i++) {
                        unsigned expected = i == pos ? (upper ? byte + 32 : byte) : 'a';
                        CHECK("lower bytes", (unsigned char)out[i], expected);
                    }
                    CHECK("in-place changed", ds_ascii_lower(p, p, n), present && upper);
                    if (n && memcmp(p, out, n)) return 3;
                    if (present) p[pos] = 'a';
                    tests++;
                }
            }
            memset(p, ' ', n);
            for (pos = 0; pos <= n; pos++)
                for (byte = 0; byte < 256; byte++) {
                    if (pos < n) p[pos] = (char)byte;
                    CHECK("spaces", ds_text_spaces(p, n), pos < n && byte != ' ' ? pos : n);
                    if (pos < n) p[pos] = ' ';
                }
#undef CHECK
            free(base);
            free(out_base);
        }
    }
    printf("%zu byte/position/alignment cases passed\n", tests);
    return 0;
}
