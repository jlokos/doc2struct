#ifndef DS_EXPERIMENTAL_PDF_BRIDGE_H
#define DS_EXPERIMENTAL_PDF_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#include "fpdfview.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Version-local ABI: matches doc2struct_pdf_glyph. Borrowed until next call.
 * This is an experiment, not a stable PDFium API. The caller must serialize
 * all PDFium calls, including consumption of the borrowed records.
 * Unsupported-feature detection is incomplete: successful extraction does
 * not imply equivalence to CPDF_TextPage (overprints, hyphens, ordering). */
typedef struct {
    uint32_t unicode;
    unsigned flags;
    int space_before;
    double left, top, right, bottom, x, y, font, dx, dy;
} DS_PDF_GLYPH;
typedef int (*DS_PDF_SINK)(void *, const DS_PDF_GLYPH *, size_t);
/* 1: emitted; 0: unsupported, caller must use stock PDFium; -1: failed. */
FPDF_EXPORT int FPDF_CALLCONV DS_PDF_ExtractPage(FPDF_PAGE page, DS_PDF_SINK sink, void *context);
/* Counters: calls, fast pages, fallback pages, emitted glyphs. */
FPDF_EXPORT void FPDF_CALLCONV DS_PDF_GetStats(uint64_t *counters);
FPDF_EXPORT int FPDF_CALLCONV DS_PDF_StreamPage(FPDF_DOCUMENT document, int index,
    DS_PDF_SINK sink, void *context, double *width, double *height);
FPDF_EXPORT void FPDF_CALLCONV DS_PDF_GetStreamStats(uint64_t *counters);
#ifdef __cplusplus
}
#endif
#endif
