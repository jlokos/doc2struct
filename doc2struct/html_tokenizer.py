"""Inspect the native tokenizer using Python triples."""
from ._engine import _native

TEXT, START, END = 0, 1, 2
WANTED = frozenset(('style', 'colspan', 'rowspan', 'href', 'src', 'alt', 'hidden'))
VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                  'link', 'meta', 'param', 'source', 'track', 'wbr'))
RAW = frozenset(('script', 'style', 'title'))


def decode(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='replace')


def tokenize(html):
    yield from _native.tokenize(html)
