"""convert_html_to_instructions.py - html (a path or bytes) -> instructions.

    instructions = convert_html_to_instructions(path_or_bytes)

Runs html_tokenizer, then html_token_normalizer. Instructions are a list of instruction cells (dicts with the
columns block, line, row, col, span, text, flags, font_size, indent, href, tag, src), in document order.
"""
from .html_token_normalizer import Options, normalize
from .html_tokenizer import decode, tokenize


def convert_html_to_instructions(html, options: Options = Options()) -> list:
    if isinstance(html, str):
        if '<' in html:                      # already html text
            content = html
        else:                                # a path
            with open(html, 'rb') as f:
                content = decode(f.read())
    elif isinstance(html, (bytes, bytearray)):
        content = decode(bytes(html))
    else:                                    # os.PathLike
        with open(html, 'rb') as f:
            content = decode(f.read())
    return normalize(tokenize(content), options)