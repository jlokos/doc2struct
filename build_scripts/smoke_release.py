"""Exercise installed release artifacts, independently of the source tree.

Used by wheel and SDK release jobs, not by package installation.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def basic_pdf():
    """A complete one-page PDF with a known embedded text string."""
    stream = b'BT /F1 12 Tf 72 720 Td (Release smoke marker.) Tj ET\n'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'endstream',
    ]
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(b'%d 0 obj\n' % index + obj + b'\nendobj\n')
    xref = len(pdf)
    pdf.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.extend(b'%010d 00000 n \n' % offset)
    pdf.extend(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % xref)
    return bytes(pdf)


def check_rows(rows):
    if 'Release smoke marker.' not in json.dumps(rows):
        raise AssertionError('Parsed output is missing the known input text: ' + repr(rows))


def python_smoke():
    import doc2struct as d
    from validate_pdfium import validate

    package = Path(d.__file__).resolve().parent
    if package == Path(__file__).resolve().parents[1] / 'python/src/doc2struct':
        raise AssertionError('Smoke check must import an installed wheel')
    suffix = '.dll' if sys.platform == 'win32' else '.dylib' if sys.platform == 'darwin' else '.so'
    validate(package / '_pdfium' / ('doc2struct_pdfium' + suffix))
    for rows in (
        d.parse_html(b'<h1>Item 1A. Risk Factors</h1><p>Release smoke marker.</p>', rules='SEC:10-K'),
        d.parse_text(b'Release smoke marker.'),
        d.parse_partialsgml(b'<TEXT>\nRelease smoke marker.\n</TEXT>'),
        d.parse_pdf(basic_pdf()),
    ):
        check_rows(rows)
    title = next(row for row in d.parse_html(b'<h1>Item 1A. Risk Factors</h1>', rules='SEC:10-K') if row['text'] == 'Item 1A. Risk Factors')
    if title['class'] != 'item' or title['standardized_title'] != 'item1a':
        raise AssertionError('Embedded SEC preset columns did not survive packaging')
    print('Installed Python package passed HTML, text, partial SGML, PDF, and SEC preset checks; version ' + importlib.metadata.version('doc2struct'))


def native_smoke(prefix, *, sdk=False):
    prefix = prefix.resolve()
    executable = prefix / 'bin' / ('doc2struct_parse.exe' if os.name == 'nt' else 'doc2struct_parse')
    # No environment override: the CLI must find the runtime in its own bundle.
    env = {key: value for key, value in os.environ.items() if key != 'DOC2STRUCT_PDFIUM_LIBRARY'}
    with tempfile.TemporaryDirectory(prefix='doc2struct-release-') as temp:
        work = Path(temp)
        for name, content in (
            ('input.html', b'<p>Release smoke marker.</p>'),
            ('input.pdf', basic_pdf()),
        ):
            source = work / name
            source.write_bytes(content)
            result = subprocess.check_output([str(executable), str(source)], cwd=work, env=env)
            check_rows(json.loads(result))
        if sdk:
            # Compile/link a downstream CMake consumer against only the installed SDK.
            (work / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.18)
project(consumer LANGUAGES C)
find_package(doc2struct CONFIG REQUIRED)
add_executable(consumer main.c)
target_link_libraries(consumer PRIVATE doc2struct::doc2struct)
enable_testing()
add_test(NAME sdk_consumer COMMAND consumer "${doc2struct_PDFIUM_LIBRARY}")
''', encoding='utf-8')
            (work / 'main.c').write_text('''#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    doc2struct_error error = {{0}};
    const char *text = "Release smoke marker.";
    if (argc != 2 || !doc2struct_pdfium_init(argv[1], &error)) return 1;
    doc2struct_parser *p = doc2struct_parser_new(0, &error);
    doc2struct_rules *r = doc2struct_rules_preset(NULL, &error);
    if (!p || !r) return 2;
    doc2struct_document *d = doc2struct_parse_text(p, (doc2struct_string){text, strlen(text)}, r, &error);
    size_t count = 0;
    const doc2struct_row *rows = d ? doc2struct_document_rows(d, &count) : NULL;
    int ok = 0;
    for (size_t i = 0; rows && i < count; ++i)
        if (rows[i].text.n == strlen(text) && !memcmp(rows[i].text.p, text, strlen(text))) ok = 1;
    doc2struct_document_free(d); doc2struct_rules_free(r); doc2struct_parser_free(p);
    return ok ? 0 : 3;
}
''', encoding='utf-8')
            subprocess.run(['cmake', '-S', str(work), '-B', str(work / 'build'), '-DCMAKE_PREFIX_PATH=' + str(prefix)], check=True)
            subprocess.run(['cmake', '--build', str(work / 'build'), '--config', 'Release', '--parallel', '2'], check=True)
            subprocess.run(['ctest', '--test-dir', str(work / 'build'), '-C', 'Release', '--output-on-failure'], check=True)
    print('Installed ' + ('SDK and CLI' if sdk else 'CLI') + ' passed release checks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', action='store_true')
    parser.add_argument('--prefix', type=Path, help='Installed or unpacked native bundle')
    parser.add_argument('--sdk', action='store_true', help='Also compile an SDK consumer')
    args = parser.parse_args()
    if not args.python and not args.prefix:
        parser.error('Select --python and/or --prefix')
    if args.python:
        python_smoke()
    if args.prefix:
        native_smoke(args.prefix, sdk=args.sdk)
