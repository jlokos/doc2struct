"""Differential checks for the experimental binaries, against frozen baseline."""
import argparse
import json
import random
from html.entities import html5

from lab import OUT, ROOT, corpus, load, save


def fixtures():
    fixed = [b"", b"<", b"<p>", b"a &amp; b", b"bad \x80 charset", b"\0<p>\xff</p>",
             b"<p href='a>b&copy;'>x</p>", b"<p href='bad", b"<p 'bad>oops",
             b"<!-- -- --><p>after</p>", b"<script>x < y; '</ScRiPt >'<p>after",
             b"<style>x</stylexxx>y</STYLE><p>x", b"<title>x</title>",
             b"<1 &amp; x<p>yes", b"<p hidden style='display:none'>a&amp;b</p>"]
    yield from fixed
    for name in html5:
        yield f'<p alt="a&{name}x">b&{name}</p>'.encode()
    for n in range(145):
        # Every mask alignment, short tail and unterminated delimiter combination.
        pad = b"x" * n
        for end in [b'"', b"'", b"&amp;", b">", b"", b"\xe2\x80\x83"]:
            yield b'<p alt="' + pad + end
            yield pad + b"&amp;<p>x</p>"
            yield b"<!--" + pad + end
            yield b"<script>" + pad + b"</script>"
    rng = random.Random(1701)
    tags = ['p', 'SPAN', 'div', 'b', 'script', 'style', 'title', 'table', 'td', 'br', 'x:tag', 'pΣ']
    names = ['style', 'STYLE', 'alt', 'href', 'src', 'colspan', 'rowspan', 'hidden', 'id', 'class', 'data-other', 'a\u2003style']
    values = ['', 'a>b<c', '&amp;', '&#160;', 'font-size:12px', 'x/y', 'display:none', 'éΣ', '\x00', '1', '2', '"a\'b', 'x' * 65]
    spaces = [' ', '\t', '\r\n', '\u00a0', '\u2003', '\x1c', '\x01', '']
    for _ in range(12000):
        tag = rng.choice(tags)
        parts = ['prefix &amp; <body><', '/' if rng.randrange(12) == 0 else '', tag]
        for _ in range(rng.randrange(6)):
            parts.extend([rng.choice(spaces), rng.choice(names)])
            if rng.randrange(6):
                quote = rng.choice(['"', "'", '', '"'])
                parts.extend([rng.choice(spaces), '=', rng.choice(spaces), quote,
                              rng.choice(values), quote if rng.randrange(15) else ''])
        parts.extend([rng.choice(['>', '/>', ' / >', '', '>>']), rng.choice(values), '</', tag, '><p>after &amp;</p>'])
        yield ''.join(parts).encode('utf-8')
    for n in [1023, 2047, 4095]:
        yield (b'<p style="font-size:12px" alt="a&amp;b">text &amp;</p>' * n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='+')
    ap.add_argument('--skip-corpus-tokens', action='store_true')
    args = ap.parse_args()
    baseline = load('baseline')
    mods = {name: load(name) for name in args.names}
    rules = json.loads((OUT / 'snapshot/rules.json').read_text())
    base_rules = baseline.prepare_rules(rules)
    prepared = {n: m.prepare_rules(rules) for n, m in mods.items()}
    counts = {'generated_token_cases': 0, 'corpus_token_files': 0, 'corpus_parse_files': 0}
    for i, data in enumerate(fixtures()):
        expected = baseline.tokenize(data)
        for name, mod in mods.items():
            if mod.tokenize(data) != expected:
                (OUT / 'failure.html').write_bytes(data)
                raise AssertionError((name, 'tokens', i, repr(data[:200])))
        counts['generated_token_cases'] += 1
    print('Generated token cases match:', counts['generated_token_cases'], flush=True)
    for path, data in corpus():
        expected = baseline.parse_html(data, base_rules, True, False, False, 100)
        for name, mod in mods.items():
            assert mod.parse_html(data, prepared[name], True, False, False, 100) == expected, (name, 'parse', path)
        counts['corpus_parse_files'] += 1
        if not args.skip_corpus_tokens:
            expected = baseline.tokenize(data)
            for name, mod in mods.items():
                assert mod.tokenize(data) == expected, (name, 'tokens', path)
            counts['corpus_token_files'] += 1
        if counts['corpus_parse_files'] % 25 == 0:
            print('Corpus files checked:', counts['corpus_parse_files'], flush=True)
    save(OUT / ('checks-' + '-'.join(args.names) + '.json'), {'variants': args.names, **counts})
    print('PASS', counts, flush=True)


if __name__ == '__main__':
    main()
