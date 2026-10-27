"""Check and time production builds against the frozen experimental baseline.

Build plain/scalar extensions into build/tokenizer-integration/{plain,scalar}
and the PGO extension in place. See PERFORMANCE.md for PGO build options.
"""
import argparse
import gc
import importlib.util
import json
import statistics
import sys
from time import perf_counter

import check
import extended_check
import lab


frozen_load = lab.load


def load(name):
    if name == 'integrated_pgo':
        folder = lab.ROOT / 'doc2struct'
    elif name in {'integrated_plain', 'integrated_scalar'}:
        folder = lab.ROOT / 'build/tokenizer-integration' / name.removeprefix('integrated_') / 'doc2struct'
    else:
        return frozen_load(name)
    binary = next(folder.glob('_native*.pyd'))
    spec = importlib.util.spec_from_file_location(name + '._native', binary)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure_paired(rounds):
    affinity = lab.pin_cpu()
    inputs = lab.corpus()
    names = ['baseline', 'integrated_plain', 'integrated_pgo']
    modules = {name: load(name) for name in names}
    rules = json.loads((lab.OUT / 'snapshot/rules.json').read_text())
    prepared = {name: module.prepare_rules(rules) for name, module in modules.items()}
    result = {
        'method': 'preloaded inputs; one warmup pass; variants alternate per file; '
                  'all six order permutations balanced across each six rounds; '
                  'includes output disposal; excludes I/O and rules preparation',
        'affinity': affinity, 'files': len(inputs), 'bytes': sum(len(d) for _, d in inputs),
        'samples': {name: [] for name in names},
    }
    for round_number in range(-1, rounds):
        gc.collect()
        elapsed = {name: 0.0 for name in names}
        for i, (_, data) in enumerate(inputs):
            offset = (round_number + i) % len(names)
            order = names[offset:] + names[:offset]
            if round_number % 2:
                order.reverse()
            for name in order:
                module, rule = modules[name], prepared[name]
                start = perf_counter()
                rows = module.parse_html(data, rule, True, False, False, 100)
                del rows
                elapsed[name] += perf_counter() - start
        if round_number >= 0:
            for name in names:
                result['samples'][name].append(elapsed[name])
        print(round_number, elapsed, flush=True)
        lab.save(lab.OUT / 'integration_paired.json', result)
    for name in names:
        times = result['samples'][name]
        ratios = [a / b for a, b in zip(result['samples']['baseline'], times)]
        print(name, f'{statistics.median(times):.6f}s',
              f'{statistics.median(ratios):.4f}x median paired throughput', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'extended', 'measure', 'paired'])
    parser.add_argument('--rounds', type=int, default=9)
    args = parser.parse_args()
    lab.load = check.load = extended_check.load = load
    names = ['integrated_plain', 'integrated_scalar', 'integrated_pgo']
    if args.action == 'paired':
        measure_paired(args.rounds)
    elif args.action == 'measure':
        lab.measure(['baseline', 'integrated_plain', 'integrated_pgo'], args.rounds, 0,
                    ['parse'], 'integration')
    else:
        sys.argv = [sys.argv[0], *names]
        (check.main if args.action == 'check' else extended_check.main)()


if __name__ == '__main__':
    main()
