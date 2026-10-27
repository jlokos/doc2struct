from pathlib import Path
import runpy
import sys
import shutil

from setuptools import Extension, setup, find_packages

BuildNative = runpy.run_path(str(Path(__file__).with_name('build_support.py')))['BuildNative']


# Refresh build inputs from the canonical shared tree. An sdist carries these
# inputs itself and does not need a sibling checkout or Python to build CMake.
root = Path(__file__).resolve().parent.parent
bundled = Path('_native_source')
if (root / 'c/src/api.c').is_file():
    runpy.run_path(str(root / 'tools/generate_presets.py'))['generate'](root / 'presets', root / 'c/src/preset_data.h')
    for directory in ('c', 'presets', 'tools'):
        for source in (root / directory).rglob('*'):
            if not source.is_file() or '__pycache__' in source.parts:
                continue
            target = bundled / source.relative_to(root)
            if not target.exists() or target.read_bytes() != source.read_bytes():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

pcre = bundled / 'c/vendor/pcre2'
core = bundled / 'c/src'
pcre_sources = [
    'auto_possess', 'chkdint', 'compile', 'compile_cgroup', 'compile_class', 'config', 'context',
    'convert', 'dfa_match', 'error', 'extuni', 'find_bracket', 'jit_compile',
    'maketables', 'match', 'match_data', 'match_next', 'newline', 'ord2utf', 'pattern_info',
    'script_run', 'serialize', 'string_utils', 'study', 'substitute', 'substring',
    'tables', 'ucd', 'valid_utf', 'xclass', 'chartables',
]
macros = [(name, '1') for name in (
    'HAVE_CONFIG_H', 'PCRE2_STATIC', 'SUPPORT_PCRE2_8', 'SUPPORT_UNICODE',
    'HAVE_MEMMOVE', 'HAVE_STDLIB_H', 'HAVE_STDINT_H', 'HAVE_STRING_H',
    'HAVE_INTTYPES_H', 'HAVE_LIMITS_H',
)]
macros.append(('PCRE2_CODE_UNIT_WIDTH', '8'))

setup(
    name="doc2struct",
    version="0.1.0",
    python_requires='>=3.10',
    package_dir={'': 'src'},
    packages=find_packages('src'),
    license_files=['_native_source/c/vendor/pcre2/LICENCE.md', '_native_source/c/vendor/pdfium/LICENSE'],
    package_data={'doc2struct': ['_pdfium/*', '_pdfium/licenses/*']},
    ext_modules=[Extension(
        'doc2struct._native',
        sources=['native/module.c'] + [str(core / (name + '.c')) for name in (
            'api', 'config', 'config_json', 'memory', 'text', 'tokenizer', 'normalizer',
            'rules', 'parser', 'standardized_text', 'lists', 'flow', 'json', 'tables', 'pdf', 'pdf_layout',
        )] + [str(pcre / ('pcre2_' + name + '.c')) for name in pcre_sources],
        include_dirs=[str(bundled / 'c/include'), str(core), str(pcre), str(bundled / 'c/vendor/pdfium')],
        depends=[str(p) for p in core.glob('*.h')] + [str(bundled / 'c/include/doc2struct/doc2struct.h')] + [str(p) for p in pcre.glob('*.h')],
        define_macros=macros,
        extra_compile_args=['/O2', '/utf-8', '/std:c11'] if sys.platform == 'win32' else ['-O3', '-std=c11'],
        libraries=[] if sys.platform == 'win32' else (['m', 'pthread'] if sys.platform == 'darwin' else ['m', 'pthread', 'dl']),
    )],
    cmdclass={'build_ext': BuildNative},
    install_requires=[],
    extras_require={'parquet': ['polars']},
)
