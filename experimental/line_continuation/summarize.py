"""Publish compact results and source-backed review observations from lab runs."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import doc2struct as ds

import corpus
import native
from lab import save
from variants import rules_variant


def main():
    review_file = corpus.HERE/'reviewed_changes.json'
    prior = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else []
    annotations = {(r['document'], r['change'], r['text']): r['review'] for r in prior}
    runs = {}
    for label in ['development_final', 'holdout_final']:
        folder = corpus.OUT / label
        runs[label] = dict(summary=json.loads((folder/'summary.json').read_text(encoding='utf-8')),
                           metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8')),
                           ledger=json.loads((folder/'ledger.json').read_text(encoding='utf-8')))
    anchor_doc = next(d for d in runs['development_final']['ledger'] if d['id'].startswith('anthropic_s1/'))
    anchor_folder = corpus.OUT / 'development_final' / anchor_doc['sha256'][:12]
    anchor = json.loads((anchor_folder/'measured_anchor_review.json').read_text(encoding='utf-8'))
    boundaries = json.loads((corpus.OUT/'boundary_scenarios.json').read_text(encoding='utf-8'))
    original = json.loads((anchor_folder/'baseline_rows.json').read_text(encoding='utf-8'))
    measured = json.loads((anchor_folder/'measured_rows.json').read_text(encoding='utf-8'))
    ds.visualize_standardized_text(original, str(anchor_folder/'baseline.html'), open_browser=False)
    ds.visualize_standardized_text(measured, str(anchor_folder/'measured.html'), open_browser=False)

    module = native.load()
    samples = json.loads((corpus.HERE/'sample.json').read_text(encoding='utf-8'))
    reviewed = []
    for label, run in runs.items():
        folder = corpus.OUT / label
        for document in run['ledger']:
            pred = document['variants']['prediction_v2']
            if pred.get('removed_title_count'):
                changes = json.loads((folder/document['sha256'][:12]/'prediction_v2_changes.json').read_text(encoding='utf-8'))
                for title in changes['removed_titles']:
                    reviewed.append(dict(document=document['id'], change='prose demotion',
                                         text=title['text'], review=annotations.get(
                                             (document['id'], 'prose demotion', title['text']), 'Pending manual review.')))
            notes = document['variants']['guarded_notes']['metrics']['notes']
            if notes != document['variants']['baseline']['metrics']['notes']:
                record = next(r for r in samples if r['id'] == document['id'])
                content = corpus.read(record)
                definition = ds.load_rules(document['rules']).to_dict() if document['rules'] else ds.Rules().to_dict()
                method = module.parse_pdf if record['format'] == '.pdf' else module.parse_html
                before = method(content, module.prepare_rules(definition), True)
                after = method(content, module.prepare_rules(rules_variant(definition, 'guarded_notes')), True)
                note_set = lambda rows: {(n[0], n[1]) for r in rows for n in r.get('footnotes') or []}
                for marker, text in sorted(note_set(before)-note_set(after)):
                    reviewed.append(dict(document=document['id'], change='removed false footnote',
                                         marker=marker, text=text, review=annotations.get(
                                             (document['id'], 'removed false footnote', text), 'Pending manual review.')))

    results = dict(
        sample_documents=len(samples), sample_formats=dict(Counter(r['format'] for r in samples)),
        sample_split=dict(Counter(r['split'] for r in samples)),
        anchor=anchor, anchor_metrics=anchor_doc['variants'],
        native_parity=json.loads((corpus.OUT/'native_parity.json').read_text(encoding='utf-8')),
        boundary_scenarios=boundaries,
        runs={k: dict(summary=v['summary'], metadata=v['metadata']) for k, v in runs.items()},
        reviewed_change_counts=dict(Counter(r['change'] for r in reviewed)),
        limitations=[
            'Only the Anthropic document exercised positioned reflow in this real-file sample.',
            'The measured heading extension fails the ambiguous adjacent large headings scenario.',
            'HTML geometry sidecar is deliberately limited to absolute divs within known relative page containers.',
            'Nested transforms, inherited positioning contexts, cross-page continuation and PDF paragraph reconstruction are unsupported.',
            'Diagnostic counts and targeted anchor checks are not corpus accuracy estimates.',
            'Python reconstruction includes two normalization passes and is not a production performance implementation.',
            'Source snapshots and large outputs are ignored artifacts; compact results and the selection manifest are retained.'
        ],
        production_files_changed=False,
    )
    save(corpus.HERE/'results.json', results)
    save(corpus.HERE/'reviewed_changes.json', reviewed)
    print('Reviewed changes', results['reviewed_change_counts'])
    print('Anchor preview', anchor_folder/'measured.html')
    print('Results', corpus.HERE/'results.json')


if __name__ == '__main__':
    main()
