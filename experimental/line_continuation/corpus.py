"""Stable corpus inventory and bounded, stratified selections. No extraction.

Archive members retain offsets so subsequent experiments can seek directly to
one filing. Inputs are never copied into the experiment output directory.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'data/filings'
OUT = HERE / 'artifacts'
MANIFEST = OUT / 'inventory.jsonl'


def rank(value):
    return hashlib.sha256(value.encode()).hexdigest()


def inventory():
    OUT.mkdir(parents=True, exist_ok=True)
    counts = defaultdict(int)
    with MANIFEST.open('w', encoding='utf-8') as target:
        for path in sorted(DATA.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(DATA).as_posix()
            group = relative.split('/')[0]
            records = []
            if path.suffix.lower() == '.tar':
                with tarfile.open(path, 'r:') as archive:
                    for member in archive:
                        if member.isfile() and Path(member.name).suffix.lower() in {'.htm', '.html', '.pdf'}:
                            records.append(dict(id=relative + '::' + member.name,
                                                path=relative, member=member.name,
                                                offset=member.offset_data, size=member.size,
                                                group=group, format=Path(member.name).suffix.lower()))
            elif path.suffix.lower() in {'.htm', '.html', '.pdf'}:
                records.append(dict(id=relative, path=relative, member=None, offset=0,
                                    size=path.stat().st_size, group=group, format=path.suffix.lower()))
            for record in records:
                record['stratum'] = stratum(record)
                record['split'] = 'holdout' if int(rank(record['id'])[:8], 16) % 5 == 0 else 'development'
                target.write(json.dumps(record) + '\n')
                counts[group] += 1
            if records and path.suffix.lower() == '.tar':
                print(relative, len(records), flush=True)
    return dict(counts)


def stratum(record):
    parts = record['id'].split('/')
    if record['group'] == 'sec_html_rules' and len(parts) > 1:
        return parts[0] + '/' + parts[1].rsplit('_', 1)[0]
    return record['group']


def records():
    with MANIFEST.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def select(per_stratum=2, split=None, limit=None, include_pdf=False, all_files=False):
    buckets = defaultdict(list)
    for item in records():
        if item['format'] == '.pdf' and not include_pdf:
            continue
        if split and item['split'] != split:
            continue
        buckets[(item['stratum'], item['format'])].append(item)
    selected = []
    for bucket in sorted(buckets):
        values = sorted(buckets[bucket], key=lambda v: rank(v['id']))
        selected.extend(values if all_files else values[:per_stratum])
    # A cap takes a deterministic hash sample, not an alphabetical prefix.
    if limit and len(selected) > limit:
        selected = sorted(selected, key=lambda v: rank(v['id']))[:limit]
    return sorted(selected, key=lambda v: v['id'])


def read(record):
    path = DATA / record['path']
    if record['member']:
        with path.open('rb') as stream:
            stream.seek(record['offset'])
            data = stream.read(record['size'])
    else:
        data = path.read_bytes()
    if len(data) != record['size']:
        raise ValueError('Input changed since inventory: ' + record['id'])
    return data


def rules_name(record, content=None):
    import doc2struct as ds
    group = record['group']
    if group == 'sec_html_rules':
        form = record['stratum'].split('/', 1)[1].replace('_', '/')
    elif '10k' in group:
        form = '10-K'
    elif '8k' in group:
        form = '8-K'
    elif group == 'anthropic_s1':
        form = 'S-1'
    else:
        # SEC complete-submission containers retain a TYPE declaration. Filename
        # guesses are intentionally avoided for mixed-form archives and exhibits.
        match = re.search(rb'<TYPE>\s*([^\r\n<]+)', (content or b'')[:10000], re.I)
        form = match.group(1).decode('ascii', errors='ignore').strip() if match else None
    known = set(ds.list_document_types('SEC'))
    return 'SEC:' + form.upper() if form and form.upper() in known else None
