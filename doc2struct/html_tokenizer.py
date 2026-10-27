"""
html_tokenizer.py - HTML bytes -> tokens. Syntax only: no stack, no meaning (the Python twin of tokenizer.h).

    for kind, a, b in tokenize(html): ...        # html: bytes (UTF-8, else cp1252) or already-decoded str

    (TEXT, text, None)         entities decoded
    (START, tag, attrs)        tag lowercased; attrs = {name: value} for WANTED attributes only
    (END, tag, None)           also emitted right after a START written as <x/> (non-void)

Skipped entirely: comments, doctype, processing instructions, and the contents of script/style/title.
"""
import re
from html import unescape

TEXT, START, END = 0, 1, 2

WANTED = frozenset(('style', 'colspan', 'rowspan', 'href', 'src', 'alt', 'hidden'))
VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source',
                  'track', 'wbr'))
RAW = frozenset(('script', 'style', 'title'))

_MARKUP = re.compile(
    r'<!--.*?(?:-->|\Z)'                                   # comment
    r'|<[!?][^>]*>?'                                       # doctype / processing instruction
    r'|<(/?)([a-zA-Z][^\s/>]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)>',   # tag
    re.S)
_ATTR = re.compile(r'([^\s=/>"\']+)(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]*))?')


def _attrs(raw):
    out = {}
    for m in _ATTR.finditer(raw):
        name = m.group(1).lower()
        if name in WANTED:
            v = m.group(2)
            if v is None:
                out[name] = ''
            else:
                if v[:1] in ('"', "'"):
                    v = v[1:-1]
                out[name] = unescape(v) if '&' in v else v
    return out


def decode(data):
    """UTF-8 if valid, otherwise Windows-1252 (what browsers do for old filings)."""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='replace')


def tokenize(html):
    if isinstance(html, (bytes, bytearray)):
        html = decode(bytes(html))
    pos, n = 0, len(html)
    for m in _MARKUP.finditer(html):
        start = m.start()
        if start > pos:
            text = html[pos:start]
            yield TEXT, (unescape(text) if '&' in text else text), None
        pos = m.end()
        closing, tag, rest = m.group(1), m.group(2), m.group(3)
        if tag is None:
            continue                                       # comment / doctype / PI
        tag = tag.lower()
        if closing:
            yield END, tag, None
            continue
        selfclosed = rest.rstrip().endswith('/')
        yield START, tag, _attrs(rest) if rest.strip() else {}
        if tag in RAW and not selfclosed:                  # skip to the matching close tag
            m2 = re.compile(r'</' + tag + r'\s*>', re.I).search(html, pos)
            pos = m2.end() if m2 else n
            yield END, tag, None
        elif selfclosed and tag not in VOID:
            yield END, tag, None
    if pos < n:
        text = html[pos:]
        yield TEXT, (unescape(text) if '&' in text else text), None