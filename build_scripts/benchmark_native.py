"""Compare two standalone C benchmark binaries on exactly the same HTML files.

Uses c/bench/test_many.c's parse-only wall-clock boundary. Input preparation,
file I/O, rule setup, document cleanup, and Python/JSON export are not timed.
Token-equivalents are estimates at four input bytes per token, not tokenization.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess


def html_files(directory):
    return sorted(p for p in directory.rglob('*')
                  if p.is_file() and p.suffix.lower() in ('.htm', '.html'))


def corpus_manifest(directory):
    files, digest, total = [], hashlib.sha256(), 0
    for path in html_files(directory):
        content = path.read_bytes()
        name = path.relative_to(directory).as_posix()
        sha = hashlib.sha256(content).hexdigest()
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(8, 'little'))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, 'little'))
        digest.update(bytes.fromhex(sha))
        files.append(dict(path=name, size=len(content), sha256=sha))
        total += len(content)
    if not files:
        raise ValueError(f'No HTML files in {directory}')
    return dict(files=len(files), input_bytes=total, input_sha256=digest.hexdigest()), files


def run(binary, directory, expected):
    proc = subprocess.run([str(binary), str(directory)], capture_output=True,
                          text=True, check=True, timeout=300)
    match = re.search(r'Total parsing time for (\d+) files: ([\d.]+) seconds\n'
                      r'Total parsed: ([\d.]+) MB\nThroughput: ([\d.]+) MB/s\n'
                      r'Total rows: (\d+)', proc.stdout)
    if not match:
        raise ValueError(f'Unrecognized benchmark output: {proc.stdout}')
    count, seconds, mb, throughput, rows = match.groups()
    if int(count) != expected['files'] or abs(float(mb) * 1e6 - expected['input_bytes']) > 501:
        raise ValueError('The benchmark did not read the expected corpus')
    return dict(files=int(count), parse_wall_seconds=float(seconds),
                throughput_mbps=float(throughput), rows=int(rows), stdout=proc.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--corpus', action='append', required=True, metavar='NAME=DIR')
    parser.add_argument('--repeat', type=int, default=9)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    binaries = [p.resolve(strict=True) for p in (args.reference, args.candidate)]
    report = dict(platform=platform.platform(), architecture=platform.machine(),
                  cpu=subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip()
                  if platform.system() == 'Darwin' else platform.processor(),
                  repeat=args.repeat, warmup_runs_per_build=1,
                  timing='native parse-only CLOCK_MONOTONIC wall time',
                  bytes_per_token_equivalent=4,
                  binaries=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                            for p in binaries], results=[])
    manifests = {}
    for spec in args.corpus:
        name, directory = spec.split('=', 1)
        directory = Path(directory).resolve(strict=True)
        expected, files = corpus_manifest(directory)
        manifests[name] = dict(directory=str(directory), files=files)
        samples = [[], []]
        warmups = [run(binary, directory, expected) for binary in binaries]
        if warmups[0]['rows'] != warmups[1]['rows']:
            raise ValueError(f'Output row counts differ on {name}')
        print(f'{name}: {expected["files"]} files, {expected["input_bytes"] / 1e6:.3f} MB; warmup complete', flush=True)
        for sample in range(args.repeat):
            for index in ((0, 1) if sample % 2 == 0 else (1, 0)):
                entry = run(binaries[index], directory, expected)
                if entry['rows'] != warmups[0]['rows']:
                    raise ValueError(f'Output row count changed on {name}')
                samples[index].append(entry)
        summaries = []
        for group in samples:
            throughput = [entry['throughput_mbps'] for entry in group]
            median = statistics.median(throughput)
            summaries.append(dict(median_mbps=median, min_mbps=min(throughput),
                                  max_mbps=max(throughput),
                                  median_parse_seconds=expected['input_bytes'] / 1e6 / median,
                                  estimated_million_token_equivalents_per_second=median / 4,
                                  samples=group))
        before, after = summaries
        result = dict(name=name, **expected, rows=warmups[0]['rows'],
                      before=before, after=after, speedup=after['median_mbps'] / before['median_mbps'])
        report['results'].append(result)
        print(f'{name}: {before["median_mbps"]:.3f} -> {after["median_mbps"]:.3f} MB/s '
              f'({result["speedup"]:.3f}x)', flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    with gzip.open(args.output.with_suffix('.manifest.json.gz'), 'wt') as stream:
        json.dump(manifests, stream, separators=(',', ':'))


if __name__ == '__main__':
    main()
