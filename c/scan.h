#ifndef DOC2STRUCT_SCAN_H
#define DOC2STRUCT_SCAN_H

#include <stddef.h>
#include <string.h>

/* The normalizer's blank set is deliberately narrower than Unicode whitespace.
 * Testing emptiness needs only a forward scan, not a stripped output slice. */
static inline int ds_blank_text(const char *p, size_t n) {
    size_t i = 0;
    while (i < n) {
        unsigned char c = (unsigned char)p[i];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
            i++;
            continue;
        }
        if (c < 128)
            return 0;
        if (n - i >= 2 && c == 0xc2 && (unsigned char)p[i + 1] == 0xa0) {
            i += 2;
            continue;
        }
        if (n - i >= 3 && c == 0xe2 && (unsigned char)p[i + 1] == 0x80 &&
            (unsigned char)p[i + 2] == 0x8b) {
            i += 3;
            continue;
        }
        return 0;
    }
    return 1;
}

/* SSE2 is part of the x86-64 baseline. Other targets keep the scalar path. */
#if !defined(DS_SCALAR_SCAN) && (defined(_M_X64) || defined(__SSE2__))
#include <emmintrin.h>
#if defined(_MSC_VER)
#include <intrin.h>
#endif
#define DS_SSE2 1
static inline unsigned ds_first_bit(unsigned mask) {
#if defined(_MSC_VER)
    unsigned long bit;
    _BitScanForward(&bit, mask);
    return (unsigned)bit;
#else
    return (unsigned)__builtin_ctz(mask);
#endif
}
#endif

/* Never read beyond the supplied slice: callers need no padding or alignment. */
static inline size_t ds_nonascii(const char *p, size_t n) {
    size_t i = 0;
#ifdef DS_SSE2
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(p + i));
        unsigned mask = (unsigned)_mm_movemask_epi8(data);
        if (mask)
            return i + ds_first_bit(mask);
    }
#endif
    for (; i < n; i++)
        if ((unsigned char)p[i] >= 128)
            break;
    return i;
}

static inline size_t ds_upper_or_nonascii(const char *p, size_t n) {
    size_t i = 0;
#ifdef DS_SSE2
    const __m128i before_a = _mm_set1_epi8('A' - 1), after_z = _mm_set1_epi8('Z' + 1);
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(p + i));
        __m128i upper =
            _mm_and_si128(_mm_cmpgt_epi8(data, before_a), _mm_cmpgt_epi8(after_z, data));
        unsigned mask = (unsigned)_mm_movemask_epi8(_mm_or_si128(data, upper));
        if (mask)
            return i + ds_first_bit(mask);
    }
#endif
    for (; i < n; i++) {
        unsigned char c = (unsigned char)p[i];
        if ((c >= 'A' && c <= 'Z') || c >= 128)
            break;
    }
    return i;
}

/* Find the next quote or tag terminator, skipping ordinary attribute bytes. */
static inline size_t ds_tag_mark(const char *p, size_t n) {
    size_t i = 0;
#ifdef DS_SSE2
    const __m128i gt = _mm_set1_epi8('>'), dq = _mm_set1_epi8('"'), sq = _mm_set1_epi8('\'');
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(p + i));
        __m128i matches =
            _mm_or_si128(_mm_cmpeq_epi8(data, gt),
                         _mm_or_si128(_mm_cmpeq_epi8(data, dq), _mm_cmpeq_epi8(data, sq)));
        unsigned mask = (unsigned)_mm_movemask_epi8(matches);
        if (mask)
            return i + ds_first_bit(mask);
    }
#endif
    for (; i < n; i++)
        if (p[i] == '>' || p[i] == '"' || p[i] == '\'')
            break;
    return i;
}

static inline size_t ds_quote_or_amp(const char *p, size_t n, char quote) {
    size_t i = 0;
#ifdef DS_SSE2
    const __m128i q = _mm_set1_epi8(quote), amp = _mm_set1_epi8('&');
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(p + i));
        unsigned mask = (unsigned)_mm_movemask_epi8(
            _mm_or_si128(_mm_cmpeq_epi8(data, q), _mm_cmpeq_epi8(data, amp)));
        if (mask)
            return i + ds_first_bit(mask);
    }
#endif
    for (; i < n; i++)
        if (p[i] == quote || p[i] == '&')
            break;
    return i;
}

static inline int ds_ascii_lower(char *out, const char *in, size_t n) {
    size_t i = 0;
    int changed = 0;
#ifdef DS_SSE2
    const __m128i before_a = _mm_set1_epi8('A' - 1), after_z = _mm_set1_epi8('Z' + 1);
    const __m128i delta = _mm_set1_epi8(32);
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(in + i));
        __m128i upper =
            _mm_and_si128(_mm_cmpgt_epi8(data, before_a), _mm_cmpgt_epi8(after_z, data));
        changed |= _mm_movemask_epi8(upper);
        _mm_storeu_si128((__m128i *)(out + i), _mm_or_si128(data, _mm_and_si128(upper, delta)));
    }
#endif
    for (; i < n; i++) {
        unsigned char c = (unsigned char)in[i];
        if (c >= 'A' && c <= 'Z') {
            out[i] = (char)(c + 32);
            changed = 1;
        } else
            out[i] = (char)c;
    }
    return changed != 0;
}

static inline size_t ds_json_escape(const char *p, size_t n) {
    size_t i = 0;
#ifdef DS_SSE2
    const __m128i quote = _mm_set1_epi8('"'), slash = _mm_set1_epi8('\\');
    const __m128i control_end = _mm_set1_epi8(31), zero = _mm_setzero_si128();
    for (; n - i >= 16; i += 16) {
        __m128i data = _mm_loadu_si128((const __m128i *)(p + i));
        __m128i control = _mm_cmpeq_epi8(_mm_subs_epu8(data, control_end), zero);
        unsigned mask = (unsigned)_mm_movemask_epi8(_mm_or_si128(control,
            _mm_or_si128(_mm_cmpeq_epi8(data, quote), _mm_cmpeq_epi8(data, slash))));
        if (mask) return i + ds_first_bit(mask);
    }
#endif
    for (; i < n; i++)
        if ((unsigned char)p[i] < 32 || p[i] == '"' || p[i] == '\\') break;
    return i;
}

#endif
