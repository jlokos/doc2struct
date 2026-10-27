"""Performance prototypes for review; these are not part of the stable API."""
from ._engine import _native, prepare
from .rules import NormalizerOptions


class NativeDocument:
    """Retain native results and the input until explicit Python conversion."""
    __slots__ = ('_handle',)

    def __init__(self, handle):
        self._handle = handle

    def __len__(self):
        return _native.native_len(self._handle)

    def to_rows(self):
        return _native.native_rows(self._handle)

    def to_columns(self):
        return _native.native_columns(self._handle)

    def to_json_bytes(self):
        return _native.native_json(self._handle)


def parse_native(html, rules=None, options=NormalizerOptions(), *, parser=None):
    return NativeDocument(_native.parse_native(
        html, prepare(rules), rules is not None,
        options.hide_hidden_attr, options.hide_visibility, options.max_span,
        parser._handle if parser is not None else None,
    ))


def parse_columns(html, rules=None, options=NormalizerOptions(), *, parser=None):
    return parse_native(html, rules, options, parser=parser).to_columns()


def parse_json_bytes(html, rules=None, options=NormalizerOptions(), *, parser=None):
    return parse_native(html, rules, options, parser=parser).to_json_bytes()
