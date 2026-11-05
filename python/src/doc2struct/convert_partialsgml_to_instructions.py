"""Mixed text and partial SGML, without submission splitting or format guessing."""
from ._engine import _native, prepare


def convert_partialsgml_to_instructions(text, rules=None):
    """Convert str, bytes or bytearray containing a partial SGML document body.

    Uses the plain text layout engine plus PAGE, TABLE, CAPTION, S/C column
    markers, P/BR breaks, comments and B/I/U formatting. Tag names are case-insensitive;
    incomplete tables end at EOF. Unknown tags, including financial field names,
    remain literal text. This is not an HTML parser or a submission splitter.
    Column markers are hints checked against body rows. Tall headers collect
    their original fragments into cells; underlines can identify parent spans.
    Body rows contradicting the inferred grid remain text rather than acquiring
    artificial spans. Header hyphenation and physical source lines are retained.
    Tabs use rules.adapters.partialsgml.tab_size (1..256, default 8).
    Encoding and instruction fields match convert_text_to_instructions.
    SEC section rules are supplied separately when standardizing the result.
    """
    return _native.partialsgml_instructions(text, prepare(rules))
