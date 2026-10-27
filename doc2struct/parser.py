"""HTML to standardized rows, with native intermediate storage."""
from ._engine import _native, prepare
from .rules import NormalizerOptions


def parse_html(html, rules=None, options=NormalizerOptions()):
    return _native.parse_html(
        html, prepare(rules), rules is not None,
        options.hide_hidden_attr, options.hide_visibility, options.max_span,
    )
