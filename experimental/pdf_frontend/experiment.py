"""Isolated PDF frontend builds and corpus measurements; never installs a build.

From the repository root (Windows):
  python experimental/pdf_frontend/build_pdfium.py --fetch --optimized
  python experimental/pdf_frontend/experiment.py build baseline
  python experimental/pdf_frontend/experiment.py build bridge
  python experimental/pdf_frontend/experiment.py build stream
  python experimental/pdf_frontend/benchmark.py --optimized

Use measure without --timing-only to save standardized rows and instructions;
compare checks those saved outputs. bridge/stream require the custom DLL.
"""
import argparse
import ast
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import statistics
import sys
import tarfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BUILD = ROOT / 'build/pdf-fast'


def write_changed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def build(variant):
    from setuptools import Distribution, Extension
    source = (ROOT / 'c/src/pdf.c').read_text()
    layout = (ROOT / 'c/src/pdf_layout.c').read_text()
    if variant in ('axis', 'compact', 'styles'):
        begin = source.index('        point(m,l,t,xx,yy);')
        end = source.index('        point(m,x,y,&g->x,&g->y);', begin)
        original = source[begin:end]
        source = source[:begin] + '''        if (m.b == 0 && m.c == 0) {
            double x0=m.a*l+m.e, x1=m.a*r+m.e;
            double y0=m.d*b+m.f, y1=m.d*t+m.f;
            g->left=x0<x1?x0:x1; g->right=x0>x1?x0:x1;
            g->top=y0<y1?y0:y1; g->bottom=y0>y1?y0:y1;
        } else {
''' + original + '        }\n' + source[end:]
    if variant in ('bridge', 'stream'):
        source = source.replace('#include "fpdf_text.h"', '#include "fpdf_text.h"\n#include "bridge.h"\n_Static_assert(sizeof(DS_PDF_GLYPH)==sizeof(doc2struct_pdf_glyph),"glyph ABI mismatch");')
        source = source.replace('static char *engine_path;', '''static char *engine_path;
static int (FPDF_CALLCONV *bridge_extract)(FPDF_PAGE, DS_PDF_SINK, void *);
static int bridge_sink(void *context, const DS_PDF_GLYPH *glyphs, size_t count) {
    doc2struct_pdf_page *page=context;
    page->glyphs=(const doc2struct_pdf_glyph *)glyphs;
    page->count=count;
    return 1;
}
''')
        source = source.replace('    p_FPDF_InitLibrary();', '''    bridge_extract = (int (FPDF_CALLCONV *)(FPDF_PAGE, DS_PDF_SINK, void *))
        GetProcAddress(library, "DS_PDF_ExtractPage");
    if (!bridge_extract) { fail(error,"custom PDFium bridge is required"); goto done; }
    p_FPDF_InitLibrary();''')
        source = source.replace('        if (page) text =', '''        if (page) {
            int fast;
            view.width=p_FPDF_GetPageWidthF(page); view.height=p_FPDF_GetPageHeightF(page);
            fast=bridge_extract(page,bridge_sink,&view);
            if (fast < 0) { fail(error,"PDF bridge extraction failed"); goto done; }
            if (fast > 0) {
                /* View is engine-owned until the next bridge call. The sink must
                 * complete under the lock for this experimental interface. */
                ok=sink(context,&view);
                p_FPDF_ClosePage(page); page=NULL;
                if (!ok) { fail(error,"PDF layout failed"); goto done; }
                continue;
            }
        }
        if (page) text =''')
        if variant == 'stream':
            source = source.replace('bridge_extract)(FPDF_PAGE, DS_PDF_SINK, void *)',
                'bridge_extract)(FPDF_DOCUMENT, int, DS_PDF_SINK, void *, double *, double *)')
            source = source.replace('(int (FPDF_CALLCONV *)(FPDF_PAGE, DS_PDF_SINK, void *))',
                '(int (FPDF_CALLCONV *)(FPDF_DOCUMENT, int, DS_PDF_SINK, void *, double *, double *))')
            source = source.replace('"DS_PDF_ExtractPage"', '"DS_PDF_StreamPage"')
            begin = source.index('        page = p_FPDF_LoadPage(document, i);')
            end = source.index('        if (page) text =', begin)
            source = source[:begin] + '''        {
            int fast=bridge_extract(document,i,bridge_sink,&view,&view.width,&view.height);
            if (fast < 0) { fail(error,"PDF stream extraction failed"); goto done; }
            if (fast > 0) {
                ok=sink(context,&view);
                if (!ok) { fail(error,"PDF layout failed"); goto done; }
                continue;
            }
        }
        page = p_FPDF_LoadPage(document, i);
''' + source[end:]
    stage = BUILD / variant
    includes=['c/include', 'c/src', 'c/vendor/pcre2', 'c/vendor/pdfium', str(HERE)]
    depends=[]
    if variant in ('compact','styles'):
        header=(ROOT/'c/include/doc2struct/doc2struct.h').read_text()
        if variant=='compact':
            header=header.replace('double left, top, right, bottom, x, y, font, dx, dy;',
                              'float left, top, right, bottom, x, y, dx, dy;\n    double font;')
        else:
            header=header.replace('typedef struct {\n    uint32_t unicode;',
                'typedef struct { double font, dx, dy; unsigned flags; } ds_pdf_style;\n'
                'typedef struct {\n    uint32_t unicode;')
            header=header.replace('    unsigned flags; /* bold=1, italic=2 */\n','')
            header=header.replace('double left, top, right, bottom, x, y, font, dx, dy;',
                'double left, top, right, bottom, x, y;\n    const ds_pdf_style *style;')
            source=source.replace('doc2struct_pdf_glyph *glyphs) {',
                'doc2struct_pdf_glyph *glyphs, Arena *styles) {\n    ds_pdf_style *style=NULL;')
            source=source.replace('            previous = object;', '''            if (!style || style->font!=font || style->dx!=dx || style->dy!=dy || style->flags!=flags) {
                style=ds_alloc_uninit(styles,sizeof(*style));
                if (!style) return 0;
                *style=(ds_pdf_style){font,dx,dy,flags};
            }
            previous = object;''')
            source=source.replace('g->unicode=cp; g->flags=flags; g->font=font; g->dx=dx; g->dy=dy;',
                                  'g->unicode=cp; g->style=style;')
            source=source.replace('    size_t capacity = 0;',
                '    ArenaPool style_pool={0};\n    Arena styles={0};\n    size_t capacity = 0;')
            source=source.replace('    LOCK();\n    if (!engine_path)',
                '    styles.pool=&style_pool; style_pool.limit=DS_DEFAULT_CACHE_SIZE;\n    LOCK();\n    if (!engine_path)')
            source=source.replace('extract_page(page, text, &view, glyphs)',
                                  'extract_page(page, text, &view, glyphs, &styles)')
            source=source.replace('        ok = sink(context, &view);',
                                  '        ok = sink(context, &view);\n        ds_arena_free(&styles);')
            source=source.replace('    free(glyphs);',
                '    free(glyphs);\n    ds_arena_free(&styles); ds_pool_clear(&style_pool);')
            layout=re.sub(r'\b([ab])->(font|dx|dy|flags)\b',r'\1->style->\2',layout)
            layout=re.sub(r'\bg(\[(?:[^\[\]]|\[[^\[\]]*\])+\])\.(font|dx|dy|flags)\b',
                          r'g\1.style->\2',layout)
        target=stage/'include/doc2struct/doc2struct.h'
        write_changed(target,header.encode())
        includes.insert(0,str(stage/'include'))
        depends.append(str(target))
        if variant=='compact':
            source=source.replace('        point(m,x,y,&g->x,&g->y);',
                              '        { double ox,oy; point(m,x,y,&ox,&oy); g->x=(float)ox; g->y=(float)oy; }')
    write_changed(stage / 'pdf.c', source.encode())
    write_changed(stage / 'pdf_layout.c', layout.encode())
    # Take the PCRE2 source list from the real build, rather than globbing tests.
    tree = ast.parse((ROOT / 'python/setup.py').read_text())
    pcre = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'pcre_sources' for t in n.targets))
    core = ['api', 'config', 'config_json', 'memory', 'text', 'tokenizer', 'normalizer',
            'rules', 'parser', 'standardized_text', 'lists', 'flow', 'json', 'tables']
    sources = ['python/native/module.c'] + [f'c/src/{name}.c' for name in core]
    sources += [str((stage / f'{name}.c').relative_to(ROOT)) for name in ('pdf', 'pdf_layout')]
    sources += [f'c/vendor/pcre2/pcre2_{name}.c' for name in pcre]
    macros = [(n, '1') for n in ('HAVE_CONFIG_H', 'PCRE2_STATIC', 'SUPPORT_PCRE2_8',
              'SUPPORT_UNICODE', 'HAVE_MEMMOVE', 'HAVE_STDLIB_H', 'HAVE_STDINT_H',
              'HAVE_STRING_H', 'HAVE_INTTYPES_H', 'HAVE_LIMITS_H', '_CRT_SECURE_NO_WARNINGS')]
    macros.append(('PCRE2_CODE_UNIT_WIDTH', '8'))
    extension = Extension('_native', sources=sources, define_macros=macros,
                          include_dirs=includes, depends=depends,
                          extra_compile_args=['/O2', '/utf-8', '/std:c11'])
    os.chdir(ROOT)
    dist = Distribution({'name': 'pdf-frontend-experiment', 'ext_modules': [extension]})
    command = dist.get_command_obj('build_ext')
    command.build_lib = str(stage)
    command.build_temp = str(BUILD / 'obj')
    command.ensure_finalized()
    command.run()


def load(variant, engine):
    binary = next((BUILD / variant).glob('_native*.pyd'))
    spec = importlib.util.spec_from_file_location('_native', binary)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    private = BUILD / variant / ('engine-' + hashlib.sha256(engine.read_bytes()).hexdigest()[:12] + '.dll')
    if not private.exists():
        shutil.copy2(engine, private)
    native.pdfium_init(str(private))
    native._experiment_engine=private
    return native


def documents():
    with tarfile.open(ROOT / 'data/filings/10k_pdf_sample/batch_000001.tar', 'r|*') as archive:
        for member in archive:
            if member.isfile() and member.name.lower().endswith('.pdf'):
                with archive.extractfile(member) as stream:
                    yield member.name, stream.read()


def measure(args):
    native = load(args.variant, args.engine.resolve())
    inputs = list(documents())
    if args.limit:
        inputs = inputs[:args.limit]
    rules = native.prepare_preset('SEC:10-K')
    times = []
    for repeat in range(args.passes):
        elapsed = 0.0
        for name, data in inputs:
            start = perf_counter()
            rows = native.parse_pdf(data, rules, True, None)
            elapsed += perf_counter() - start
        times.append(elapsed)
        print(f'{args.variant}: pass {repeat+1}: {elapsed:.3f}s', flush=True)
    destination=BUILD/(args.label or args.variant)
    destination.mkdir(parents=True,exist_ok=True)
    output = destination / 'output.json.gz'
    hashes = []
    if not args.timing_only:
        save_outputs(native, inputs, rules, output, hashes)
    result = dict(variant=args.variant, files=len(inputs), bytes=sum(len(b) for _, b in inputs),
                  seconds=times, median_seconds=statistics.median(times), row_hashes=hashes,
                  engine_sha256=hashlib.sha256(args.engine.read_bytes()).hexdigest())
    if args.variant in ('bridge', 'stream'):
        import ctypes
        engine=ctypes.WinDLL(str(native._experiment_engine))
        counts=(ctypes.c_uint64*4)()
        getattr(engine, 'DS_PDF_GetStreamStats' if args.variant=='stream' else 'DS_PDF_GetStats')(counts)
        result['bridge_stats']=dict(zip(['calls','fast_pages','fallback_pages','glyphs'],counts))
    (destination / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='row_hashes'}, indent=2))


def save_outputs(native, inputs, rules, output, hashes):
    with gzip.open(output, 'wt', encoding='utf-8') as saved:
        for name, data in inputs:
            rows = native.parse_pdf(data, rules, True, None)
            instructions = native.pdf_instructions(data, None)
            record = {'name': name, 'rows': rows, 'instructions': instructions}
            saved.write(json.dumps(record, ensure_ascii=False) + '\n')
            hashes.append(hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())


def compare(first, second):
    mismatches = []
    with gzip.open(BUILD/first/'output.json.gz', 'rt', encoding='utf-8') as a, \
         gzip.open(BUILD/second/'output.json.gz', 'rt', encoding='utf-8') as b:
        for left, right in zip(a,b, strict=True):
            x,y = json.loads(left),json.loads(right)
            assert x['name']==y['name']
            if x['rows'] != y['rows']:
                xt=''.join(r['text'] for r in x['instructions'])
                yt=''.join(r['text'] for r in y['instructions'])
                xn=''.join(xt.split()).replace('-','')
                yn=''.join(yt.split()).replace('-','')
                mismatches.append(dict(name=x['name'], baseline_rows=len(x['rows']),
                    candidate_rows=len(y['rows']), baseline_chars=len(xt), candidate_chars=len(yt),
                    text_equal=''.join(xt.split())==''.join(yt.split()),
                    text_equal_without_spaces_or_hyphens=xn==yn,
                    character_counts_equal_without_spaces_or_hyphens=Counter(xn)==Counter(yn)))
    report = dict(baseline=first,candidate=second,row_mismatches=len(mismatches),mismatches=mismatches)
    (BUILD/second/'comparison.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['build','measure','compare'])
    ap.add_argument('variant',choices=['baseline','axis','compact','styles','bridge','stream'])
    ap.add_argument('--engine',type=Path,default=ROOT/'python/src/doc2struct/_pdfium/doc2struct_pdfium.dll')
    ap.add_argument('--passes',type=int,default=3)
    ap.add_argument('--limit',type=int)
    ap.add_argument('--baseline',default='baseline')
    ap.add_argument('--label')
    ap.add_argument('--timing-only',action='store_true')
    args=ap.parse_args()
    if args.action=='build': build(args.variant)
    elif args.action=='measure': measure(args)
    else: compare(args.baseline,args.label or args.variant)
