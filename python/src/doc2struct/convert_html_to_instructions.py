"""HTML tokenization and normalization stay native until instruction export."""
from ._engine import _native, prepare


def convert_html_to_instructions(html, rules=None):
    """Convert HTML str, bytes or bytearray to instruction dictionaries.

    Equivalent to normalize(tokenize(html), rules), keeping tokens in C.
    HTML settings come from rules.adapters.html. Heading and cleanup rules apply
    when standardizing the instructions.
    """
    return _native.html_instructions(html, prepare(rules))
