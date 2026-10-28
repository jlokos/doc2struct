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
from doc2struct.rules import merge, ListRules, RemoveRules, TableRules


def check_preserved_text():
    """Cleanup preserves content without turning boilerplate into structure."""
    def parse(html, rules=None):
        content = html.encode()
        rows = ds.parse_html(content, rules)
        assert rows == ds.convert_instructions_to_standardized_text(ds.normalize(ds.tokenize(content)), rules)
        return [r for r in rows if not (r['type'] == 'title' and r['text'] == 'introduction')]

    rows = parse('<p>before</p><p>123</p><p>___</p><p><a href="#toc">Table of Contents</a></p><p>after</p>')
    assert [r['text'] for r in rows] == ['before', '123', '___', 'Table of Contents', 'after']
    assert [r['type'] for r in rows] == ['text', 'redundant', 'redundant', 'redundant', 'text']
    rows = parse('<p><b>7</b> apples</p>')
    assert [(r['type'], r['text']) for r in rows] == [('redundant', '7'), ('text', 'apples')]
    rows = parse('<p>Repeated notice.</p><p>Middle text.</p><p>Repeated notice.</p>',
                 {'remove': {'patterns': [], 'repeat_threshold': 2, 'page_label_regex': None}})
    assert [(r['type'], r['text']) for r in rows] == [
        ('redundant', 'Repeated notice.'), ('text', 'Middle text.'), ('redundant', 'Repeated notice.')]
    assert parse('<p>Repeated notice.</p>'*2, {'remove': {'repeat_threshold': None}})[0]['type'] == 'text'
    rows = parse('<p>F-1</p><p>F-2</p><p>F-3</p>')
    assert all(r['type'] == 'redundant' for r in rows)
    assert parse('<p>F-1</p>')[0]['type'] != 'redundant'
    rows = parse('<h1>F-1</h1><p>F-2</p><p>F-3</p>')
    assert rows[0]['text'] == 'F-1' and rows[0]['type'] != 'redundant'
    rows = parse('<p style="font-size:12px">body text.</p>'*3 + '<p style="font-size:8px">F-1</p>')
    assert rows[-1]['type'] == 'redundant'
    rows = parse('<p>F-1</p><p>F-2</p><p>F-3</p>', {'remove': {'page_label_regex': None}})
    assert all(r['type'] != 'redundant' for r in rows)
    rows = parse('<p>● Actual list content</p><p>● ● ●</p>')
    assert rows[0]['type'] == 'list' and 'Actual list content' in rows[0]['matrix'][0][1]
    assert rows[-1]['type'] == 'redundant'
    table = '<table><tr><td>Year</td><td>Sales</td></tr><tr><td>2025</td><td>100</td></tr></table>'
    rows = parse(table + '<p>(1) Includes all sales.</p><p>(415) 326-6303</p><p>548 Market Street</p>')
    actual_table = next(r for r in rows if r['type'] == 'table')
    assert actual_table['footnotes'] == [['(1)', 'Includes all sales.']]
    assert any(r['type'] == 'text' and '(415) 326-6303' in r['text'] for r in rows)
    assert any(r['type'] == 'text' and '548 Market Street' in r['text'] for r in rows)
    rows = parse(table + '<p>548 Market Street</p>')
    assert not next(r for r in rows if r['type'] == 'table')['footnotes']
    rows = parse(table + '<p>F-1</p><p>F-2</p><p>F-3</p>')
    assert all(not next(r for r in rows if r['type'] == 'table')[key]
               for key in ['preamble', 'footnotes', 'postamble'])
    sentence = 'Our business depends on ' + 'continued customer demand and reliable services ' * 7 + 'worldwide.'
    paragraph = sentence + ' These statements describe our operations and the information investors should consider.'
    assert parse('<p><i>'+sentence+'</i></p>')[0]['type'] == 'title'
    assert parse('<p><i>'+paragraph+'</i></p>')[0]['type'] == 'text'
    assert parse('<h2><i>'+paragraph+'</i></h2>')[0]['type'] == 'title'
    rows = parse('<h1>Item 1. Business</h1><h1>Item 1. Business (continued)</h1><p>body text.</p>', 'SEC:10-K')
    assert any(r['type'] == 'redundant' and 'continued' in r['text'] for r in rows)


def check_text_blocks():
    def parse(html, rules=None):
        content = html.encode()
        rows = ds.parse_html(content, rules)
        assert rows == ds.convert_instructions_to_standardized_text(ds.normalize(ds.tokenize(content)), rules)
        assert [r['id'] for r in rows] == list(range(len(rows)))
        return rows[1:]

    rows = parse('<p>first line.</p><p>second line.</p><p>third line.</p>')
    assert len(rows) == 1 and rows[0]['text'] == 'first line. second line. third line.'
    rows = parse('<p>first</p><p>second</p><p>123</p><p>456</p><p>third</p><p>fourth</p>')
    assert [(r['type'], r['text']) for r in rows] == [
        ('text', 'first second'), ('redundant', '123'), ('redundant', '456'), ('text', 'third fourth')]
    rows = parse('<p>before</p><h2>New Section</h2><p>after</p><p>last</p>')
    assert [r['type'] for r in rows] == ['text', 'title', 'text']
    assert rows[-1]['text'] == 'after last'
    rows = parse('<p>before</p><h2>Item 1. Business</h2><p>after</p><p>last</p>', 'SEC:10-K')
    assert rows[-1]['text'] == 'after last' and rows[-1]['level'] != rows[0]['level']
    rows = parse('<p>before</p><p><img src="logo.png" alt="logo"></p><p>after</p>')
    assert [r['type'] for r in rows] == ['text', 'image', 'text']
    rows = parse('<p>before</p><ul><li>an item</li></ul><p>after</p>')
    assert [r['type'] for r in rows] == ['text', 'list', 'text']
    table = '<table><tr><td>Year</td><td>Sales</td></tr><tr><td>2025</td><td>100</td></tr></table>'
    rows = parse('<p>before</p>'+table+'<p>after</p>',
                 {'tables': {'preamble_lines': 0, 'postamble_lines': 0}})
    assert [r['type'] for r in rows] == ['text', 'table', 'text']
    rows = parse('<p style="font-size:12px">first</p><p style="font-size:12px">second</p>'
                 '<p style="font-size:8px">small one</p><p style="font-size:8px">small two</p>'
                 '<p style="font-size:12px">third</p><p style="font-size:12px">fourth</p>'
                 '<p style="font-size:12px">last</p>')
    assert [r['type'] for r in rows] == ['text', 'textsmall', 'text']
    assert rows[1]['text'] == 'small one small two'
    assert rows[0]['text'] == 'first second' and rows[-1]['text'] == 'third fourth last'
    rows = parse('<p><a href="one">first</a></p><p><a href="two">second</a></p>', {'columns': [
        {'name': 'links', 'source': 'href', 'dtype': 'list'},
        {'name': 'last_link', 'source': 'href', 'which': 'last'}]})
    assert len(rows) == 1 and rows[0]['text'] == 'first second'
    assert rows[0]['links'] == ['one', 'two'] and rows[0]['last_link'] == 'two'
    rows = parse('<p>caf\u00e9</p><p>na\u00efve</p>')
    assert rows[0]['text'] == 'caf\u00e9 na\u00efve'
    lines = [f'line {i}.' for i in range(2000)]
    rows = parse(''.join('<p>'+line+'</p>' for line in lines))
    assert len(rows) == 1 and rows[0]['text'] == ' '.join(lines)


def check_title_blocks():
    def parse(html, rules=None):
        data = html.encode()
        rows = ds.parse_html(data, rules)
        assert rows == ds.convert_instructions_to_standardized_text(ds.normalize(ds.tokenize(data)), rules)
        assert [r['id'] for r in rows] == list(range(len(rows)))
        assert rows[0]['text'] == 'introduction'
        return rows[1:]

    fragments = [
        'We are highly dependent on the continued service of our co-founders, senior management',
        'team, and key technical employees, and the loss of any of these individuals may adversely',
        'affect our business, financial condition, and results of operations.']
    rows = parse(''.join('<p><b><i>'+t+'</i></b></p>' for t in fragments), 'SEC:S-1')
    assert len(rows) == 1 and rows[0]['type'] == 'title' and rows[0]['text'] == ' '.join(fragments)
    # Matching titles merge even when they are complete, capitalized phrases.
    rows = parse('<p><b>Revenue</b></p><p><b>Expenses</b></p>')
    assert len(rows) == 1 and rows[0]['text'] == 'Revenue Expenses'
    rules = {'headers': [{'name': 'section', 'regex': '^section', 'level': 0, 'requires': []}]}
    rows = parse('<p><b>Section one</b></p><p><i>Section two</i></p>', rules)
    assert len(rows) == 2 and rows[0]['level'] == rows[1]['level']
    rows = parse('<p style="font-size:18px"><b>Section one</b></p>'
                 '<p style="font-size:20px"><b>Section two</b></p>', rules)
    assert len(rows) == 2
    rows = parse('<p style="margin-left:10px"><b>Section one</b></p>'
                 '<p style="margin-left:20px"><b>Section two</b></p>', rules)
    assert len(rows) == 2
    rows = parse('<p><b>Section one</b></p><p><b>Section two</b></p>', {'headers': [
        {'name': 'one', 'regex': '^section one$', 'level': 0},
        {'name': 'two', 'regex': '^section two$', 'level': 1}]})
    assert len(rows) == 2 and rows[0]['level'] != rows[1]['level']
    for separator, kind in [('<p>123</p>', 'redundant'), ('<p>ordinary prose.</p>', 'text')]:
        rows = parse('<p><b>Revenue</b></p>'+separator+'<p><b>Expenses</b></p>')
        assert [r['type'] for r in rows] == ['title', kind, 'title']
    table = '<table><tr><td>Year</td><td>Sales</td></tr><tr><td>2025</td><td>100</td></tr></table>'
    rows = parse('<p><b>Financial</b></p><p><b>Information</b></p>'+table)
    assert rows[0]['text'] == 'Financial Information'
    assert rows[1]['type'] == 'table' and rows[1]['text'] == 'Financial Information'
    rows = parse('<p><b><a href="one">Revenue</a></b></p><p><b><a href="two">Expenses</a></b></p>',
                 {'columns': [{'name': 'links', 'source': 'href', 'dtype': 'list'}]})
    assert len(rows) == 1 and rows[0]['links'] == ['one', 'two']


def check_list_continuations():
    def item(text):
        return '<p>\u2022'+text+'</p>'

    def plain(text):
        return '<p>'+text+'</p>'

    def parse(html, lists=None, **extra):
        rules = {'lists': lists or {}, **extra}
        data = html.encode()
        rows = ds.parse_html(data, rules)
        assert rows == ds.convert_instructions_to_standardized_text(ds.normalize(ds.tokenize(data)), rules)
        assert [r['id'] for r in rows] == list(range(len(rows)))
        return rows[1:]

    assert ds.load_rules({}).lists == ListRules(max_gap_rows=3, max_tail_rows=1)
    for count in [1, 2, 3, 4]:
        gap = ''.join(plain(f'continuation {i}.') for i in range(count))
        rows = parse(item('first.')+gap+item('second.'), {'max_tail_rows': 0})
        if count <= 3:
            assert len(rows) == 1 and len(rows[0]['matrix']) == 2
            assert rows[0]['matrix'][0][1] == '\u2022first. ' + ' '.join(f'continuation {i}.' for i in range(count))
        else:
            assert [r['type'] for r in rows] == ['list', 'text', 'list']
            assert rows[0]['matrix'][0][1] == '\u2022first.'
    html = (item('first.')+plain('Capitalized continuation.')+plain('Another continuation.')+
            item('second.')+plain('Tail continuation.')+plain('Independent paragraph.')+plain('More prose.'))
    rows = parse(html)
    assert [r['type'] for r in rows] == ['list', 'text']
    assert rows[0]['matrix'] == [['0', '\u2022first. Capitalized continuation. Another continuation.'],
                                ['0', '\u2022second. Tail continuation.']]
    assert rows[1]['text'] == 'Independent paragraph. More prose.'
    rows = parse(html, {'max_gap_rows': 1})
    assert sum(r['type'] == 'list' for r in rows) == 2
    rows = parse(html, {'max_tail_rows': 0})
    assert rows[0]['matrix'][1][1] == '\u2022second.'
    assert rows[1]['text'].startswith('Tail continuation.')
    rows = parse(html, {'max_tail_rows': 2})
    assert rows[0]['matrix'][1][1] == '\u2022second. Tail continuation. Independent paragraph.'
    assert rows[1]['text'] == 'More prose.'
    rows = parse(html, {'max_gap_rows': 0, 'max_tail_rows': 2})
    assert sum(r['type'] == 'list' for r in rows) == 2
    assert all(len(r['matrix']) == 1 for r in rows if r['type'] == 'list')
    rows = parse(item('lone item.')+plain('Following prose.'))
    assert [r['type'] for r in rows] == ['list', 'text']
    long_gap = ''.join(plain(f'gap {i}.') for i in range(4))
    rows = parse(item('first.')+plain('bridge.')+item('second.')+long_gap+item('third.'))
    assert [r['type'] for r in rows] == ['list', 'text', 'list']
    assert rows[0]['matrix'][1][1] == '\u2022second.'
    rows = parse(item('first.')+long_gap+item('second.'), {'max_gap_rows': 4})
    assert len(rows) == 1 and len(rows[0]['matrix']) == 2
    for barrier in [plain('123'), '<h2>A Heading</h2>', '<p><img src="x" alt="image"></p>']:
        rows = parse(item('first.')+plain('continuation.')+barrier+item('second.'))
        assert sum(r['type'] == 'list' for r in rows) == 2
    for style in ['font-size:8px', 'margin-left:12px']:
        rows = parse(item('first.')+f'<p style="{style}">different attributes.</p>'+item('second.'))
        assert sum(r['type'] == 'list' for r in rows) == 2
    # A separately styled bullet must not dictate the payload's attributes.
    rows = parse('<p><b>\u2022</b>first item</p>'+plain('continuation.')+'<p><b>\u2022</b>second item</p>')
    assert len(rows) == 1 and rows[0]['matrix'][0][1] == '\u2022first item continuation.'
    rows = parse('<p>\u2022<a href="one">first item</a></p><p><a href="continuation">continued</a></p>'
                 '<p>\u2022<a href="two">second item</a></p>',
                 columns=[{'name': 'links', 'source': 'href', 'dtype': 'list'}])
    assert len(rows) == 1 and rows[0]['links'] == ['one', 'continuation', 'two']
    for field, value in [('max_gap_rows', -1), ('max_tail_rows', -1),
                         ('max_gap_rows', 1.5), ('max_tail_rows', True)]:
        try:
            ds.load_rules({'lists': {field: value}})
        except ValueError:
            pass
        else:
            raise AssertionError((field, value))


def check_shared_header_styles():
    header = {'name': 'topic', 'regex': r'^underwriting\b', 'level': 0}

    def matches(html, extra=None, rule=None):
        rules = {'headers': [header if rule is None else rule], **(extra or {})}
        content = html.encode()
        rows = ds.parse_html(content, rules)
        assert rows == ds.convert_instructions_to_standardized_text(ds.normalize(ds.tokenize(content)), rules)
        return any(r['class'] == 'topic' for r in rows)

    assert ds.Rules().header_styles == ('bold', 'all_caps', 'proper_case')
    assert ds.Rules().lists.max_tail_rows == 1
    assert not matches('<p>underwriting discounts and commissions apply.</p>')
    assert matches('<p><b>underwriting expanded terms</b></p>')
    assert matches('<p>UNDERWRITING EXPANDED TERMS</p>')
    assert matches('<p>Underwriting Agreement</p>')
    assert not matches('<p><i>underwriting expanded terms</i></p>')
    assert matches('<p>underwriting expanded terms</p>', {'header_styles': []})
    assert matches('<p>underwriting expanded terms</p>', rule={**header, 'requires': []})
    assert matches('<p><u>underwriting expanded terms</u></p>', {'header_styles': ['underline']})
    assert matches('<p><i>underwriting expanded terms</i></p>', rule={**header, 'requires': ['italic']})
    both = {**header, 'requires': ['bold', 'italic']}
    assert not matches('<p><b>underwriting expanded terms</b></p>', rule=both)
    assert matches('<p><b><i>underwriting expanded terms</i></b></p>', rule=both)
    inherited = ds.HeaderRule('topic', '^underwriting', 0)
    unstyled = ds.HeaderRule('topic', '^underwriting', 0, requires=())
    assert 'requires' not in inherited.to_dict()
    assert unstyled.to_dict()['requires'] == []
    assert ds.load_rules({'headers': [unstyled.to_dict()]}).headers[0].requires == ()
    assert ds.load_rules({'headers': [inherited.to_dict()]}).headers[0].requires is None
    for styles in [[], ['underline']]:
        assert merge(ds.load_rules({}), ds.load_rules({'header_styles': styles})).header_styles == tuple(styles)
    for name, text in [('item', 'item 1. business'), ('part', 'part i')]:
        assert any(r['class'] == name for r in ds.parse_html(('<p>'+text+'</p>').encode(), 'SEC:10-K'))
    for invalid in [{'header_styles': None}, {'header_styles': 'bold'}, {'header_styles': ['unknown']},
                    {'header_styles': [1]}, {'headers': [{**header, 'requires': None}]}]:
        try:
            ds.load_rules(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(invalid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', type=Path)
    ap.add_argument('--cli', type=Path)
    ap.add_argument('--corpus', type=Path)
    args = ap.parse_args()
    check_shared_header_styles()
    check_preserved_text()
    check_text_blocks()
    check_title_blocks()
    check_list_continuations()
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
                  {'tables': {'preamble_lines': 0}}, {'lists': {'max_gap_rows': 0}}]:
        extra = ds.load_rules(extra)
        expected = ds.Rules(name=f'{base.name}+{extra.name}', headers=base.headers+extra.headers,
                            columns=base.columns+extra.columns,
                            remove=base.remove if extra.remove == RemoveRules() else extra.remove,
                            tables=base.tables if extra.tables == TableRules() else extra.tables,
                            lists=base.lists if extra.lists == ListRules() else extra.lists)
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
