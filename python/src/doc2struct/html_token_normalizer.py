"""
html_token_normalizer.py - token stream -> flat rows of FACTS (no judgments about headers, levels or meaning).

    rows = normalize(tokenize(html))    # list of dicts, one per run of text / image, in document order
    cols = to_columns(rows)             # {column: [values]}  (feed to pyarrow / polars / duckdb)

Normalization runs in C, using a small open-element stack and style/table state
to emit text and image runs without building a DOM.

Row columns
    block      id from one counter in document order: a plain line gets one, a whole table gets one
    line       global visual-line counter (a line ends at the end of p/div/h1-h6/li or at <br>)
    row, col   position inside a table (None outside tables)
    span       "RxC" (rowspan x colspan) for a cell bigger than 1x1, otherwise None
    text       the run's text (entities decoded, source whitespace kept); for an image, its alt
    flags      bitmask: BOLD 1, ITALIC 2, UNDERLINE 4, CENTERED 8
    font_size  px (float), nearest enclosing inline font-size, rounded to whole pixels (None if none)
    indent     px (float), nearest enclosing element's own text-indent/padding/margin,
               rounded to whole pixels (None if none);
               native list items also include 40px per nested list beyond the first
    href       link target of the enclosing <a> ('' if it has none, None outside links)
    tag        innermost enclosing block tag (p, div, h1-h6, li, td, th); native list-item content uses li
    src        image source; set only on image rows

Hidden: inline display:none is always hidden; rules.adapters.html adds the `hidden` attribute and visibility. Nested tables are flattened
into the cell that holds them. Whitespace-only text at the start of a line is dropped. Spans are capped.
"""
from ._engine import _native, prepare

COLUMNS = ('block', 'line', 'row', 'col', 'span', 'text', 'flags', 'font_size', 'indent', 'href', 'tag', 'src')

BOLD, ITALIC, UNDERLINE, CENTERED = 1, 2, 4, 8


def normalize(tokens, rules=None):
    """Normalize tokens using rules.adapters.html."""
    return _native.normalize(tokens, prepare(rules))


def to_columns(rows):
    return {c: [r[c] for r in rows] for c in COLUMNS}


def write_parquet(rows, path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table(to_columns(rows)), path)
