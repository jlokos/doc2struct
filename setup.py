from pathlib import Path
import runpy
import sys

from setuptools import Extension, setup, find_packages

BuildNative = runpy.run_path(str(Path(__file__).with_name('build_support.py')))['BuildNative']


pcre = Path('c/vendor/pcre2')
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
    packages=find_packages(),
    package_data={'doc2struct': ['rules/presets/*.json']},
    license_files=['c/vendor/pcre2/LICENCE.md'],
    ext_modules=[Extension(
        'doc2struct._native',
        sources=[
            'c/memory.c', 'c/text.c', 'c/tokenizer.c', 'c/normalizer.c',
            'c/rules.c', 'c/parser.c', 'c/standardized_text.c', 'c/lists.c', 'c/flow.c', 'c/json.c', 'c/tables.c', 'c/python/module.c',
        ] + [str(pcre / ('pcre2_' + name + '.c')) for name in pcre_sources],
        include_dirs=['c', str(pcre)],
        depends=['c/doc2struct.h', 'c/unicode_data.h', 'c/scan.h', 'c/tags.h'] + [str(p) for p in pcre.glob('*.h')],
        define_macros=macros,
        extra_compile_args=['/O2', '/utf-8', '/std:c11'] if sys.platform == 'win32' else ['-O3', '-std=c11'],
        libraries=[] if sys.platform == 'win32' else ['m'],
    )],
    cmdclass={'build_ext': BuildNative},
    install_requires=[],
    extras_require={'parquet': ['polars']},
)
