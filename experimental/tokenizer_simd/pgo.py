"""Optional MSVC profile-guided build, trained on separate local filings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

from lab import OUT, ROOT, corpus, load, save


def train(name):
    # Python's extension loader does not use PATH for dependent DLL discovery.
    dll_directory = os.add_dll_directory(os.environ['LAB_COMPILER_DLLS'])
    mod = load(name)
    rules = mod.prepare_rules(json.loads((OUT / 'snapshot/rules.json').read_text()))
    excluded = {hashlib.sha256(data).digest() for _, data in corpus()}
    selected = []
    for path in sorted((ROOT / 'data/filings/test_work').rglob('*.htm')):
        data = path.read_bytes()
        digest = hashlib.sha256(data).digest()
        if digest not in excluded:
            selected.append((path, data))
    # Spread training across historical layouts and keep it disjoint by content.
    if len(selected) > 6:
        selected = [selected[i * len(selected) // 6] for i in range(6)]
    if not selected:
        raise RuntimeError('No disjoint training filings found')
    save(OUT / name / 'training.json', [
        {'path': str(p.relative_to(ROOT)), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for p, data in selected])
    for _ in range(3):
        for _, data in selected:
            mod.parse_html(data, rules, True, False, False, 100)
    print('Trained on', len(selected), 'disjoint filings', flush=True)


def build(names):
    from setuptools._distutils.ccompiler import new_compiler
    cc = new_compiler(compiler='msvc')
    cc.initialize()
    cc.force = True
    common = [str(p) for p in (OUT / 'common/obj').rglob('*.obj')]
    assert common
    for name in names:
        variant = name + '_pgo'
        folder = OUT / variant
        folder.mkdir(exist_ok=True)
        objects = common + [str(p) for p in (OUT / name / 'obj').rglob('*.obj')]
        binary = folder / ('_native' + sysconfig.get_config_var('EXT_SUFFIX'))
        flags = ['/LTCG', '/OPT:REF', '/PGD:' + str(folder / 'profile.pgd')]
        kwargs = dict(libraries=['python' + sysconfig.get_python_version().replace('.', '')],
                      library_dirs=[str(Path(sys.base_prefix) / 'libs')],
                      export_symbols=['PyInit__native'])
        cc.link_shared_object(objects, str(binary), extra_postargs=flags + ['/GENPROFILE'], **kwargs)
        env = os.environ.copy()
        env['LAB_COMPILER_DLLS'] = str(Path(cc.cc).parents[2] / 'Hostx64/x64')
        subprocess.run([sys.executable, str(Path(__file__)), '--train', variant], check=True, env=env)
        cc.link_shared_object(objects, str(binary), extra_postargs=flags + ['/USEPROFILE'], **kwargs)
        print('BUILT', variant, flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('names', nargs='+')
    ap.add_argument('--train', action='store_true')
    args = ap.parse_args()
    train(args.names[0]) if args.train else build(args.names)
