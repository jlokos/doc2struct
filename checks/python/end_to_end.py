"""Public API, native CLI, packaging, and optional pre-refactor comparisons.

Run after installing ./python. --baseline accepts the previous _native binary.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import tempfile

import doc2struct as ds
from doc2struct import _native as native
from doc2struct.rules import merge, RemoveRules, TableRules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', type=Path)
    ap.add_argument('--cli', type=Path)
    ap.add_argument('--corpus', type=Path)
    args = ap.parse_args()
    old = None
    if args.baseline:
        spec = importlib.util.spec_from_file_location('before._native', args.baseline.resolve())
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
    definition = ds.load_rules('SEC:10-K').to_dict()
    rules = native.prepare_rules(definition)
    old_rules = old.prepare_rules(definition) if old else None
    assert ds.load_rules({'remove': {'patterns': None}}).remove.patterns == ds.Rules().remove.patterns
    for invalid in ['{', '[]', '{"headers":null}', '{"name":"a","name":"b"}',
                    '{"name":"\\ud800"}', '{"tables":{"steps":["bad"]}}']:
        try:
            native.prepare_rules(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(invalid)
    for ns in ds.list_namespaces():
        for name in ds.list_document_types(ns):
            loaded = ds.load_rules(f'{ns}:{name}')
            assert loaded.to_dict() == ds.load_rules(f' {ns.lower()} : {name.lower()} ').to_dict()
    fixtures = [b'', b'<', b'<p>Revenue &amp; growth.</p>', b'bad\x80 utf8',
                b'<h1>Item 1. Business</h1><p>A <a href="one">first</a> and <a href="two">second</a>.</p>',
                b'<table><tr><td>Year</td><td>Sales</td></tr><tr><td>2025</td><td>123</td></tr></table>',
                b'<p hidden>A</p><p style="visibility:hidden">B</p><p>C</p>']
    rng = random.Random(122)
    parts = [b'<p>', b'</p>', b'word ', b'&amp;', b'<b>', b'</b>', b'<br>',
             b'<script>ignore</script>', b'<a href="a&amp;b">link</a>', b'\0', b'<span>']
    fixtures += [b''.join(rng.choices(parts, k=30)) for _ in range(200)]
    custom = ds.load_rules({'columns': [
        {'name': 'links', 'source': 'href', 'dtype': 'list'},
        {'name': 'first_link', 'source': 'href'},
        {'name': 'last_link', 'source': 'href', 'which': 'last'},
        {'name': 'match', 'source': 'text', 'pattern': '(Revenue|first)'},
        {'name': 'style_bits', 'source': 'flags', 'dtype': 'int'},
        {'name': 'is_present', 'source': 'text', 'dtype': 'bool'},
    ]}).to_dict()
    custom_rules = native.prepare_rules(custom)
    old_custom = old.prepare_rules(custom) if old else None
    for html in fixtures:
        tokens = native.tokenize(html)
        if old:
            assert tokens == old.tokenize(html)
        for options in [(False, False, 100), (True, True, 4)]:
            runs = native.normalize(tokens, *options)
            if old:
                assert runs == old.normalize(tokens, *options)
            rows = native.parse_html(html, rules, True, *options)
            if old:
                assert rows == old.parse_html(html, old_rules, True, *options)
                assert native.standardize(runs, rules, True) == old.standardize(runs, old_rules, True)
        result = native.parse_html(html, custom_rules, True)
        if old:
            assert result == old.parse_html(html, old_custom, True)
        retained = native.parse_native(bytearray(html), custom_rules, True)
        assert native.native_rows(retained) == result
        columns = native.native_columns(retained)
        assert len(result) == native.native_len(retained)
        assert [{key: values[i] for key, values in columns.items()} for i in range(len(result))] == result
        document = native.parse_native(html, rules, True)
        assert json.loads(native.native_json(document)) == native.native_rows(document)
    # The C merge keeps the existing append/replace rules, including explicit defaults.
    base = ds.load_rules('SEC:10-K')
    for extra in [{}, {'columns': custom['columns']}, {'remove': {'patterns': []}},
                  {'tables': {'preamble_lines': 0}}]:
        extra = ds.load_rules(extra)
        expected = ds.Rules(name=f'{base.name}+{extra.name}', headers=base.headers+extra.headers,
                            columns=base.columns+extra.columns,
                            remove=base.remove if extra.remove == RemoveRules() else extra.remove,
                            tables=base.tables if extra.tables == TableRules() else extra.tables)
        assert merge(base, extra).to_dict() == expected.to_dict()
    with ds.Parser() as parser:
        expected = ds.parse_html(fixtures[4], 'SEC:10-K')
        assert parser.parse_html(fixtures[4], 'SEC:10-K') == expected
        retained = native.parse_native(fixtures[4], rules, True, False, False, 100, parser._handle)
        parser.clear()
    assert native.native_rows(retained) == expected
    del retained
    gc.collect()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(result == expected for result in pool.map(lambda _: ds.parse_html(fixtures[4], 'SEC:10-K'), range(100)))
    count = 0
    paths = sorted(p for p in args.corpus.rglob('*') if p.suffix.lower() in {'.htm', '.html'}) if args.corpus else []
    if args.cli:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.html'
            for html in fixtures[:7]:
                path.write_bytes(html)
                actual = json.loads(subprocess.check_output([str(args.cli.resolve()), str(path), 'SEC:10-K']))
                assert actual == ds.parse_html(html, 'SEC:10-K')
    for path in paths:
        html = path.read_bytes()
        actual = native.parse_html(html, rules, True)
        if old:
            assert actual == old.parse_html(html, old_rules, True), path
        if args.cli:
            assert actual == json.loads(subprocess.check_output([str(args.cli.resolve()), str(path), 'SEC:10-K'])), path
        count += 1
        if count % 25 == 0:
            print(f'Corpus files checked: {count}', flush=True)
    print(f'PASS: presets, {len(fixtures)} fixtures, custom columns, merge, lifetimes, threads, {count} corpus files')


if __name__ == '__main__':
    main()
