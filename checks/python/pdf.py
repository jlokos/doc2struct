"""Native PDF checks. Run: python checks/python/pdf.py [--cli path/to/executable]."""
import argparse
import ctypes
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile

import doc2struct as ds


def fixture(pages, *, rotate=0, crop=None):
    """Small deterministic PDFs without another PDF creation dependency."""
    objects = [b'', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>']
    cmap = (b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap '
            b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def '
            b'/CMapName /CheckUnicode def /CMapType 2 def '
            b'1 begincodespacerange <00> <FF> endcodespacerange '
            b'2 beginbfchar <41> <03A9> <42> <D83DDE00> endbfchar '
            b'endcmap CMapName currentdict /CMap defineresource pop end end')
    objects.extend([b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 7 0 R >>',
                    f'<< /Length {len(cmap)} >>\nstream\n'.encode() + cmap + b'\nendstream'])
    kids = []
    for content in pages:
        if isinstance(content, str):
            content = content.encode('cp1252')
        page_id, stream_id = len(objects) + 1, len(objects) + 2
        kids.append(f'{page_id} 0 R')
        crop_box = f'/CropBox [{crop}]' if crop else ''
        objects.append((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
                        f'{crop_box} /Rotate {rotate} /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R >> >> '
                        f'/Contents {stream_id} 0 R >>').encode())
        objects.append(f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'\nendstream')
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = f'<< /Type /Pages /Count {len(kids)} /Kids [{" ".join(kids)}] >>'.encode()
    data = bytearray(b'%PDF-1.7\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    start = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        data.extend(f'{offset:010} 00000 n \n'.encode())
    data.extend(f'trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(data)


def text(value, x=50, y=700, font='F1', size=12):
    value = value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return f'BT /{font} {size} Tf {x} {y} Td ({value}) Tj ET\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cli', type=Path)
    args = ap.parse_args()
    content = text('Item 1. Business', font='F2', size=16) + text('Café & growth.', y=675)
    content += text('Final line survives.', y=650)
    sample = fixture([content, '', text('Next page.')])
    instructions = ds.convert_pdf_to_instructions(sample)
    assert 'Café & growth.' in ''.join(r['text'] for r in instructions)
    assert 'Final line survives.' in ''.join(r['text'] for r in instructions)
    assert len({r['block'] for r in instructions}) == 4
    for rules in [None, 'SEC:10-K', {'headers': []}]:
        expected = ds.convert_instructions_to_standardized_text(instructions, rules)
        assert ds.parse_pdf(sample, rules) == expected
        with ds.Parser() as parser:
            assert parser.parse_pdf(bytearray(sample), rules) == expected
            assert parser.cached_bytes <= parser.cache_size
        try:
            parser.parse_pdf(sample)
        except ValueError:
            pass
        else:
            raise AssertionError('closed parser accepted PDF')
    assert ds.parse_pdf(fixture([''])) == ds.convert_instructions_to_standardized_text([])
    assert any(r['flags'] & 1 for r in instructions)
    italic = ds.convert_pdf_to_instructions(fixture([text('Italic', font='F3')]))
    assert italic[0]['flags'] & 2
    assert abs(italic[0]['font_size'] - 16) < .01
    mapped = ds.convert_pdf_to_instructions(fixture([text('AB', font='F4')]))
    assert ''.join(r['text'] for r in mapped).replace(' ', '') == '\u03a9\U0001f600', mapped
    # Exercise the default bridge and its per-page fallback, without depending
    # on PDFium's old line-end dehyphenation policy.
    kerned=ds.convert_pdf_to_instructions(fixture(['BT /F1 12 Tf 50 700 Td [(one) -250 (two)] TJ ET']))
    assert ''.join(r['text'] for r in kerned)=='one two'
    hyphenated=ds.convert_pdf_to_instructions(fixture([text('forward-')+text('looking',y=684)]))
    assert hyphenated[0]['text']=='forward-'
    replacement=ds.convert_pdf_to_instructions(fixture(['/Span << /ActualText (Replacement) >> BDC '+text('Original')+'EMC']))
    assert ''.join(r['text'] for r in replacement)=='Replacement'
    library=next((Path(ds.__file__).parent/'_pdfium').glob('doc2struct_pdfium.*'))
    engine=ctypes.CDLL(str(library))
    assert engine.DS_PDF_BridgeVersion()==1
    counters=(ctypes.c_uint64*4)()
    engine.DS_PDF_GetStats(counters)
    assert counters[1]>0 and counters[2]>0, 'bridge and fallback must both run'
    scaled = ds.convert_pdf_to_instructions(fixture(['q 2 0 0 2 0 0 cm ' + text('Scaled', y=300) + 'Q']))
    assert abs(scaled[0]['font_size'] - 32) < .01
    # Differently styled adjacent text objects must not invent a word boundary.
    split = fixture([text('Hello', x=50) + text('world', x=77.336, font='F2')])
    assert ''.join(r['text'] for r in ds.convert_pdf_to_instructions(split)) == 'Helloworld'
    for rotation in (0, 90, 180, 270):
        rotated = fixture([text('Rotation survives.')], rotate=rotation, crop='20 30 600 780')
        assert ''.join(r['text'] for r in ds.convert_pdf_to_instructions(rotated)) == 'Rotation survives.'
    table = ''.join(text(a, 50, y) + text(b, 300, y) for a, b, y in
                    [('Year', 'Sales', 700), ('2024', '123', 680), ('2025', '456', 660)])
    table_pdf = fixture([table])
    table_runs = ds.convert_pdf_to_instructions(table_pdf)
    assert len({r['row'] for r in table_runs}) == 3, table_runs
    assert ds.parse_pdf(table_pdf) == ds.convert_instructions_to_standardized_text(table_runs)
    columns = ''.join(text(a, 50, y) + text(b, 330, y) for a, b, y in
                      [('Left first', 'Right first', 700), ('Left second', 'Right second', 684),
                       ('Left third', 'Right third', 668)])
    column_runs = ds.convert_pdf_to_instructions(fixture([columns]))
    assert [r['text'] for r in column_runs] == ['Left first', 'Left second', 'Left third',
                                              'Right first', 'Right second', 'Right third']
    for invalid in (b'', b'not a PDF', b'%PDF-1.7\ninvalid'):
        try:
            ds.parse_pdf(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid PDF accepted')
    try:
        ds.parse_pdf('a filename.pdf')
    except TypeError:
        pass
    else:
        raise AssertionError('string accepted as PDF bytes')
    expected = ds.parse_pdf(sample)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(result == expected for result in pool.map(ds.parse_pdf, [sample] * 32))
    # Loading/closing the other wrapper must not destroy our private engine.
    try:
        import pypdfium2
    except ImportError:
        pass
    else:
        with pypdfium2.PdfDocument(sample) as other:
            assert len(other) == 3
        assert ds.parse_pdf(sample) == expected
    if args.cli:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'sample.pdf'
            path.write_bytes(sample)
            env = dict(os.environ)
            env['DOC2STRUCT_PDFIUM_LIBRARY'] = str(next((Path(ds.__file__).parent / '_pdfium').glob('doc2struct_pdfium.*')))
            native = json.loads(subprocess.check_output([str(args.cli), str(path)], env=env))
            assert native == expected, (native, expected)
    print('PDF checks passed: staged/fused parity, layout, rotation, Unicode, errors, threads.'
          + (' C CLI parity passed.' if args.cli else ''))


if __name__ == '__main__':
    main()
