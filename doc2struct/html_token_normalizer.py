"""
html_token_normalizer.py - token stream -> flat rows of FACTS (no judgments about headers, levels or meaning).

    rows = normalize(tokenize(html))    # list of dicts, one per run of text / image, in document order
    cols = to_columns(rows)             # {column: [values]}  (feed to pyarrow / polars / duckdb)

No tree is built: a small open-element stack plays the tree builder (implied end tags, end tags never pop past a
table boundary), and style / table state is kept in counters and stacks. Same shape as the planned C version.

Row columns
    block      id from one counter in document order: a plain line gets one, a whole table gets one
    line       global visual-line counter (a line ends at the end of p/div/h1-h6/li or at <br>)
    row, col   position inside a table (None outside tables)
    span       "RxC" (rowspan x colspan) for a cell bigger than 1x1, otherwise None
    text       the run's text (entities decoded, source whitespace kept); for an image, its alt
    flags      bitmask: BOLD 1, ITALIC 2, UNDERLINE 4, CENTERED 8
    font_size  px (int), nearest enclosing inline font-size (None if none)
    indent     px (int), nearest enclosing element's own text-indent/padding/margin (None if none)
    href       link target of the enclosing <a> ('' if it has none, None outside links)
    tag        innermost enclosing block tag (p, div, h1-h6, li, td, th)
    src        image source; set only on image rows

Hidden: only inline display:none (options add the `hidden` attribute and visibility). Nested tables are flattened
into the cell that holds them. Whitespace-only text at the start of a line is dropped. Spans are capped.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple, Optional

from ._engine import _native
from .rules import NormalizerOptions

EMPTY_CHARS = ' \t\n\r\xa0\u200b'


# ----------------------------------------------------------------------------------------------- CSS
def _css_value(s: str):
    s = s.strip(EMPTY_CHARS)
    if s in ('auto', 'inherit', 'initial'):
        return 0.0, s
    num, unit = '', 'px'
    for i, ch in enumerate(s):
        if ch.isdigit() or ch == '.':
            num += ch
        elif ch == '-' and i == 0:
            num += ch
        else:
            unit = s[i:].strip(EMPTY_CHARS)
            break
    try:
        v = float(num) if num else 0.0
    except ValueError:
        v = 0.0
    return v, unit


@lru_cache(maxsize=20000)
def to_px(s: str) -> float:
    """CSS length -> pixels, with doc2struct's conversions (em/rem/% are relative to 16px)."""
    if not s:
        return 0.0
    v, u = _css_value(s)
    if u in ('auto', 'inherit', 'initial'):
        return 0.0
    if u == 'px': return v
    if u == 'pt': return v * 1.333
    if u in ('em', 'rem'): return v * 16
    if u == '%': return v * 16 / 100
    if u in ('ex', 'ch'): return v * 8
    if u == 'cm': return v * 37.8
    if u == 'mm': return v * 3.78
    if u == 'in': return v * 96
    if u == 'pc': return v * 16
    return v


def _font_shorthand(value: str) -> dict:
    parts = value.strip().split()
    if len(parts) < 2:
        return {}
    out, i = {}, 0
    if parts[i].lower() in ('italic', 'oblique', 'normal'):
        if parts[i].lower() == 'italic':
            out['font-style'] = 'italic'
        i += 1
    if i < len(parts) and parts[i].lower() in ('small-caps', 'normal'):
        i += 1
    if i < len(parts):
        w = parts[i].lower()
        if w in ('bold', '700'):
            out['font-weight'] = 'bold'; i += 1
        elif w in ('normal', '400'):
            out['font-weight'] = 'normal'; i += 1
        elif w in ('100', '200', '300', '500', '600', '800', '900', 'lighter', 'bolder'):
            out['font-weight'] = w; i += 1
    if i < len(parts):
        size = parts[i]
        out['font-size'] = size.split('/', 1)[0]
        i += 1
    if i < len(parts):
        out['font-family'] = ' '.join(parts[i:]).strip('\'"')
    return out


def _left_of_box(v: str) -> float:
    parts = v.split()
    if len(parts) == 4: return to_px(parts[3])
    if len(parts) in (2, 3): return to_px(parts[1])
    return to_px(v)


class Style(NamedTuple):
    bold: bool
    italic: bool
    underline: bool
    center: bool
    font_size: Optional[float]
    indent: float
    display_none: bool
    vis_hidden: bool


@lru_cache(maxsize=50000)
def parse_style(style: str) -> Style:
    d = {}
    for item in style.lower().split(';'):
        item = item.strip(EMPTY_CHARS)
        if ':' in item:
            k, v = item.split(':', 1)
            d[k.strip(EMPTY_CHARS)] = v.strip(EMPTY_CHARS)
    if 'font' in d:
        d.update(_font_shorthand(d['font']))
    indent = 0.0
    if 'text-indent' in d: indent += to_px(d['text-indent'])
    if 'padding' in d: indent += _left_of_box(d['padding'])
    if 'padding-left' in d: indent += to_px(d['padding-left'])
    if 'margin' in d: indent += _left_of_box(d['margin'])
    if 'margin-left' in d: indent += to_px(d['margin-left'])
    return Style(
        bold=d.get('font-weight') in ('bold', '700'),
        italic=d.get('font-style') == 'italic',
        underline=d.get('text-decoration') == 'underline',
        center=d.get('text-align') == 'center',
        font_size=to_px(d['font-size']) if 'font-size' in d else None,
        indent=indent,
        display_none=d.get('display') == 'none',
        vis_hidden=d.get('visibility') in ('hidden', 'collapse'),
    )




COLUMNS = ('block', 'line', 'row', 'col', 'span', 'text', 'flags', 'font_size', 'indent', 'href', 'tag', 'src')

BOLD, ITALIC, UNDERLINE, CENTERED = 1, 2, 4, 8


Options = NormalizerOptions   # defined in rules/types.py


def normalize(tokens, options=Options()):
    return _native.normalize(tokens, options.hide_hidden_attr, options.hide_visibility, options.max_span)


def to_columns(rows):
    return {c: [r[c] for r in rows] for c in COLUMNS}


def write_parquet(rows, path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table(to_columns(rows)), path)
