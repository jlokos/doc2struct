"""Compare full native C JSON results without retaining expanded snapshots.

Pass two shared libraries made from the same static archives as the benchmark
binaries. Serialization and hashing are correctness checks, outside timings.
"""
import argparse
import ctypes as c
import gzip
import hashlib
import json
from pathlib import Path

from benchmark_native import corpus_manifest, html_files


class Input(c.Structure):
    _fields_ = [('p', c.c_char_p), ('n', c.c_size_t)]


class Error(c.Structure):
    _fields_ = [('message', c.c_char * 256)]


class Native:
    def __init__(self, path):
        self.lib = c.CDLL(str(path.resolve()))
        self.error = Error()
        signatures = {
            'doc2struct_rules_preset': ([c.c_char_p, c.POINTER(Error)], c.c_void_p),
            'doc2struct_rules_free': ([c.c_void_p], None),
            'doc2struct_parser_new': ([c.c_size_t, c.POINTER(Error)], c.c_void_p),
            'doc2struct_parser_free': ([c.c_void_p], None),
            'doc2struct_parse': ([c.c_void_p, Input, c.c_void_p, c.POINTER(Error)], c.c_void_p),
            'doc2struct_document_rows': ([c.c_void_p, c.POINTER(c.c_size_t)], c.c_void_p),
            'doc2struct_document_json': ([c.c_void_p, c.c_void_p, c.c_int,
                                        c.POINTER(c.c_size_t), c.POINTER(Error)], c.c_void_p),
            'doc2struct_buffer_free': ([c.c_void_p], None),
            'doc2struct_document_free': ([c.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        self.rules = self.lib.doc2struct_rules_preset(b'SEC:10-K', c.byref(self.error))
        self.parser = self.lib.doc2struct_parser_new(8 * 1024 * 1024, c.byref(self.error))
        if not self.rules or not self.parser:
            self.close()
            raise RuntimeError(self.error.message.decode(errors='replace'))

    def close(self):
        self.lib.doc2struct_parser_free(self.parser)
        self.lib.doc2struct_rules_free(self.rules)

    def parse(self, content):
        self.error.message = b''
        document = self.lib.doc2struct_parse(self.parser, Input(content, len(content)),
                                             self.rules, c.byref(self.error))
        if not document:
            raise RuntimeError(self.error.message.decode(errors='replace'))
        buffer = None
        try:
            rows, size = c.c_size_t(), c.c_size_t()
            self.lib.doc2struct_document_rows(document, c.byref(rows))
            buffer = self.lib.doc2struct_document_json(document, self.rules, 1,
                                                       c.byref(size), c.byref(self.error))
            if not buffer:
                raise RuntimeError(self.error.message.decode(errors='replace'))
            return c.string_at(buffer, size.value), rows.value
        finally:
            self.lib.doc2struct_buffer_free(buffer)
            self.lib.doc2struct_document_free(document)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--corpus', action='append', required=True, metavar='NAME=DIR')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(reference=str(args.reference.resolve()), candidate=str(args.candidate.resolve()),
                  comparison='exact native JSON bytes and row counts', results=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output.with_suffix('.records.jsonl.gz'), 'wt') as records:
        for spec in args.corpus:
            name, directory = spec.split('=', 1)
            directory = Path(directory).resolve(strict=True)
            expected, manifest = corpus_manifest(directory)
            before, after = Native(args.reference), Native(args.candidate)
            digest, total_rows, output_bytes = hashlib.sha256(), 0, 0
            try:
                for index, (path, info) in enumerate(zip(html_files(directory), manifest, strict=True)):
                    content = path.read_bytes()
                    if hashlib.sha256(content).hexdigest() != info['sha256']:
                        raise AssertionError(f'Input changed: {path}')
                    left, left_rows = before.parse(content)
                    right, right_rows = after.parse(content)
                    if left_rows != right_rows or left != right:
                        raise AssertionError(f'Native output differs: {path}; '
                                             f'rows {left_rows}/{right_rows}; '
                                             f'JSON SHA256 {hashlib.sha256(left).hexdigest()}/'
                                             f'{hashlib.sha256(right).hexdigest()}')
                    sha = hashlib.sha256(left).hexdigest()
                    digest.update(bytes.fromhex(sha))
                    total_rows += left_rows
                    output_bytes += len(left)
                    records.write(json.dumps(dict(corpus=name, index=index, **info,
                                                  output_sha256=sha, rows=left_rows)) + '\n')
            finally:
                before.close()
                after.close()
            report['results'].append(dict(name=name, **expected, rows=total_rows,
                                          output_bytes=output_bytes, output_sha256=digest.hexdigest()))
            args.output.write_text(json.dumps(report, indent=2) + '\n')
            print(f'{name}: {expected["files"]} native JSON results match exactly', flush=True)


if __name__ == '__main__':
    main()
