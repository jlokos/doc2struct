"""Extra parity checks for finalists: options, malformed inputs, cache boundaries."""
import argparse
import hashlib
import json

from check import fixtures
from lab import OUT, ROOT, load, save


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='+')
    args = ap.parse_args()
    baseline = load('baseline')
    mods = {name: load(name) for name in args.names}
    from doc2struct.rules import Rules
    definitions = [Rules().to_dict(), json.loads((OUT / 'snapshot/rules.json').read_text())]
    configs = []
    for definition in definitions:
        configs.append((baseline.prepare_rules(definition), {
            name: mod.prepare_rules(definition) for name, mod in mods.items()}))
    generated = [data for i, data in enumerate(fixtures()) if i % 29 == 0]
    generated += [b'<p alt="' + bytes([i]) + b'">' + bytes([i]) + b'</p>' for i in range(256)]
    # Trigger the template cache, eviction, collisions, long comparisons and tails.
    for n in [65535, 65536, 65537, 66048, 131072]:
        unit = b'<p style="font-size:12px" alt="&amp;">a&amp;b</p>'
        generated.append((unit * (n // len(unit) + 1))[:n])
    for length in [7, 8, 15, 16, 17, 31, 32, 33, 63, 64, 65, 511, 512, 513, 4096]:
        unit = b'<p alt="' + b'x' * length + b'&amp;">plain &amp;</p>'
        generated.append(unit * (70000 // len(unit) + 1))
    generated.append(b''.join(b'<p alt="prefix%06d&copy;suffix">text</p>' % i for i in range(6000)))
    count = 0
    for i, data in enumerate(generated):
        for kind, (base_rule, prepared) in enumerate(configs):
            for hidden, visibility in [(False, False), (True, True)]:
                def call(mod, rule):
                    try:
                        return ('ok', mod.parse_html(data, rule, bool(kind), hidden, visibility, 100))
                    except Exception as exc:
                        return ('error', type(exc).__name__, str(exc))
                expected = call(baseline, base_rule)
                for name, mod in mods.items():
                    assert call(mod, prepared[name]) == expected, (name, i, kind, hidden)
                count += 1
    print('Generated full-parse cases match:', count, flush=True)
    extra = []
    for path in sorted((ROOT / 'data/filings/test_work').rglob('*.htm')):
        data = path.read_bytes()
        for kind, (base_rule, prepared) in enumerate(configs):
            expected = baseline.parse_html(data, base_rule, bool(kind), False, False, 100)
            for name, mod in mods.items():
                assert mod.parse_html(data, prepared[name], bool(kind), False, False, 100) == expected, (name, str(path), kind)
        extra.append({'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(data).hexdigest()})
    report = {'variants': args.names, 'generated_parse_cases': count, 'extra_filings': extra,
              'extra_configurations_per_filing': 2}
    save(OUT / 'extended_checks.json', report)
    print('PASS', len(extra), 'additional filings, default and SEC:10-K configuration', flush=True)


if __name__ == '__main__':
    main()
