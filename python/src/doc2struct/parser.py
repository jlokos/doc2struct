"""HTML to standardized rows, with native intermediate storage."""
from ._engine import _native, prepare
from .rules import NormalizerOptions


def parse_html(html, rules=None, options=NormalizerOptions()):
    """Parse HTML, reusing up to 8 MiB of C memory between calls."""
    return _native.parse_html(
        html, prepare(rules), rules is not None,
        options.hide_hidden_attr, options.hide_visibility, options.max_span,
    )


def clear_parser_cache():
    """Release memory cached by parse_html; subsequent calls remain usable."""
    _native.clear_parser_cache()


class Parser:
    """Reuse up to cache_size bytes of C memory between sequential parses.

    Rules and returned rows have the same behavior as parse_html. Each instance
    has one owner; calls on that instance must not overlap. close() releases
    cached blocks, and clear() releases them while keeping the parser usable.
    """
    __slots__ = ('_handle',)

    def __init__(self, cache_size=8 * 1024 * 1024):
        self._handle = _native.parser_new(cache_size)

    def parse_html(self, html, rules=None, options=NormalizerOptions()):
        return _native.parse_html(
            html, prepare(rules), rules is not None,
            options.hide_hidden_attr, options.hide_visibility, options.max_span,
            self._handle,
        )

    @property
    def cache_size(self):
        return _native.parser_info(self._handle)[0]

    @property
    def cached_bytes(self):
        return _native.parser_info(self._handle)[1]

    @property
    def closed(self):
        return _native.parser_info(self._handle)[2]

    def clear(self):
        _native.parser_clear(self._handle)

    def close(self):
        _native.parser_close(self._handle)

    def __enter__(self):
        if self.closed:
            raise ValueError('Parser is closed')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
