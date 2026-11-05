"""PDF geometry and layout stay native until instruction export."""
from ._engine import _native, prepare


def convert_pdf_to_instructions(pdf, rules=None):
    """Convert PDF bytes to the same instruction dictionaries produced by HTML.

    Font sizes and indentation are converted from PDF points to CSS pixels.
    """
    return _native.pdf_instructions(pdf, prepare(rules))
