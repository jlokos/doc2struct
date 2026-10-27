"""Build one isolated heading-prediction variant; never install it.

The source snapshot and compiler output live under ignored artifacts/. The
existing installed extension is copied as a frozen baseline, not overwritten.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import sysconfig

from corpus import ROOT, OUT

PROSE = r'''
/* Experiment: long italic prose is weak evidence for a heading. Explicit
 * section rules and semantic heading elements retain their existing behavior. */
static int lab_italic_prose(Document *d, Line *line, int big) {
    Item *first = line->nitems ? line->items : NULL;
    Str text;
    size_t i, words = 0;
    int in_word = 0;
    if (!first || big || !(first->run.flags & ITALIC) ||
        (first->run.flags & (BOLD | CENTERED | UNDERLINE))) return 0;
    if (first->run.tag.n == 2 && first->run.tag.p[0] == 'h' &&
        first->run.tag.p[1] >= '1' && first->run.tag.p[1] <= '6') return 0;
    text = ds_strip(line_text(d, line->items, line->nitems), 1);
    for (i = 0; i < text.n; i++) {
        int space = text.p[i] == ' ' || text.p[i] == '\n' || text.p[i] == '\t';
        if (!space && !in_word) words++;
        in_word = !space;
    }
    if (words < 28 || text.n < 160) return 0;
    for (i = 1; i + 2 < text.n; i++)
        if ((text.p[i] == '.' || text.p[i] == '?' || text.p[i] == '!') &&
            text.p[i+1] == ' ' && text.p[i+2] >= 'A' && text.p[i+2] <= 'Z') return 1;
    return text.n && text.p[text.n-1] == '.';
}
'''


def build(name='prediction', conservative=False):
    from setuptools import Distribution, Extension
    from doc2struct import _native
    snapshot = OUT / 'snapshot'
    if not snapshot.exists():
        snapshot.mkdir(parents=True)
        shutil.copytree(ROOT / 'c', snapshot / 'c')
        shutil.copy2(ROOT / 'python/native/module.c', snapshot / 'module.c')
        manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for root in [ROOT / 'c', ROOT / 'presets', ROOT / 'python/native']
                    for p in root.rglob('*') if p.is_file()}
        (snapshot / 'sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        base = OUT / 'baseline'
        base.mkdir()
        shutil.copy2(_native.__file__, base / Path(_native.__file__).name)
    dest = OUT / name
    dest.mkdir(exist_ok=True)
    original = (snapshot / 'c/src/standardized_text.c').read_text(encoding='utf-8')
    helper = PROSE
    if conservative:
        helper = helper.replace("text.p[i+1] == ' ' && text.p[i+2] >= 'A' && text.p[i+2] <= 'Z') return 1;", """text.p[i+1] == ' ' && text.p[i+2] >= 'A' && text.p[i+2] <= 'Z') {
            size_t start = i;
            while (start && text.p[start-1] >= 'a' && text.p[start-1] <= 'z') start--;
            if (i-start >= 3 && (!start || text.p[start-1] == ' ')) return 1;
        }""")
        helper = helper.replace("return text.n && text.p[text.n-1] == '.';", 'return 0;')
    code = original.replace('static int classify(Document *d, const Rules *r, Vec *lines) {',
                            helper + '\nstatic int classify(Document *d, const Rules *r, Vec *lines) {')
    old = '} else if (!ln->layout_text && (big || (ln->attrs & ~FAKE_TABLE)) && !phone_line(d, ln)) {'
    new = '} else if (!ln->layout_text && (big || (ln->attrs & ~FAKE_TABLE)) && !phone_line(d, ln) && !lab_italic_prose(d, ln, big)) {'
    if code.count(old) != 1:
        raise ValueError('Prediction source shape changed')
    code = code.replace(old, new)
    patched = dest / 'standardized_text.c'
    patched.write_text(code, encoding='utf-8')
    core = snapshot / 'c/src'
    vendor = snapshot / 'c/vendor/pcre2'
    # Use exactly the implementation units selected by the package build.
    names = ['auto_possess', 'chkdint', 'compile', 'compile_cgroup', 'compile_class', 'config',
             'context', 'convert', 'dfa_match', 'error', 'extuni', 'find_bracket', 'jit_compile',
             'maketables', 'match', 'match_data', 'match_next', 'newline', 'ord2utf', 'pattern_info',
             'script_run', 'serialize', 'string_utils', 'study', 'substitute', 'substring',
             'tables', 'ucd', 'valid_utf', 'xclass', 'chartables']
    sources = [str(snapshot / 'module.c')] + [str(p) for p in sorted(core.glob('*.c'))
               if p.stem not in {'cli', 'standardized_text'}] + [str(patched)]
    sources += [str(vendor / ('pcre2_' + name + '.c')) for name in names]
    macros = [(n, '1') for n in ['HAVE_CONFIG_H', 'PCRE2_STATIC', 'SUPPORT_PCRE2_8',
              'SUPPORT_UNICODE', 'HAVE_MEMMOVE', 'HAVE_STDLIB_H', 'HAVE_STDINT_H',
              'HAVE_STRING_H', 'HAVE_INTTYPES_H', 'HAVE_LIMITS_H', '_CRT_SECURE_NO_WARNINGS']]
    macros.append(('PCRE2_CODE_UNIT_WIDTH', '8'))
    extension = Extension(name + '._native', sources=sources,
                          include_dirs=[str(snapshot / 'c/include'), str(core), str(vendor),
                                        str(snapshot / 'c/vendor/pdfium')],
                          define_macros=macros,
                          extra_compile_args=['/O2', '/utf-8', '/std:c11'] if sys.platform == 'win32'
                          else ['-O3', '-std=c11'],
                          libraries=[] if sys.platform == 'win32' else ['m', 'pthread', 'dl'])
    dist = Distribution({'ext_modules': [extension]})
    command = dist.get_command_obj('build_ext')
    command.build_lib = str(OUT)
    command.build_temp = str(OUT / 'objects')
    command.ensure_finalized()
    command.run()
    return dest


def load(name='baseline'):
    import doc2struct._engine as engine
    path = next((OUT / name).glob('_native*' + sysconfig.get_config_var('EXT_SUFFIX')))
    spec = importlib.util.spec_from_file_location('lab_' + name + '._native', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dll = Path(engine.__file__).parent / '_pdfium' / ('doc2struct_pdfium' + engine._pdfium_suffix)
    module.pdfium_init(str(dll))
    return module
