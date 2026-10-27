"""Reproducible, small-sample structure experiments.

python experimental/line_continuation/lab.py inventory
python experimental/line_continuation/lab.py build
python experimental/line_continuation/lab.py sample
python experimental/line_continuation/lab.py run --split development
python experimental/line_continuation/lab.py run --split holdout

Artifacts contain a compact metric ledger and bounded change examples, not a
copy of the corpus. Metrics are diagnostic proxies, not accuracy measurements.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import platform
import sys
from time import perf_counter

import doc2struct as ds

import corpus
import native
from reflow import normalize_with_facts, reconstruct
from variants import rules_variant


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sample():
    records = corpus.records()
    selected = {}
    strata = ['anthropic_s1', 'many_10k', 'msft_10k', 'msft_8k', '10k_2025', '8k_2020',
              'sec_html_rules/S-1', 'sec_html_rules/424B4', 'sec_html_rules/20-F',
              'sec_html_rules/N-CSR', 'sec_html_rules/S-3', 'sec_html_rules/10-Q',
              'structural_review', '10k_pdf_sample']
    for stratum in strata:
        for split in ['development', 'holdout']:
            candidates = [r for r in records if r['stratum'] == stratum and r['split'] == split]
            candidates.sort(key=lambda r: corpus.rank(r['id']))
            if candidates:
                value = next((r for r in candidates if r['size'] > 200000), candidates[0]) if stratum == '10k_pdf_sample' else candidates[0]
                selected[value['id']] = value
    # A second non-Anthropic S-1 to check issuer generalization even when this
    # small stratum happens to contain no hash-assigned holdout.
    extras = sorted([r for r in records if r['stratum'] == 'sec_html_rules/S-1'],
                    key=lambda r: corpus.rank(r['id']))
    if len(extras) > 1:
        selected[extras[1]['id']] = extras[1]
    result = list(selected.values())
    save(corpus.HERE / 'sample.json', result)
    return result


def row_text(row):
    return row.get('text') or ''


def metrics(rows):
    counts = Counter(row['type'] for row in rows)
    titles = [r for r in rows if r['type'] == 'title']
    lists = [r for r in rows if r['type'] == 'list']
    tables = [r for r in rows if r['type'] == 'table']
    notes = [note for r in tables for note in (r.get('footnotes') or [])]
    return dict(rows=len(rows), **dict(counts),
                explicit_sections=sum(bool(r.get('standardized_title')) and r.get('class') != 'introduction'
                                      for r in titles),
                predicted_titles=sum(r.get('class') == 'predicted header' for r in titles),
                long_predicted_titles=sum(r.get('class') == 'predicted header' and len(row_text(r).split()) >= 28
                                          for r in titles),
                page_titles=sum(bool(re.fullmatch(r'F-\d+', row_text(r))) for r in titles),
                list_items=sum(len(r.get('matrix') or []) for r in lists),
                list_followed_by_lowercase=sum(r['type'] == 'list' and rows[i+1]['type'] in {'text', 'textsmall'}
                                               and bool(re.match('[a-z]', row_text(rows[i+1])))
                                               for i, r in enumerate(rows[:-1])),
                notes=len(notes),
                # Footnotes are [marker, text], not dictionaries.
                note_characters=sum(len(str(note)) for note in notes))


def outline(rows):
    return [dict(text=r['text'], klass=r.get('class'), level=r['level']) for r in rows
            if r['type'] == 'title' and r.get('class') != 'introduction']


def difference(before, after):
    a, b = outline(before), outline(after)
    key = lambda x: (x['text'], x['klass'])
    ca, cb = Counter(map(key, a)), Counter(map(key, b))
    removed, added = ca-cb, cb-ca
    return dict(removed_titles=[r for r in a if key(r) in removed][:35],
                added_titles=[r for r in b if key(r) in added][:35],
                removed_title_count=sum(removed.values()), added_title_count=sum(added.values()))


def run(args):
    selected = json.loads((corpus.HERE / 'sample.json').read_text(encoding='utf-8'))
    if args.split:
        selected = [r for r in selected if r['split'] == args.split]
    if args.only:
        selected = [r for r in selected if args.only in r['id']]
    modules = {'baseline': native.load(), 'prediction': native.load('prediction'),
               'prediction_v2': native.load('prediction_v2')}
    destination = corpus.OUT / args.label
    destination.mkdir(parents=True, exist_ok=True)
    save(destination / 'metadata.json', dict(
        python=sys.version, platform=platform.platform(), variants=args.variants,
        sample_sha256=hashlib.sha256((corpus.HERE/'sample.json').read_bytes()).hexdigest(),
        scripts={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in corpus.HERE.glob('*.py')},
        binaries={name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                  for name, module in modules.items()},
        timings='Single pass, includes Python prototype and output construction; excludes corpus I/O and rule compilation. Not a native performance benchmark.',
        limitations='Diagnostic counts are not accuracy. HTML-only reconstruction requires a known page and absolute div positions. PDF variants do not reconstruct paragraphs.'
    ))
    ledger = []
    for index, record in enumerate(selected):
        content = corpus.read(record)
        rules_name = corpus.rules_name(record, content)
        definition = ds.load_rules(rules_name).to_dict() if rules_name else ds.Rules().to_dict()
        digest = hashlib.sha256(content).hexdigest()
        result = dict(id=record['id'], sha256=digest, size=len(content), rules=rules_name,
                      split=record['split'], variants={})
        baseline = None
        baseline_matrix = None
        for variant in args.variants:
            artifacts = []
            module = (modules['prediction_v2'] if variant in {'prediction_v2', 'candidate', 'conservative_v2', 'measured'}
                      else modules['prediction'] if variant in {'prediction', 'combined'} else modules['baseline'])
            definition_variant = rules_variant(definition, variant)
            if variant in {'candidate', 'measured'}:
                definition_variant = rules_variant(rules_variant(definition_variant, 'guarded_notes'), 'pages')
            rules = module.prepare_rules(definition_variant)
            start = perf_counter()
            if record['format'] == '.pdf':
                if variant in {'geometry', 'conservative', 'combined', 'candidate', 'conservative_v2', 'measured'}:
                    continue  # HTML sidecar cannot reconstruct PDF geometry.
                rows = module.parse_pdf(content, rules, True)
            elif variant in {'geometry', 'conservative', 'combined', 'candidate', 'conservative_v2', 'measured'}:
                tokens = modules['baseline'].tokenize(content)
                runs, sidecar, alignment_error = normalize_with_facts(modules['baseline'], tokens)
                transformed, events, positioned = reconstruct(runs, sidecar,
                                            'geometry' if variant in {'geometry', 'candidate'} else
                                            'measured' if variant == 'measured' else 'conservative')
                rows = module.standardize(transformed, rules, True)
                result['variants'][variant] = dict(joins=len(events), eligible_blocks=positioned,
                                                  alignment_error=alignment_error)
                # Save a deterministic spread, plus the beginning, for review.
                chosen = events[:15] + sorted(events[15:], key=lambda e: corpus.rank(str(e)))[:35]
                artifacts.append((destination / digest[:12] / (variant + '_joins.json'), chosen))
                if record['group'] == 'anthropic_s1':
                    # A complete trace for the anchor case is still small.
                    artifacts.append((destination / digest[:12] / (variant + '_all_joins.json'), events))
            else:
                rows = module.parse_html(content, rules, True, False, False, 100)
            elapsed = perf_counter()-start
            for path, value in artifacts:
                save(path, value)
            result['variants'].setdefault(variant, {}).update(seconds=elapsed, metrics=metrics(rows))
            if variant == 'baseline':
                baseline = rows
                baseline_matrix = [r['matrix'] for r in rows if r['type'] == 'table']
            elif baseline is not None:
                changes = difference(baseline, rows)
                result['variants'][variant].update({k: v for k, v in changes.items() if k.endswith('_count')})
                result['variants'][variant]['output_equal'] = rows == baseline
                result['variants'][variant]['table_matrices_equal'] = baseline_matrix == [
                    r['matrix'] for r in rows if r['type'] == 'table']
                save(destination / digest[:12] / (variant + '_changes.json'), changes)
            if record['group'] == 'anthropic_s1' and variant in {'baseline', 'combined', 'conservative', 'candidate', 'conservative_v2', 'measured'}:
                save(destination / digest[:12] / (variant + '_rows.json'), rows)
            del rows
        ledger.append(result)
        save(destination / 'ledger.json', ledger)
        print(f"{index+1}/{len(selected)} {record['id']} " +
              str({k: v['metrics']['rows'] for k, v in result['variants'].items()}), flush=True)
    save(destination / 'summary.json', summarize(ledger))


def summarize(ledger):
    result = {}
    variants = sorted({v for r in ledger for v in r['variants']})
    for variant in variants:
        values = [r['variants'][variant] for r in ledger if variant in r['variants']]
        totals = Counter()
        baseline_totals = Counter()
        for v in values:
            totals.update(v['metrics'])
        for document in ledger:
            if variant in document['variants']:
                baseline_totals.update(document['variants']['baseline']['metrics'])
        result[variant] = dict(documents=len(values), totals=dict(totals),
                               paired_baseline=dict(baseline_totals),
                               joins=sum(v.get('joins', 0) for v in values),
                               matrices_changed=sum(not v.get('table_matrices_equal', True) for v in values),
                               removed_titles=sum(v.get('removed_title_count', 0) for v in values),
                               added_titles=sum(v.get('added_title_count', 0) for v in values))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'build', 'sample', 'run'])
    parser.add_argument('--split', choices=['development', 'holdout'])
    parser.add_argument('--only')
    parser.add_argument('--label', default='initial')
    parser.add_argument('--variants', nargs='+', default=['baseline', 'pages', 'bounded_headers',
                        'strict_notes', 'style_required', 'prediction', 'geometry', 'conservative', 'combined'])
    args = parser.parse_args()
    if args.action == 'inventory':
        print(corpus.inventory())
    elif args.action == 'build':
        print(native.build())
        print(native.build('prediction_v2', conservative=True))
    elif args.action == 'sample':
        result = sample()
        print(Counter(r['split'] for r in result))
        print(Counter(r['format'] for r in result))
    else:
        run(args)


if __name__ == '__main__':
    main()
