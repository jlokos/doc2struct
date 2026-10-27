"""Boundary scenarios and reviewable anchor observations for the reflow lab."""
import argparse
import json
import re

import corpus
import native
from reflow import normalize_with_facts, reconstruct


def parity():
    import doc2struct as ds
    module = native.load('prediction_v2')
    records = json.loads((corpus.HERE/'sample.json').read_text(encoding='utf-8'))
    results = []
    for record in records:
        content = corpus.read(record)
        name = corpus.rules_name(record, content)
        definition = ds.load_rules(name).to_dict() if name else ds.Rules().to_dict()
        rules = module.prepare_rules(definition)
        if record['format'] == '.pdf':
            direct = module.parse_pdf(content, rules, True)
            staged = module.standardize(module.pdf_instructions(content), rules, True)
        else:
            direct = module.parse_html(content, rules, True)
            staged = module.standardize(module.normalize(module.tokenize(content)), rules, True)
        if direct != staged:
            raise AssertionError('Direct/staged mismatch: ' + record['id'])
        results.append(dict(document=record['id'], passed=True))
    report = dict(variant='prediction_v2', passed=len(results), total=len(results), documents=results)
    (corpus.OUT/'native_parity.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Native prediction direct/staged parity:', len(results), 'passed')
    return report


def page(content):
    return '<div style="position:relative;width:600pt;height:800pt">' + content + '</div>'


def line(text, y, x=72, size=10, flags='', width=400, tag='div'):
    return (f'<div style="position:absolute;top:{y}pt">'
            f'<{tag} style="font-size:{size}pt;left:{x}pt;position:absolute;width:{width}pt;{flags}">'
            f'{text}</{tag}></div>')


def scenarios():
    base = native.load()
    filler = line('Ordinary body text establishes the predominant document font. ' * 12, 200)
    cases = [
        ('wrapped body', page(line('Our customers rely on the', 20) + line('services we provide.', 32)), 1),
        ('paragraph gap', page(line('Our customers rely on the', 20) + line('services we provide.', 47)), 0),
        ('independent headings', page(line('Revenue', 20, flags='font-weight:bold') +
                                      line('Expenses', 32, flags='font-weight:bold')), 0),
        ('new bullet', page(line('•The first item describes our', 20) + line('•The second item.', 32)), 0),
        ('hanging bullet', page(line('•The first item describes our', 20) +
                                line('services to customers.', 32, x=90)), 1),
        ('roman item', page(line('(iii) The previous item describes our', 20) +
                            line('(iv) The next item.', 32)), 0),
        ('different column', page(line('Our customers rely on the', 20) +
                                  line('services we provide.', 32, x=300)), 0),
        ('different font', page(line('Our customers rely on the', 20) +
                                line('services we provide.', 32, size=8)), 0),
        ('page break', page(line('Our customers rely on the', 20)) +
                       page(line('services we provide.', 32)), 0),
        ('table boundary', page(line('Our customers rely on the', 20) +
                                 '<table><tr><td>Year</td><td>2025</td></tr></table>' +
                                 line('services we provide.', 32)), 0),
        ('separator', page(line('_______________', 20) + line('Notes to the statements.', 32)), 0),
        ('explicit paragraphs', page(line('Our customers rely on the', 20, tag='p') +
                                     line('services we provide.', 32, tag='p')), 0),
        ('large multiline heading', page(line('Certain Relationships and Related Person', 20, size=20,
                                             flags='font-weight:bold') +
                                          line('Transactions', 44, size=20, flags='font-weight:bold') + filler), 1),
        ('ambiguous adjacent large headings', page(line('Review of Annual Results', 20, size=20,
                                                       flags='font-weight:bold') +
                                                    line('Next Steps', 44, size=20, flags='font-weight:bold') + filler), 0),
        ('ordinary HTML paragraphs', '<p>Our customers rely on the</p><p>services we provide.</p>', 0),
    ]
    report = []
    for name, html, expected in cases:
        tokens = base.tokenize(('<html><body>'+html+'</body></html>').encode())
        runs, sidecar, error = normalize_with_facts(base, tokens)
        for mode in ['geometry', 'conservative', 'measured']:
            result, events, eligible = reconstruct(runs, sidecar, mode)
            report.append(dict(case=name, mode=mode, expected=expected, joins=len(events),
                               pass_=len(events) == expected and error is None,
                               alignment_error=error))
    output = corpus.OUT / 'boundary_scenarios.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for mode in ['geometry', 'conservative', 'measured']:
        failed = [r['case'] for r in report if r['mode'] == mode and not r['pass_']]
        print(mode, 'failures:', failed)
    return report


def anchor(label, variant):
    folder = corpus.OUT / label
    ledger = json.loads((folder/'ledger.json').read_text(encoding='utf-8'))
    document = next(r for r in ledger if r['id'].startswith('anthropic_s1/'))
    location = folder / document['sha256'][:12]
    rows = json.loads((location/(variant+'_rows.json')).read_text(encoding='utf-8'))
    original = json.loads((location/'baseline_rows.json').read_text(encoding='utf-8'))
    titles = [r for r in rows if r['type'] == 'title']
    text = lambda r: r['text'] or ''
    original_capitalization = original[5635]
    table = next(r for r in rows if r['type'] == 'table' and
                 r['matrix'] == original_capitalization['matrix'])
    notes = dict(table['footnotes'] or [])
    first_table = next(r for r in rows if r['type'] == 'table')
    items = [i[1] for r in rows if r['type'] == 'list' for i in r['matrix']]
    checks = {
        'summary introduction is prose': any(r['type'] == 'text' and text(r).startswith('This summary highlights') for r in rows),
        'risk introduction is prose': any(r['type'] == 'text' and text(r).startswith('Investing in our Class A common stock involves') for r in rows),
        'business fragment absent from headings': not any(text(r).lower() == 'business.' for r in titles),
        'MD&A heading complete': any(text(r).startswith('Management') and 'Discussion and Analysis of Financial Condition and Results of Operations' in text(r) for r in titles),
        'related person heading complete': any(text(r) == 'Certain Relationships and Related Person Transactions' for r in titles),
        'first bullet complete': any('cognitive capabilities matching' in t and 'scientific disciplines;' in t for t in items),
        'address and phone not table footnotes': not any(n[0] in {'548', '(415)'} for n in first_table.get('footnotes') or []),
        'capitalization table title correct': text(table) == 'Capitalization',
        'capitalization note continuation complete': 'initial public offering price remains the same' in notes.get('(2)', '') and notes.get('(2)', '').endswith('us.'),
        'financial page labels not headings': not any(re.fullmatch(r'F-\d+', text(r)) for r in titles),
        'table cell matrices preserved': [r['matrix'] for r in original if r['type']=='table'] == [r['matrix'] for r in rows if r['type']=='table'],
    }
    result = dict(variant=variant, checks=checks, passed=sum(checks.values()), total=len(checks))
    (location/(variant+'_anchor_review.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['scenarios', 'anchor', 'parity'])
    parser.add_argument('--label', default='development_final')
    parser.add_argument('--variant', default='measured')
    args = parser.parse_args()
    if args.action == 'scenarios':
        scenarios()
    elif args.action == 'parity':
        parity()
    else:
        anchor(args.label, args.variant)
