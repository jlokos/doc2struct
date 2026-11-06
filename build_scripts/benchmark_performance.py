"""Compare two installed builds in isolated processes, including Python export.

Example: python build_scripts/benchmark_performance.py --reference /tmp/before \
    --candidate /tmp/after --corpus data/filings --output build/performance.json
Package roots must contain doc2struct/ with its matching native extension.
Synthetic stress cases expose scaling limits; they are not typical SEC filings.
Older builds can require several GB for these cases. Use --no-synthetic with a
corpus to measure ordinary documents; --paired reduces interpreter/scheduling
variation when checking small timing differences and omits per-build peak RSS.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

DEFAULT_CASES = ('ordinary_html', 'deep_html', 'wide_table', 'fragmented_instructions')
EXTRA_CASES = ('tiny_html', 'tiny_instructions', 'unicode_html', 'metadata_html',
               'plain_text', 'partial_sgml', 'pdf_text', 'varied_styles',
               'normalize_tokens', 'tiny_normalize', 'tiny_tokenize', 'tokenize_html', 'tokenize_nested')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':')).encode()).hexdigest()


def batch_size(operation, minimum):
    operation()
    count, batch, elapsed = 0, 1, 0
    start = time.process_time()
    while elapsed < 0.01 and count < 100000:
        batch = min(batch, 100000 - count)
        for _ in range(batch):
            operation()
        count += batch
        batch *= 2
        elapsed = time.process_time() - start
    return max(1, min(100000, math.ceil(minimum * count / max(elapsed, 1e-9))))


def isolated_call_site(function):
    # A/B closures must not compete for one adaptive CALL/LOAD_ATTR cache.
    function.__code__ = function.__code__.replace()
    return function


def batch_runner(operation, iterations):
    def run():
        for iteration in range(iterations):
            result = operation()
            if iteration + 1 < iterations:
                del result
        return result
    return isolated_call_site(run)


def workload(d, case, filename):
    rules = 'SEC:10-K'
    if filename:
        content = Path(filename).read_bytes()
    elif case in ('tiny_html', 'tiny_instructions', 'tiny_normalize'):
        content = b'<p>ordinary content.</p>'
    elif case == 'tiny_tokenize':
        content = b'<div>ordinary content.</div>'
    elif case in ('normalize_tokens', 'tokenize_html'):
        content = b'<div><span style="font-size:12px">ordinary text.</span></div>' * 2000
    elif case == 'tokenize_nested':
        content = (b''.join(b'<custom%05d>' % i for i in range(2000)) + b'text' +
                   b''.join(b'</custom%05d>' % i for i in reversed(range(2000))))
    elif case == 'unicode_html':
        content = ''.join(f'<p>Paragraph {i}: ΣΟΣ café İstanbul K \u200b你好 🙂.</p>'
                          for i in range(1000)).encode()
    elif case == 'metadata_html':
        content = b''.join(b'<p><a href="/%d">paragraph %d </a><b>emphasis</b> tail.</p>' % (i, i)
                           for i in range(1000))
        rules = {'columns': [{'name': name, 'source': source, 'dtype': 'list', 'which': 'all'}
                            for name, source in [('links', 'href'), ('fonts', 'font_size'), ('styles', 'flags')]]}
    elif case == 'plain_text':
        content = b''.join(b'Ordinary paragraph %d with several words.\n\n' % i for i in range(1000))
    elif case == 'partial_sgml':
        content = b'<TEXT>\n' + b''.join(b'<B>Section %d</B>\nOrdinary prose for this section.\n\n' % i
                                         for i in range(500)) + b'</TEXT>'
    elif case == 'pdf_text':
        from smoke_release import basic_pdf
        content = basic_pdf()
    elif case == 'varied_styles':
        content = b'<p>' + b''.join(b'<span style="font-size:%dpx">fragment </span>' % i
                                    for i in range(1, 3001)) + b'</p>'
    elif case == 'deep_html':
        content = b'<div>' * 20000 + b'<p>Nested prose.</p>' + b'</div>' * 20000
    elif case == 'wide_table':
        content = (b'<table><tr>' + b'<td>123</td>' * 20000 + b'</tr><tr>' +
                   b'<td>234</td>' * 20000 + b'</tr></table>')
    elif case == 'fragmented_instructions':
        content = b'<p>' + (b'<span>' + b'Ordinary prose with a fragmented inline text representation. ' +
                              b'</span>') * 10000 + b'</p>'
    else:
        content = b''.join(b'<p>Ordinary paragraph number %d contains prose.</p>' % i
                           for i in range(1000))
    if case in ('fragmented_instructions', 'file_standardize', 'tiny_instructions'):
        instructions = d.convert_html_to_instructions(content, rules)
        operation = lambda: d.convert_instructions_to_standardized_text(instructions, rules)
    elif case == 'file_instructions':
        operation = lambda: d.convert_html_to_instructions(content, rules)
    elif case in ('normalize_tokens', 'tiny_normalize', 'file_normalize'):
        tokens = list(d.tokenize(content))
        operation = lambda: d.normalize(tokens, rules)
    elif case in ('tokenize_html', 'tokenize_nested', 'file_tokenize', 'tiny_tokenize'):
        operation = lambda: list(d.tokenize(content))
    elif case == 'plain_text':
        operation = lambda: d.parse_text(content, rules)
    elif case == 'partial_sgml':
        operation = lambda: d.parse_partialsgml(content, rules)
    elif case == 'pdf_text':
        operation = lambda: d.parse_pdf(content, rules)
    else:
        operation = lambda: d.parse_html(content, rules)
    return content, operation


def worker(args):
    sys.path.insert(0, str(Path(args.package_root).resolve()))
    import doc2struct as d
    content, operation = workload(d, args.worker, args.file)
    operation = isolated_call_site(operation)
    iterations = batch_size(operation, args.min_time)
    run = batch_runner(operation, iterations)
    run()
    durations, cpu_durations = [], []
    for _ in range(args.repeat):
        start = time.perf_counter()
        cpu_start = time.process_time()
        result = run()
        cpu_durations.append((time.process_time() - cpu_start) / iterations)
        durations.append((time.perf_counter() - start) / iterations)
        output_digest, rows = digest(result), len(result)
        del result
    peak = None
    if os.name != 'nt':
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != 'darwin':
            peak *= 1024
    print(json.dumps(dict(median_seconds=statistics.median(durations),
                          median_cpu_seconds=statistics.median(cpu_durations), iterations=iterations,
                          samples_seconds=durations, samples_cpu_seconds=cpu_durations,
                          peak_process_bytes=peak,
                          input_bytes=len(content), input_sha256=hashlib.sha256(content).hexdigest(),
                          output_sha256=output_digest, rows=rows)))


def paired_worker(args):
    # Shared interpreter/hash seed and alternating batches help distinguish
    # small parser differences from process-to-process variation. RSS cannot
    # be attributed to one build here; use isolated mode for memory results.
    operations, content_hashes = [], []
    for name, root in [('reference_doc2struct', args.reference), ('candidate_doc2struct', args.candidate)]:
        package = root.resolve() / 'doc2struct'
        spec = importlib.util.spec_from_file_location(name, package / '__init__.py',
                                                     submodule_search_locations=[str(package)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        content, operation = workload(module, args.worker, args.file)
        operation = isolated_call_site(operation)
        iterations = batch_size(operation, args.min_time)
        operations.append((operation, iterations))
        content_hashes.append(hashlib.sha256(content).hexdigest())
    sizes = [count for _, count in operations]
    if max(sizes) <= 4 * min(sizes):
        operations = [(operation, max(sizes)) for operation, _ in operations]
    runners = [batch_runner(operation, count) for operation, count in operations]
    for run in runners:
        run()
    samples = [dict(samples_seconds=[], samples_cpu_seconds=[]),
               dict(samples_seconds=[], samples_cpu_seconds=[])]
    for sample in range(args.repeat):
        for index in ((0, 1) if sample % 2 == 0 else (1, 0)):
            operation, iterations = operations[index]
            start, cpu_start = time.perf_counter(), time.process_time()
            result = runners[index]()
            entry = samples[index]
            entry['samples_cpu_seconds'].append((time.process_time() - cpu_start) / iterations)
            entry['samples_seconds'].append((time.perf_counter() - start) / iterations)
            entry.update(output_sha256=digest(result), rows=len(result))
            del result
    for index, entry in enumerate(samples):
        entry.update(median_seconds=statistics.median(entry['samples_seconds']),
                     median_cpu_seconds=statistics.median(entry['samples_cpu_seconds']),
                     iterations=operations[index][1], input_sha256=content_hashes[index], input_bytes=len(content),
                     peak_process_bytes=None)
    print(json.dumps(samples))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--corpus', nargs='*', type=Path, default=[])
    parser.add_argument('--token-stages', action='store_true',
                        help='Also measure tokenization and Python-token normalization for corpus files')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--paired', action='store_true',
                        help='Alternate both builds in one interpreter for timings; omit per-build RSS')
    parser.add_argument('--no-synthetic', action='store_true', help='Measure only the supplied corpus')
    parser.add_argument('--cases', nargs='+', choices=DEFAULT_CASES + EXTRA_CASES,
                        help='Select synthetic cases, including additional modality and boundary workloads')
    parser.add_argument('--repeat', type=int, default=7)
    parser.add_argument('--min-time', type=float, default=0.1,
                        help='Target CPU seconds per sample; batch short operations to reduce noise')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--package-root', help=argparse.SUPPRESS)
    parser.add_argument('--file', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeat < 1 or not math.isfinite(args.min_time) or args.min_time <= 0:
        parser.error('--repeat and --min-time must be positive')
    if args.worker:
        paired_worker(args) if args.paired else worker(args)
        return
    if not args.reference or not args.candidate:
        parser.error('--reference and --candidate are required')
    jobs = [(case, None) for case in (args.cases or DEFAULT_CASES)] if not args.no_synthetic else []
    for source in args.corpus:
        files = sorted(p for p in source.rglob('*') if p.suffix.lower() in ('.html', '.htm')) if source.is_dir() else [source]
        stages = ('file_parse', 'file_instructions', 'file_standardize')
        if args.token_stages:
            stages += ('file_tokenize', 'file_normalize')
        jobs.extend((case, str(path.resolve())) for path in files for case in stages)
    report = dict(python=sys.version, platform=sys.platform, reference=str(args.reference.resolve()),
                  candidate=str(args.candidate.resolve()), repeat=args.repeat,
                  minimum_sample_cpu_seconds=args.min_time, paired=args.paired, results=[])
    for case, filename in jobs:
        samples = [[], []]
        # Sequential children avoid competing for CPU or retaining the other
        # build's allocations. Imports and input construction are outside timing.
        # Alternate order between process pairs to reduce scheduling/frequency
        # drift on shared machines. Each child returns one warmed, batched sample.
        roots = (args.reference, args.candidate)
        if args.paired:
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', case, '--paired',
                       '--reference', str(args.reference.resolve()), '--candidate', str(args.candidate.resolve()),
                       '--repeat', str(args.repeat), '--min-time', str(args.min_time)]
            if filename:
                command += ['--file', filename]
            run = subprocess.run(command, check=True, capture_output=True, text=True, timeout=180,
                                 env=dict(os.environ, PYTHONHASHSEED='0'))
            samples = [[entry] for entry in json.loads(run.stdout)]
        for sample in range(0 if args.paired else args.repeat):
            for index in ((0, 1) if sample % 2 == 0 else (1, 0)):
                command = [sys.executable, str(Path(__file__).resolve()), '--worker', case,
                           '--package-root', str(roots[index].resolve()), '--repeat', '1',
                           '--min-time', str(args.min_time)]
                if filename:
                    command += ['--file', filename]
                run = subprocess.run(command, check=True, capture_output=True, text=True, timeout=180,
                                     env=dict(os.environ, PYTHONHASHSEED='0'))
                samples[index].append(json.loads(run.stdout))
        results = []
        for group in samples:
            summary = dict(group[0])
            for entry in group:
                if (entry['input_sha256'], entry['output_sha256']) != (summary['input_sha256'], summary['output_sha256']):
                    raise AssertionError('Input or output changed between samples: ' + str((case, filename)))
            for key in ('samples_seconds', 'samples_cpu_seconds'):
                summary[key] = [value for entry in group for value in entry[key]]
            summary['median_seconds'] = statistics.median(summary['samples_seconds'])
            summary['median_cpu_seconds'] = statistics.median(summary['samples_cpu_seconds'])
            summary['iterations'] = [entry['iterations'] for entry in group]
            peaks = [entry['peak_process_bytes'] for entry in group if entry['peak_process_bytes'] is not None]
            summary['peak_process_bytes'] = max(peaks) if peaks else None
            results.append(summary)
        before, after = results
        if before['input_sha256'] != after['input_sha256'] or before['output_sha256'] != after['output_sha256']:
            raise AssertionError('Output changed: ' + str((case, filename)))
        speedup = before['median_seconds'] / after['median_seconds']
        cpu_speedup = before['median_cpu_seconds'] / after['median_cpu_seconds']
        report['results'].append(dict(case=case, file=filename, before=before, after=after,
                                      speedup=speedup, cpu_speedup=cpu_speedup))
        print(f'{case} {filename or "(synthetic)"}: {before["median_seconds"] * 1000:.3f} -> '
              f'{after["median_seconds"] * 1000:.3f} ms ({speedup:.2f}x wall, {cpu_speedup:.2f}x CPU)', flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
