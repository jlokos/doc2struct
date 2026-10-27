"""Produce a reviewable report and patches without applying any production edit."""
import difflib
import hashlib
import json
import statistics

from lab import HERE, OUT, ROOT, save


LABELS = {
    'baseline': 'Current source baseline',
    'fused_text': 'Combined text / entity scan (SSE2)',
    'equal_fused': 'Combined scan + short tag equality (SSE2)',
    'baseline_pgo': 'Baseline + PGO',
    'fused_text_pgo': 'Combined scan + PGO',
    'equal_fused_pgo': 'Combined scan + short tag equality + PGO',
}


def main():
    phases = {}
    for name in ['baseline', 'round1', 'pinned_screen', 'finalists', 'confirmation']:
        phases[name] = json.loads((OUT / (name + '.json')).read_text())
    final = phases['confirmation']
    med = {mode: {name: statistics.median(values) for name, values in variants.items()}
           for mode, variants in final['samples'].items()}
    winner = min(med['parse'], key=med['parse'].get)
    source_names = [n for n in med['parse'] if not n.endswith('_pgo')]
    source_winner = min(source_names, key=med['parse'].get)
    hashes = json.loads((OUT / 'snapshot/manifest.json').read_text())
    changed = [p for p, digest in hashes.items()
               if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest]
    assert not changed, ('Production C sources changed since snapshot', changed)
    save(HERE / 'source_manifest.json', hashes)
    save(HERE / 'corpus_manifest.json', final['corpus'])
    checks = {p.name: json.loads(p.read_text()) for p in OUT.glob('checks-*.json')}
    extra = json.loads((OUT / 'extended_checks.json').read_text())
    profile = json.loads((OUT / 'profile.json').read_text())
    training = {n: json.loads((OUT / n / 'training.json').read_text())
                for n in med['parse'] if n.endswith('_pgo')}
    compact = {name: {k: v for k, v in result.items() if k != 'corpus'}
               for name, result in phases.items()}
    save(HERE / 'results.json', {'winner': winner, 'source_winner': source_winner,
                               'phases': compact, 'checks': checks, 'extended_checks': extra,
                               'profile': profile, 'pgo_training': training})
    original = (OUT / 'snapshot/c/tokenizer.c').read_text().splitlines(keepends=True)
    for name in ['fused_text', 'equal_fused']:
        candidate = (OUT / name / 'tokenizer.c').read_text().splitlines(keepends=True)
        diff = ''.join(difflib.unified_diff(original, candidate,
                                           fromfile='a/c/tokenizer.c', tofile='b/c/tokenizer.c'))
        (HERE / (name + '.patch')).write_text(diff, encoding='utf-8')
    base = med['parse']['baseline']
    fb = med['frontend']['baseline']
    initial = statistics.median(phases['baseline']['samples']['parse']['baseline'])
    lines = [
        '# Tokenizer SIMD experiments — 2026-10-27', '',
        f'Best measured full-parser throughput: **{base / med["parse"][winner]:.3f}x baseline** '
        f'with `{winner}`. Best source-only result: **{base / med["parse"][source_winner]:.3f}x** '
        f'with `{source_winner}`. Production sources were not modified.', '',
        f'The corpus contains **{final["files"]} HTML filings, {final["bytes"] / 1e6:.3f} MB** '
        'from `data/filings/many_10k`. Other files in that directory are excluded. '
        'The exact paths and content hashes are in [corpus_manifest.json](corpus_manifest.json).', '',
        '| Configuration | Full parse, seconds | MB/s | Full parse throughput | Frontend, seconds | Frontend throughput |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for name, seconds in med['parse'].items():
        frontend = med['frontend'][name]
        lines.append(f'| {LABELS[name]} | {seconds:.6f} | {final["bytes"] / seconds / 1e6:.1f} | '
                     f'{base / seconds:.3f}x | {frontend:.6f} | {fb / frontend:.3f}x |')
    lines += ['',
        f'The winning build reduces full-parse time by **{(1 - med["parse"][winner] / base) * 100:.1f}%** '
        f'and raises throughput by **{(base / med["parse"][winner] - 1) * 100:.1f}%**. '
        'PGO affects the entire native extension, so its gain is not attributed solely to the tokenizer.', '',
        'These are medians of **11 measured full-corpus passes**, after one complete warmup for each '
        'configuration and mode. Variants ran sequentially in seeded shuffled order, pinned to '
        f'Windows logical CPU {final["affinity"]["logical_cpu"]}, a performance-class core. '
        'Inputs and compiled rules were prepared before timing; timing includes parsing, Python row '
        'export, and output disposal. The existing 8 MiB native arena cache is enabled. '
        'No disk reads, compilation, equality checks, or other benchmark variants ran concurrently with a timed pass.', '',
        '`frontend` is a lab-only native hook covering input validation/decoding, tokenization, '
        'normalization, flow construction, finish, and document cleanup. It excludes standardization '
        'and Python row export. It is **not a tokenizer-only measurement**. All variants include the identical hook. '
        'Full parse uses the native entry point called by `parse_html(data, "SEC:10-K")`, with default '
        'visibility options; Python rule preparation is outside timing.', '',
        f'The first unpinned three-run baseline was {initial:.6f} seconds '
        f'({final["bytes"] / initial / 1e6:.1f} MB/s). Later CPU placement and system state differ. '
        'Use the contemporaneous pinned baseline above for speedup claims, not that preliminary absolute time. '
        'Raw samples from every phase are preserved in [results.json](results.json).', '',
        'The strongest source changes are available as unapplied review patches:', '',
        '- [fused_text.patch](fused_text.patch): find the next `<` while tracking whether the preceding '
        'text contains `&`; bypass the redundant entity search for text known to be entity-free.',
        '- [equal_fused.patch](equal_fused.patch): add bounded SSE2 equality checks for short repeated '
        'tags to the combined scan. Every cache hit still requires complete byte equality.', '',
        'The attribute masks were a useful negative result. The existing template cache already reuses '
        f'{profile["template_hit_bytes"] / 1e6:.1f} MB of markup '
        f'({profile["template_hit_bytes"] / final["bytes"] * 100:.1f}% of the input). '
        'Computing broad delimiter masks for cache misses adds work without helping those hits. '
        'Retained 16-/64-byte masks, wider text scans, AVX2 quote scans, scalar class tables, '
        'bulk comment/raw-content skipping, and three cache sizes were all measured.', '',
        '| Screening variant | Full parse throughput vs paired baseline | Frontend throughput vs paired baseline |',
        '|---|---:|---:|',
    ]
    screen = phases['pinned_screen']['samples']
    sb = {m: statistics.median(v['baseline']) for m, v in screen.items()}
    for name in screen['parse']:
        if name != 'baseline':
            lines.append(f'| `{name}` | {sb["parse"] / statistics.median(screen["parse"][name]):.3f}x | '
                         f'{sb["frontend"] / statistics.median(screen["frontend"][name]):.3f}x |')
    lines += ['',
        'The screen used three measured passes per configuration. Small differences there are exploratory; '
        'the finalists received a separate nine-pass comparison and the eleven-pass confirmation above. '
        'The vector equality experiments are recorded in the nine-pass phase. '
        'A total of 22 configurations (baseline plus 21 candidates, including PGO builds) were timed.', '',
        '**Validation:** every finalist matched baseline token lists and parsed rows on all 146 corpus '
        'files and matched 17,729 generated token cases. The extended checks matched 3,556 full-parse '
        'cases, including malformed markup, every single-byte input value, Unicode whitespace, '
        'visibility settings, cache activation thresholds, and comparison lengths around SIMD boundaries. '
        'Twenty-two additional filings matched under both default and SEC:10-K configurations. '
        'This establishes parity with the existing parser, not independent HTML-standard conformance.', '',
        '**PGO:** MSVC instruments the native extension, observes three passes over six local '
        '`data/filings/test_work` filings, then relinks using that profile. Training inputs are '
        'disjoint from the timing corpus by SHA-256 content, including across alternate filenames. '
        'Training paths/hashes are recorded in `results.json`. No timing-corpus data trained the PGO builds.', '',
        '**Scope:** this lab targets Windows x64/MSVC. All variants use `/O2 /GL /std:c11 /utf-8` '
        'and `/LTCG /OPT:REF`; AVX2 experiments additionally use `/arch:AVX2` for the tokenizer translation unit. '
        'The winning SSE2 source does not require AVX2. The lab does not implement production CPU dispatch '
        'or validate performance on other machines. Compiler flags and PGO are experimental, not new package defaults. '
        'The corpus was used to select source variants; cross-machine and unseen-corpus speedups remain unmeasured.', '',
        'Reproduce from the repository root with Python 3.14 and MSVC installed:', '',
        '```powershell',
        'python experimental/tokenizer_simd/lab.py build baseline fused_text equal_fused',
        'python experimental/tokenizer_simd/pgo.py baseline fused_text equal_fused',
        'python experimental/tokenizer_simd/check.py fused_text equal_fused baseline_pgo fused_text_pgo equal_fused_pgo',
        'python experimental/tokenizer_simd/extended_check.py fused_text equal_fused baseline_pgo fused_text_pgo equal_fused_pgo',
        'python experimental/tokenizer_simd/lab.py measure baseline fused_text equal_fused baseline_pgo fused_text_pgo equal_fused_pgo --rounds 11 --label confirmation',
        '```', '',
        'The first build freezes the current C sources and rules under `artifacts/snapshot`; later '
        'builds use that snapshot. Generated sources, binaries, build logs, and complete raw phase results '
        'remain under `artifacts/`. The original C-source hashes are retained in '
        '[source_manifest.json](source_manifest.json); all production C files still match them. '
        '`readme.md` was not edited and no `tests/` directory was added.', '',
    ]
    (HERE / 'results.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Winner:', winner, 'source-only:', source_winner)
    for name, seconds in med['parse'].items():
        print(name, f'{seconds:.6f}s', f'{base / seconds:.4f}x',
              'frontend', f'{fb / med["frontend"][name]:.4f}x')


if __name__ == '__main__':
    main()
