"""Plain text layout, using the native instruction format shared by HTML/PDF."""
from ._engine import _native, prepare


def convert_text_to_instructions(text, rules=None):
    """Convert str, bytes or bytearray to instructions without interpreting tags.

    Detects casing, heading underlines, indentation and aligned tables. Tabs
    advance to rules.adapters.text.tab_size character stops (1..256, default 8).
    Indentation uses 8px cells;
    font_size remains None. Physical source line numbers are zero-based.
    Bytes use UTF-8 with the same Windows-1252 fallback as the HTML frontend.
    Feed the result to convert_instructions_to_standardized_text with any rules.
    """
    return _native.text_instructions(text, prepare(rules))
