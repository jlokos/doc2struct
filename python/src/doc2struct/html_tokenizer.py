"""Inspect the native tokenizer using Python triples."""
from ._engine import _native

TEXT, START, END = 0, 1, 2


def tokenize(html):
    """Tokenize HTML str, bytes or bytearray; token text is returned as str."""
    yield from _native.tokenize(html)
