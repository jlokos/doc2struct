"""Isolated tokenizer experiments. Never builds into the production package.

Run from the repository root: python experimental/tokenizer_simd/lab.py --help
Generated sources, binaries, source hashes and measurements live in artifacts/.
"""
import argparse
import ctypes
import gc
import hashlib
import importlib.util
import json
import platform
import random
import runpy
import shutil
import statistics
import sys
import sysconfig
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "artifacts"
sys.path.insert(0, str(ROOT))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def snapshot():
    target = OUT / "snapshot"
    if target.exists():
        return
    target.mkdir(parents=True)
    shutil.copytree(ROOT / "c", target / "c")
    shutil.copyfile(ROOT / "setup.py", target / "setup.py")
    from doc2struct.rules import load_rules
    save(target / "rules.json", load_rules("SEC:10-K").to_dict())
    save(target / "manifest.json", {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "c").rglob("*") if p.is_file()
    })


FRONTEND = r'''
/* Lab-only measurement hook: same frontend as ds_parse, no Python token export. */
static PyObject *lab_frontend(PyObject *self, PyObject *args) {
    PyObject *html, *capsule, *owner = NULL;
    Document d = {0};
    Str text;
    Rules *rules;
    void *normalizer;
    int ok;
    size_t lines;
    NativeParser *parser;
    Options options = {0, 0, 100};
    if (!PyArg_ParseTuple(args, "OO", &html, &capsule)) return NULL;
    rules = PyCapsule_GetPointer(capsule, "doc2struct.Rules");
    if (!rules || !input(html, &text, &owner)) return NULL;
    capsule = default_parser(self);
    if (!capsule) { Py_XDECREF(owner); return NULL; }
    parser = PyCapsule_GetPointer(capsule, "doc2struct.Parser");
    d.arena.pool = &parser->context.pool;
    Py_BEGIN_ALLOW_THREADS
    text = ds_input(&d.arena, text);
    d.retain_table_cells = rules->unwrap_layout;
    d.collect_hrefs = rules->collect_hrefs;
    ok = text.p && ds_flow_begin(&d);
    normalizer = ok ? ds_normalizer(&d, options) : NULL;
    ok = normalizer && ds_tokenize(&d, text, ds_normalize_token, normalizer)
         && ds_normalize_finish(normalizer);
    lines = d.lines.n;
    ds_document_free(&d);
    Py_END_ALLOW_THREADS
    Py_XDECREF(owner);
    if (!ok) { PyErr_SetString(PyExc_RuntimeError, "lab frontend failed"); return NULL; }
    return PyLong_FromSize_t(lines);
}
'''


def build(names):
    from setuptools._distutils.ccompiler import new_compiler
    from variants import variants
    snapshot()
    base = OUT / "snapshot"
    with patch("setuptools.setup") as capture:
        runpy.run_path(str(base / "setup.py"))
    ext = capture.call_args.kwargs["ext_modules"][0]
    cc = new_compiler(compiler="msvc")
    cc.initialize()
    flags = ["/O2", "/GL", "/std:c11", "/utf-8"]
    macros = ext.define_macros + [("_CRT_SECURE_NO_WARNINGS", "1")]
    common = OUT / "common"
    common.mkdir(exist_ok=True)
    module = (base / "c/python/module.c").read_text(encoding="utf-8")
    module = module.replace("static PyMethodDef methods[] = {", FRONTEND + '\nstatic PyMethodDef methods[] = {\n    {"lab_frontend", lab_frontend, METH_VARARGS, "Lab frontend timing."},')
    (common / "module.c").write_text(module, encoding="utf-8")
    shared = []
    for source in ext.sources:
        if source == "c/tokenizer.c":
            continue
        path = common / "module.c" if source == "c/python/module.c" else base / source
        shared.append(str(path))
    include = [str(base / "c"), str(base / "c/vendor/pcre2"), sysconfig.get_path("include")]
    objects = cc.compile(shared, output_dir=str(common / "obj"), include_dirs=include,
                         macros=macros, extra_postargs=flags)
    source = (base / "c/tokenizer.c").read_text(encoding="utf-8")
    definitions = variants(source)
    for name in names:
        folder = OUT / name
        folder.mkdir(exist_ok=True)
        code, extra_flags = definitions[name]
        path = folder / "tokenizer.c"
        path.write_text(code, encoding="utf-8")
        token_obj = cc.compile([str(path)], output_dir=str(folder / "obj"),
                               include_dirs=include, macros=macros,
                               extra_postargs=flags + extra_flags)
        binary = folder / ("_native" + sysconfig.get_config_var("EXT_SUFFIX"))
        cc.link_shared_object(objects + token_obj, str(binary),
                              libraries=["python" + sysconfig.get_python_version().replace(".", "")],
                              library_dirs=[str(Path(sys.base_prefix) / "libs")],
                              export_symbols=["PyInit__native"],
                              extra_postargs=["/LTCG", "/OPT:REF"])
        print("BUILT", name, flush=True)


def load(name):
    path = next((OUT / name).glob("_native*.pyd"))
    spec = importlib.util.spec_from_file_location(name + "._native", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpus(limit=0):
    paths = sorted(p for p in (ROOT / "data/filings/many_10k").rglob("*")
                   if p.suffix.lower() in {".htm", ".html"})
    if limit:
        # Spread the sample across the sorted corpus, not just one issuer.
        paths = [paths[i * len(paths) // limit] for i in range(min(limit, len(paths)))]
    return [(str(p.relative_to(ROOT)), p.read_bytes()) for p in paths]


def pin_cpu():
    """Pin only this benchmark process to one of Windows' fastest-class cores."""
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.GetLogicalProcessorInformationEx.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    api.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    api.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    size = ctypes.c_ulong()
    api.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not api.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    process = api.GetCurrentProcess()
    allowed, system = ctypes.c_size_t(), ctypes.c_size_t()
    if not api.GetProcessAffinityMask(process, ctypes.byref(allowed), ctypes.byref(system)):
        raise ctypes.WinError(ctypes.get_last_error())
    cores, offset = [], 0
    data = buf.raw
    while offset < len(data):
        length = int.from_bytes(data[offset + 4:offset + 8], 'little')
        group = int.from_bytes(data[offset + 40:offset + 42], 'little')
        mask = int.from_bytes(data[offset + 32:offset + 40], 'little') & allowed.value
        if group == 0 and mask:
            cores.append((data[offset + 9], mask))
        offset += length
    fastest = max(eff for eff, _ in cores)
    candidates = [mask for eff, mask in cores if eff == fastest]
    mask = candidates[min(2, len(candidates) - 1)]
    mask &= -mask
    if not api.SetProcessAffinityMask(process, mask):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'logical_cpu': mask.bit_length() - 1, 'efficiency_class': fastest, 'core_classes': cores}


def measure(names, rounds, limit, modes, label):
    affinity = pin_cpu()
    inputs = corpus(limit)
    rules = json.loads((OUT / "snapshot/rules.json").read_text())
    modules = {name: load(name) for name in names}
    prepared = {name: mod.prepare_rules(rules) for name, mod in modules.items()}
    result = {"machine": platform.platform(), "cpu": platform.processor(), "affinity": affinity,
              "python": sys.version, "files": len(inputs),
              "bytes": sum(len(data) for _, data in inputs),
              "corpus": [{"path": p, "bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()} for p, d in inputs],
              "method": "preloaded inputs; one full warmup per variant/mode; shuffled variant order each round; timed output disposal; native 8 MiB arena reuse; no I/O or equality checking in timing",
              "samples": {mode: {name: [] for name in names} for mode in modes}}
    rng = random.Random(736)
    for mode in modes:
        functions = {name: (lambda data, n=name: modules[n].parse_html(data, prepared[n], True, False, False, 100))
                     if mode == "parse" else
                     (lambda data, n=name: modules[n].lab_frontend(data, prepared[n]))
                     for name in names}
        for round_number in range(-1, rounds):
            order = names[:]
            rng.shuffle(order)
            for name in order:
                gc.collect()
                fn = functions[name]
                start = perf_counter()
                for _, data in inputs:
                    output = fn(data)
                    del output
                elapsed = perf_counter() - start
                if round_number >= 0:
                    result["samples"][mode][name].append(elapsed)
                print(mode, round_number, name, f"{elapsed:.6f}s", flush=True)
                save(OUT / (label + ".json"), result)
        medians = {n: statistics.median(s) for n, s in result["samples"][mode].items()}
        for name, seconds in medians.items():
            print("MEDIAN", mode, name, f"{seconds:.6f}s", f"{result['bytes']/seconds/1e6:.1f} MB/s",
                  f"{medians.get('baseline', seconds)/seconds:.4f}x", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["build", "measure"])
    ap.add_argument("names", nargs="+", help="variant names, including baseline")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--modes", nargs="+", default=["parse", "frontend"])
    ap.add_argument("--label", default="measurements")
    args = ap.parse_args()
    if args.action == "build":
        build(args.names)
    else:
        measure(args.names, args.rounds, args.limit, args.modes, args.label)


if __name__ == "__main__":
    main()
