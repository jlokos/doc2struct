"""Snapshot public API results, then compare another build field for field.

Run once per build using its PYTHONPATH (or installed environment):
  python build_scripts/check_equivalence.py --snapshot build/before.jsonl
  python build_scripts/check_equivalence.py --compare build/before.jsonl
Use identical --random-cases, --seed and --corpus arguments for both runs.
Inputs include malformed HTML, custom metadata, tables, text, SGML and PDF.
Snapshot paths ending in .gz use gzip compression.
"""
import argparse
import gzip
import itertools
import json
from pathlib import Path
import random


METADATA_RULES = {'columns': [
    {'name': name, 'source': source, 'dtype': 'list', 'which': 'all'}
    for name, source in [('links', 'href'), ('sources', 'src'), ('fonts', 'font_size'),
                         ('indents', 'indent'), ('styles', 'flags')]
]}


def html_cases(count, seed):
    cases = [
        b'', b'plain text', b'<head>ignored</head><p>Visible</p>',
        b'<p>one<p>two<div>three</div>four',
        b'<ul><li>one<li><b>two</b><ul><li>inner</ul><li>last</ul>',
        b'<dl><dt>term<dd>definition<dt>next<dd>another</dl>',
        b'<p>lead <b>bold <i>both</i></b> plain <img src="x" alt="a">after</p>',
        b'<p><a href="a">first </a><b><a href="b">bold </a></b><a href="c">last</a></p>',
        b'<div hidden><p>hidden</div><div style="display:none"><b>hidden</b></div><p>visible',
        b'<p>caf\xe9 &amp; &#x3a3; &nGt; &NotEqualTilde; &#0; &#129;</p>',
        '<p>ΣΟΣ ΟΣ\u00a0\u200b İstanbul K café 🙂</p>'.encode(),
        b'<p>before<table><tr><td rowspan="3">a<td>b<tr><td>c</table>after',
        b'<table><thead><tr><th colspan="2">2025<tbody><tr><td>$<td>123<tr><td>($<td>42)</table>',
        b'<table><tr><td>before<table><tr><td>nested</td></tr></table>after<td>end</table>',
        b'<table><tr><td><ul><li>one<li>two</ul><td>other</tr></table>',
        b'<p>Item 1A. Risk Factors</p><p>Prose.</p><table><tr><td>2025<td>2024<tr><td>12<td>10</table>',
        b'<div>' * 256 + b'<p>deep<p>next' + b'</div>' * 256,
        b'<p>' + b'<span>fragment </span>' * 2048 + b'</p>',
        b'<table><tr>' + b'<td rowspan="2">same</td>' * 129 + b'<tr><td>last</table>',
        b'<table><tr><td colspan="63">span</td><td rowspan="2">r</td><td>z</td></tr><tr><td>end</table>',
    ]
    rng = random.Random(seed)
    tags = ['p', 'div', 'span', 'b', 'i', 'u', 'a', 'ul', 'ol', 'li', 'dl', 'dt', 'dd',
            'table', 'tr', 'td', 'th', 'tbody', 'thead', 'h1', 'section', 'body', 'html', 'unknown']
    attributes = ['', ' style="font-weight:bold"', ' style="font-size:13px;margin-left:24px"',
                  ' href="/a&amp;b"', ' hidden', ' style="display:none"',
                  ' colspan="3" rowspan="2"', ' style="font-style:italic"']
    text = ['words ', 'Item 1. Business', '1. List item', '2025', '$', '123', ' ',
            '\u00a0\u200b', 'ΣΟΣ café', '&amp;&#160;', '<img src="x" alt="logo">', '<br>']
    for _ in range(count):
        pieces = []
        for _ in range(rng.randrange(10, 100)):
            tag = rng.choice(tags)
            choice = rng.randrange(3)
            pieces.append('<' + tag + rng.choice(attributes) + '>' if choice == 0 else
                          '</' + tag + '>' if choice == 1 else rng.choice(text))
        cases.append(''.join(pieces).encode())
    return cases


def instruction_cases(count, seed):
    rng = random.Random(seed)
    for _ in range(count):
        runs = []
        for i in range(rng.randrange(1, 100)):
            runs.append(dict(block=i // 30, line=i // 7, row=None, col=None, span=None,
                             text=rng.choice(['', ' ', 'alpha ', 'BETA', 'tail', '\u200b', '\u00a0', 'ΣΟΣ']),
                             flags=rng.choice([0, 1, 2, 3, 4, 8]),
                             font_size=rng.choice([None, 12.0, 14.0]),
                             indent=rng.choice([None, 0.0, 24.0]),
                             href=rng.choice([None, '', '/a', '/b']), tag='p',
                             src=rng.choice([None] * 9 + ['', 'img.png'])))
        yield runs


def results(d, args):
    from smoke_release import basic_pdf

    def checked(name, call):
        try:
            value = call()
        except Exception as exc:
            value = dict(error=type(exc).__name__, message=str(exc))
        return dict(case=name, result=value)

    cases = html_cases(args.random_cases, args.seed)
    for source in args.corpus:
        files = sorted(p for p in source.rglob('*') if p.suffix.lower() in ('.htm', '.html')) if source.is_dir() else [source]
        cases.extend(p.read_bytes() for p in files)
    for index, html in enumerate(cases):
        tokens = list(d.tokenize(html))
        yield dict(case=f'html/{index}/tokens', result=tokens)
        for ri, rules in enumerate([None, 'SEC:10-K', METADATA_RULES]):
            prefix = f'html/{index}/rules/{ri}/'
            runs = d.convert_html_to_instructions(html, rules)
            yield dict(case=prefix + 'instructions', result=runs)
            yield checked(prefix + 'normalize', lambda: d.normalize(tokens, rules))
            yield checked(prefix + 'parse', lambda: d.parse_html(html, rules))
            yield checked(prefix + 'standardize', lambda: d.convert_instructions_to_standardized_text(runs, rules))
            with d.Parser(4096) as parser:
                for repeat in range(2):
                    yield checked(prefix + f'parser/{repeat}', lambda: parser.parse_html(html, rules))
                    assert parser.cached_bytes <= parser.cache_size
    for index, runs in enumerate(instruction_cases(args.random_cases, args.seed)):
        yield checked(f'runs/{index}', lambda: d.convert_instructions_to_standardized_text(runs, METADATA_RULES))
    texts = [b'', b'Item 1. Business\n\nProse with words.\n', b'\tName\t2025\t2024\n\tSales\t123\t100\n',
             b'<TEXT>\n<B>Item 1A.</B>\nplain text\n<TABLE>\nYear   Value\n2025   123\n</TABLE>\n</TEXT>',
             b'caf\xe9\r\ntext\fformfeed', 'ΣΟΣ café\u00a0🙂'.encode()]
    for index, text in enumerate(texts):
        for kind in ('text', 'partialsgml'):
            convert = getattr(d, f'convert_{kind}_to_instructions')
            parse = getattr(d, f'parse_{kind}')
            for ri, rules in enumerate([None, 'SEC:10-K', METADATA_RULES]):
                yield checked(f'{kind}/{index}/{ri}/instructions', lambda: convert(text, rules))
                yield checked(f'{kind}/{index}/{ri}/parse', lambda: parse(text, rules))
                yield checked(f'{kind}/{index}/{ri}/standardize', lambda: d.convert_instructions_to_standardized_text(convert(text, rules), rules))
    for ri, rules in enumerate([None, 'SEC:10-K', METADATA_RULES]):
        yield checked(f'pdf/{ri}/instructions', lambda: d.convert_pdf_to_instructions(basic_pdf(), rules))
        yield checked(f'pdf/{ri}/parse', lambda: d.parse_pdf(basic_pdf(), rules))
    for name, call in [
        ('html_type', lambda: d.parse_html('not bytes')),
        ('pdf_invalid', lambda: d.parse_pdf(b'invalid')),
        ('instruction_field', lambda: d.convert_instructions_to_standardized_text([{}])),
    ]:
        yield checked('errors/' + name, call)
    d.clear_parser_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--snapshot', type=Path)
    mode.add_argument('--compare', type=Path)
    parser.add_argument('--random-cases', type=int, default=500)
    parser.add_argument('--seed', type=int, default=20261104)
    parser.add_argument('--corpus', nargs='*', type=Path, default=[])
    args = parser.parse_args()
    if args.random_cases < 0:
        parser.error('--random-cases must be nonnegative')
    import doc2struct as d
    records = (json.dumps(record, sort_keys=True, ensure_ascii=True) + '\n' for record in results(d, args))
    count = 0
    if args.snapshot:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        with (gzip.open(args.snapshot, 'wt', encoding='utf-8') if args.snapshot.suffix == '.gz' else
              args.snapshot.open('w', encoding='utf-8')) as output:
            for count, record in enumerate(records, 1):
                output.write(record)
    else:
        with (gzip.open(args.compare, 'rt', encoding='utf-8') if args.compare.suffix == '.gz' else
              args.compare.open(encoding='utf-8')) as reference:
            for count, (expected, actual) in enumerate(itertools.zip_longest(reference, records), 1):
                if expected != actual:
                    label = json.loads(actual or expected)['case']
                    raise AssertionError(f'Result {count} differs: {label}')
    print(f'{count} public API results ' + ('recorded' if args.snapshot else 'identical'))


if __name__ == '__main__':
    main()
