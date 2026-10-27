"""parser.py - html bytes -> standardized text, in one call.

    rows = parse_html(html_bytes)                 # default columns
    rows = parse_html(html_bytes, "SEC:10-K")     # with rules (a form name, a rules file, a dict or a Rules object)

Runs html_tokenizer, then html_token_normalizer (instructions), then convert_instructions_to_standardized_text.
"""
from typing import Optional, Union
from pathlib import Path

from .convert_instructions_to_standardized_text import convert_instructions_to_standardized_text
from .html_token_normalizer import normalize
from .html_tokenizer import tokenize
from .rules import NormalizerOptions, Rules


def parse_html(html: bytes, rules: Optional[Union[Rules, str, Path, dict]] = None,
               options: NormalizerOptions = NormalizerOptions()) -> list:
    instructions = normalize(tokenize(html), options)
    return convert_instructions_to_standardized_text(instructions, rules)