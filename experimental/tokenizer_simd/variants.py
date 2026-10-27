"""Source transformations applied only to the frozen experimental snapshot."""


def replace(source, old, new):
    assert old in source, old[:100]
    return source.replace(old, new)


def helper(source, code):
    return replace(source, "static int space_at(", code + "\nstatic int space_at(")


def bulk_skip(source):
    source = replace(source, '''            while (j + 3 <= n && memcmp(html.p + j, "-->", 3))
                j++;''', '''            while (j + 3 <= n) {
                const char *mark = memchr(html.p + j, '-', n - j - 2);
                if (!mark) { j = n; break; }
                j = (size_t)(mark - html.p);
                if (html.p[j + 1] == '-' && html.p[j + 2] == '>') break;
                j++;
            }''')
    source = replace(source, '''            while (j < n && html.p[j] != '>')
                j++;''', '''            {
                const char *mark = memchr(html.p + j, '>', n - j);
                j = mark ? (size_t)(mark - html.p) : n;
            }''')
    return replace(source, '''            while (q + 2 + tag.n <= n) {
                if (html.p[q] == '<' ''', '''            while (q + 2 + tag.n <= n) {
                const char *mark = memchr(html.p + q, '<', n - q - 1 - tag.n);
                if (!mark) break;
                q = (size_t)(mark - html.p);
                if (html.p[q] == '<' ''')


TEXT_HELPER = r'''
static size_t lab_text_end(const char *p, size_t n, int *entity) {
    size_t i = 0;
#ifdef DS_SSE2
    const __m128i lt = _mm_set1_epi8('<'), amp = _mm_set1_epi8('&');
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(p + i));
        unsigned ends = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(data, lt));
        unsigned amps = (unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(data, amp));
        if (ends) {
            unsigned bit = ds_first_bit(ends);
            *entity |= (amps & ((1u << bit) - 1)) != 0;
            return i + bit;
        }
        *entity |= amps != 0;
    }
#endif
    for (; i < n && p[i] != '<'; i++) *entity |= p[i] == '&';
    return i;
}
'''


def fused_text(source):
    source = helper(source, TEXT_HELPER)
    source = replace(source, "TokenSink sink, void *ctx, Str text) {", "TokenSink sink, void *ctx, Str text, int entity) {")
    source = replace(source, "return sink(ctx, TEXT, ds_unescape(&d->arena, text), NULL);",
                     "return sink(ctx, TEXT, entity ? ds_unescape(&d->arena, text) : text, NULL);")
    source = replace(source, "size_t i = 0, pos = 0, n = html.n;", "size_t i = 0, pos = 0, n = html.n;\n    int text_entity = 0;")
    source = replace(source, "        if (html.p[i] != '<') {", "        if (i == pos) text_entity = 0;\n        if (html.p[i] != '<') {")
    source = replace(source, '''            const char *next = memchr(html.p + i, '<', n - i);
            if (!next)
                break;
            i = start = (size_t)(next - html.p);''', '''            i += lab_text_end(html.p + i, n - i, &text_entity);
            if (i == n) break;
            start = i;''')
    source = replace(source, "(Str){html.p + pos, start - pos}))", "(Str){html.p + pos, start - pos}, text_entity))")
    return replace(source, "(Str){html.p + pos, n - pos}))", "(Str){html.p + pos, n - pos}, text_entity))")


def fused32(source):
    source = fused_text(source)
    start = source.index('static size_t lab_text_end(')
    end = source.index('\nstatic int space_at(', start)
    return source[:start] + r'''
#include <immintrin.h>
static size_t lab_text_end(const char *p, size_t n, int *entity) {
    size_t i = 0;
    const __m256i lt = _mm256_set1_epi8('<'), amp = _mm256_set1_epi8('&');
    for (; n - i >= 32; i += 32) {
        __m256i data = _mm256_loadu_si256((const __m256i *)(p + i));
        unsigned ends = (unsigned)_mm256_movemask_epi8(_mm256_cmpeq_epi8(data, lt));
        unsigned amps = (unsigned)_mm256_movemask_epi8(_mm256_cmpeq_epi8(data, amp));
        if (ends) {
            unsigned bit = ds_first_bit(ends);
            *entity |= (amps & ((1u << bit) - 1)) != 0;
            return i + bit;
        }
        *entity |= amps != 0;
    }
    for (; i < n && p[i] != '<'; i++) *entity |= p[i] == '&';
    return i;
}
''' + source[end:]


def fused64(source):
    source = fused_text(source)
    start = source.index("    for (; n - i >= 16; i += 16)", source.index('static size_t lab_text_end('))
    code = '''    for (; n - i >= 64; i += 64) {
        uint64_t ends = 0, amps = 0;
'''
    for j in range(4):
        code += f'''        {{
            __m128i x = _mm_loadu_si128((const __m128i *)(p + i + {j * 16}));
            ends |= (uint64_t)(unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(x, lt)) << {j * 16};
            amps |= (uint64_t)(unsigned)_mm_movemask_epi8(_mm_cmpeq_epi8(x, amp)) << {j * 16};
        }}
'''
    code += '''        if (ends) {
            unsigned long bit;
            _BitScanForward64(&bit, ends);
            *entity |= (amps & (((uint64_t)1 << bit) - 1)) != 0;
            return i + bit;
        }
        *entity |= amps != 0;
    }
'''
    return source[:start] + code + source[start:]


def profile(source):
    source = helper(source, '''
static uint64_t lab_counts[8];
__declspec(dllexport) uint64_t *lab_metrics(void) { return lab_counts; }
''')
    source = replace(source, '        name_start = j;', '        name_start = j;\n        lab_counts[0]++;')
    source = replace(source, '                tag = cached->tag;', '                lab_counts[1]++;\n                lab_counts[2] += cached->raw.n;\n                tag = cached->tag;')
    source = replace(source, '        name_end = i;', '        lab_counts[3] += i - start;\n        name_end = i;')
    source = replace(source, '                value = (Str){html.p + start, i - start};',
                     '                lab_counts[4] += i - start;\n                lab_counts[5] += index < 0 ? i - start : 0;\n                value = (Str){html.p + start, i - start};')
    source = replace(source, '    if (d->flow) {', '    lab_counts[6] += text.n;\n    if (d->flow) {')
    source = replace(source, '    return sink(ctx, TEXT, ds_unescape', '    lab_counts[7] += text.n;\n    return sink(ctx, TEXT, ds_unescape')
    return source


def classes(source):
    values = []
    for c in range(256):
        space = c == 32 or 9 <= c <= 13 or 28 <= c <= 31
        name = space or c >= 128 or c in b'=/>"\'' or c == 0
        unquoted = space or c >= 128 or c in b'>"\'&'
        tag = space or c >= 128 or c in b'/>'
        values.append(int(space) | (int(name) << 1) | (int(unquoted) << 2) | (int(tag) << 3))
    code = 'static const unsigned char lab_class[256] = {\n'
    code += ',\n'.join(','.join(map(str, values[i:i+16])) for i in range(0, 256, 16)) + '\n};\n'
    code += '''static size_t lab_class_scan(const char *p, size_t n, unsigned mask) {
    size_t i = 0;
    while (i < n && !(lab_class[(unsigned char)p[i]] & mask)) i++;
    return i;
}
'''
    source = helper(source, code)
    source = replace(source, "return c == ' ' || (c >= 9 && c <= 13) || (c >= 28 && c <= 31);",
                     "return lab_class[c] & 1;")
    source = replace(source, '''        start = i;
        while (i < html.n) {
            c = (unsigned char)html.p[i];''', '''        start = i;
        while (i < html.n) {
            i += lab_class_scan(html.p + i, html.n - i, 2);
            if (i == html.n) break;
            c = (unsigned char)html.p[i];''')
    source = replace(source, '''        while (j < n && html.p[j] != '/' && html.p[j] != '>' && !space_at(html, j, &k))
            j += k;''', '''        while (j < n) {
            j += lab_class_scan(html.p + j, n - j, 8);
            if (j == n || html.p[j] == '/' || html.p[j] == '>' || space_at(html, j, &k)) break;
            j += k;
        }''')
    return replace(source, '''                while (i < html.n && html.p[i] != '>' && !space_at(html, i, &k)) {
                    if (html.p[i] == '"' || html.p[i] == '\\'')''', '''                while (i < html.n) {
                    i += lab_class_scan(html.p + i, html.n - i, 4);
                    if (i == html.n || html.p[i] == '>' || space_at(html, i, &k)) break;
                    if (html.p[i] == '"' || html.p[i] == '\\'')''')


def template_equal(source, avx=False):
    code = r'''
static int lab_equal(const char *a, const char *b, size_t n) {
    if (n >= 16 && n <= 32) {
        __m128i first = _mm_cmpeq_epi8(_mm_loadu_si128((const __m128i *)a), _mm_loadu_si128((const __m128i *)b));
        __m128i last = _mm_cmpeq_epi8(_mm_loadu_si128((const __m128i *)(a + n - 16)), _mm_loadu_si128((const __m128i *)(b + n - 16)));
        return _mm_movemask_epi8(_mm_and_si128(first, last)) == 65535;
    }
    if (n > 32 && n <= 64) {
        __m128i x0 = _mm_cmpeq_epi8(_mm_loadu_si128((const __m128i *)a), _mm_loadu_si128((const __m128i *)b));
        __m128i x1 = _mm_cmpeq_epi8(_mm_loadu_si128((const __m128i *)(a + 16)), _mm_loadu_si128((const __m128i *)(b + 16)));
        __m128i x2 = _mm_cmpeq_epi8(_mm_loadu_si128((const __m128i *)(a + n - 32)), _mm_loadu_si128((const __m128i *)(b + n - 32)));
        __m128i x3 = _mm_cmpeq_epi8(_mm_loadu_si128((const __m128i *)(a + n - 16)), _mm_loadu_si128((const __m128i *)(b + n - 16)));
        return _mm_movemask_epi8(_mm_and_si128(_mm_and_si128(x0, x1), _mm_and_si128(x2, x3))) == 65535;
    }
    if (n >= 8 && n < 16) {
        uint64_t a0, b0, a1, b1;
        memcpy(&a0, a, 8); memcpy(&b0, b, 8);
        memcpy(&a1, a + n - 8, 8); memcpy(&b1, b + n - 8, 8);
        return ((a0 ^ b0) | (a1 ^ b1)) == 0;
    }
    return !memcmp(a, b, n);
}
'''
    if avx:
        start = code.index('    if (n > 32')
        end = code.index('    if (n >= 8', start)
        code = '#include <immintrin.h>\n' + code[:start] + r'''
    if (n > 32 && n <= 64) {
        __m256i first = _mm256_cmpeq_epi8(_mm256_loadu_si256((const __m256i *)a), _mm256_loadu_si256((const __m256i *)b));
        __m256i last = _mm256_cmpeq_epi8(_mm256_loadu_si256((const __m256i *)(a + n - 32)), _mm256_loadu_si256((const __m256i *)(b + n - 32)));
        return (unsigned)_mm256_movemask_epi8(_mm256_and_si256(first, last)) == 0xffffffffu;
    }
''' + code[end:]
    source = helper(source, code)
    return replace(source, '!memcmp(html.p + j, cached->raw.p, cached->raw.n)',
                   'lab_equal(html.p + j, cached->raw.p, cached->raw.n)')


AVX_HELPER = r'''
#include <immintrin.h>
static size_t lab_quote_or_amp(const char *p, size_t n, char quote) {
    size_t i = 0;
    __m256i q = _mm256_set1_epi8(quote), amp = _mm256_set1_epi8('&');
    for (; n - i >= 32; i += 32) {
        __m256i data = _mm256_loadu_si256((const __m256i *)(p + i));
        unsigned mask = (unsigned)_mm256_movemask_epi8(_mm256_or_si256(
            _mm256_cmpeq_epi8(data, q), _mm256_cmpeq_epi8(data, amp)));
        if (mask) return i + ds_first_bit(mask);
    }
    return i + ds_quote_or_amp(p + i, n - i, quote);
}
'''


def avx_quote(source):
    source = replace(source, "i += ds_quote_or_amp(html.p + i, html.n - i, quote);",
                     "i += lab_quote_or_amp(html.p + i, html.n - i, quote);")
    return helper(source, AVX_HELPER)


MASK_HELPER = r'''
/* Retained masks of raw byte candidates; HTML state still lives in the parser.
 * Non-ASCII/control candidates go back through the existing Unicode logic. */
typedef struct {
    const char *p;
    size_t n, base;
    uint64_t names, unquoted, dq, sq, amp;
} LabMarks;
static unsigned lab_first64(uint64_t mask) {
    unsigned long bit;
    _BitScanForward64(&bit, mask);
    return (unsigned)bit;
}
static void lab_load(LabMarks *m, size_t i) {
    size_t j, count;
    m->base = i / LAB_BLOCK * LAB_BLOCK;
    count = m->n - m->base;
    if (count > LAB_BLOCK) count = LAB_BLOCK;
    m->names = m->unquoted = m->dq = m->sq = m->amp = 0;
    for (j = 0; count - j >= 16; j += 16) {
        __m128i x = _mm_loadu_si128((const __m128i *)(m->p + m->base + j));
        __m128i low = _mm_cmpeq_epi8(_mm_subs_epu8(x, _mm_set1_epi8(32)), _mm_setzero_si128());
        __m128i dq = _mm_cmpeq_epi8(x, _mm_set1_epi8('"'));
        __m128i sq = _mm_cmpeq_epi8(x, _mm_set1_epi8(39));
        __m128i amp = _mm_cmpeq_epi8(x, _mm_set1_epi8('&'));
        __m128i term = _mm_or_si128(x, _mm_or_si128(low, _mm_or_si128(
            _mm_cmpeq_epi8(x, _mm_set1_epi8('>')), _mm_or_si128(dq, sq))));
        __m128i name = _mm_or_si128(term, _mm_or_si128(
            _mm_cmpeq_epi8(x, _mm_set1_epi8('=')), _mm_cmpeq_epi8(x, _mm_set1_epi8('/'))));
        m->names |= (uint64_t)(unsigned)_mm_movemask_epi8(name) << j;
        m->unquoted |= (uint64_t)(unsigned)_mm_movemask_epi8(_mm_or_si128(term, amp)) << j;
        m->dq |= (uint64_t)(unsigned)_mm_movemask_epi8(dq) << j;
        m->sq |= (uint64_t)(unsigned)_mm_movemask_epi8(sq) << j;
        m->amp |= (uint64_t)(unsigned)_mm_movemask_epi8(amp) << j;
    }
    for (; j < count; j++) {
        unsigned char c = (unsigned char)m->p[m->base + j];
        uint64_t bit = (uint64_t)1 << j;
        int term = c <= 32 || c >= 128 || c == '>' || c == '"' || c == 39;
        if (term || c == '=' || c == '/') m->names |= bit;
        if (term || c == '&') m->unquoted |= bit;
        if (c == '"') m->dq |= bit;
        if (c == 39) m->sq |= bit;
        if (c == '&') m->amp |= bit;
    }
}
static size_t lab_next(LabMarks *m, size_t i, int kind) {
    while (i < m->n) {
        uint64_t mask;
        if (m->base == SIZE_MAX || i < m->base || i - m->base >= LAB_BLOCK) lab_load(m, i);
        mask = (kind ? m->unquoted : m->names) & (~(uint64_t)0 << (i - m->base));
        if (mask) return m->base + lab_first64(mask);
        i = m->base + LAB_BLOCK;
    }
    return m->n;
}
static size_t lab_quote(LabMarks *m, size_t i, char quote, int *entity) {
    while (i < m->n) {
        uint64_t mask, amps;
        if (m->base == SIZE_MAX || i < m->base || i - m->base >= LAB_BLOCK) lab_load(m, i);
        mask = (quote == '"' ? m->dq : m->sq) & (~(uint64_t)0 << (i - m->base));
        amps = m->amp & (~(uint64_t)0 << (i - m->base));
        if (mask) {
            unsigned bit = lab_first64(mask);
            *entity |= (amps & (((uint64_t)1 << bit) - 1)) != 0;
            return m->base + bit;
        }
        *entity |= amps != 0;
        i = m->base + LAB_BLOCK;
    }
    return m->n;
}
'''


def masks(source, block=64):
    source = helper(source, f"#define LAB_BLOCK {block}\n" + MASK_HELPER)
    source = replace(source, "    unsigned decode = 0;", "    unsigned decode = 0;\n    LabMarks marks = {html.p, html.n, SIZE_MAX, 0, 0, 0, 0, 0};")
    source = replace(source, '''        start = i;
        while (i < html.n) {
            c = (unsigned char)html.p[i];''', '''        start = i;
        while (i < html.n) {
            i = lab_next(&marks, i, 0);
            if (i == html.n) break;
            c = (unsigned char)html.p[i];''')
    start = source.index("                const char *close;", source.index("static int start_attrs"))
    end = source.index("                value = (Str){html.p + start, i - start};", start)
    source = source[:start] + '''                char quote = html.p[i++];
                start = i;
                i = lab_quote(&marks, i, quote, &has_entity);
                if (i == html.n) return 0;
''' + source[end:]
    source = replace(source, '''                while (i < html.n && html.p[i] != '>' && !space_at(html, i, &k)) {
                    if (html.p[i] == '"' || html.p[i] == '\\'')''', '''                while (i < html.n) {
                    i = lab_next(&marks, i, 1);
                    if (i == html.n || html.p[i] == '>' || space_at(html, i, &k)) break;
                    if (html.p[i] == '"' || html.p[i] == '\\'')''')
    return source


def variants(source):
    return {
        "baseline": (source, []),
        "bulk_skip": (bulk_skip(source), []),
        "fused_text": (fused_text(source), []),
        "avx_quote": (avx_quote(source), ["/arch:AVX2"]),
        "masks16": (masks(source, 16), []),
        "masks64": (masks(source, 64), []),
        "fused_bulk": (bulk_skip(fused_text(source)), []),
        "text32": (fused32(source), ["/arch:AVX2"]),
        "text64": (fused64(source), []),
        "avx_codegen": (source, ["/arch:AVX2"]),
        "text32_bulk": (bulk_skip(fused32(source)), ["/arch:AVX2"]),
        "profile": (profile(source), []),
        "classes": (classes(source), []),
        "classes_fused": (classes(bulk_skip(fused_text(source))), []),
        "cache256": (replace(source, "TEMPLATE_SLOTS = 1024", "TEMPLATE_SLOTS = 256"), []),
        "cache4096": (replace(source, "TEMPLATE_SLOTS = 1024", "TEMPLATE_SLOTS = 4096"), []),
        "cache16384": (replace(source, "TEMPLATE_SLOTS = 1024", "TEMPLATE_SLOTS = 16384"), []),
        "equal_sse": (template_equal(source), []),
        "equal_avx": (template_equal(source, True), ["/arch:AVX2"]),
        "equal_fused": (template_equal(fused_text(source)), []),
    }
