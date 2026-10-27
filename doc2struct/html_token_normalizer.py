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

from .html_tokenizer import START, TEXT
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


# ------------------------------------------------------------------------------------------ tag sets
LINE_END = frozenset(('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li'))
BLOCK_TAGS = LINE_END | {'td', 'th'}
VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source',
                  'track', 'wbr'))
HEAD_TAGS = frozenset(('html', 'head', 'title', 'meta', 'link', 'base', 'style', 'script', 'noscript'))
P_CLOSERS = frozenset(('address', 'article', 'aside', 'blockquote', 'center', 'details', 'dialog', 'dir', 'div', 'dl',
                       'dd', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5',
                       'h6', 'header', 'hgroup', 'hr', 'li', 'main', 'menu', 'nav', 'ol', 'p', 'pre', 'section',
                       'summary', 'table', 'ul'))
BOLD_T, ITALIC_T, UNDER_T = frozenset(('b', 'strong')), frozenset(('i', 'em')), frozenset(('u', 'ins'))
P_STOP = frozenset(('table', 'td', 'th', 'body', 'html'))
END_STOP_CELL = frozenset(('tr', 'table'))
END_STOP_TABLE = frozenset(('table',))
END_STOP_OTHER = frozenset(('table', 'td', 'th'))


class _Frame:
    __slots__ = ('tag', 'bold', 'italic', 'underline', 'center', 'font', 'indent', 'href', 'hides', 'suppressed',
                 'act', 'root')

    def __init__(self, tag):
        self.tag = tag
        self.bold = self.italic = self.underline = self.center = 0
        self.font = self.indent = self.href = self.hides = self.suppressed = self.act = self.root = False


class _Table:
    __slots__ = ('block', 'row', 'col', 'occupied', 'cell')

    def __init__(self, block):
        self.block, self.row, self.col, self.occupied, self.cell = block, 0, 0, set(), None


class _Cell:
    __slots__ = ('row', 'col', 'rowspan', 'colspan', 'emitted')

    def __init__(self, row, col, rowspan, colspan):
        self.row, self.col, self.rowspan, self.colspan, self.emitted = row, col, rowspan, colspan, False


def _span(v, cap):
    try:
        n = int(v) if v else 1
    except ValueError:
        n = 1
    return max(1, min(n, cap))


class _Normalizer:
    def __init__(self, opts: Options):
        self.o = opts
        self.rows = []
        self.stack = []
        self.in_body = False
        self.hidden = 0
        # style state
        self.bold = self.italic = self.underline = self.center = 0
        self.font_stack, self.indent_stack, self.href_stack = [], [], []
        # structure state
        self.table = None
        self.table_depth = 0
        self.line_no = 0
        self.line_open = False
        self.next_block = 0
        self.cur_block = None

    # ------------------------------------------------------------------ token handlers
    def text(self, data):
        if not self.in_body or self.hidden or not data:
            return
        if not self.line_open and not data.strip(EMPTY_CHARS):
            return
        self._emit(data)

    # ------------------------------------------------------------------ helpers
    def _alloc(self):
        self.next_block += 1
        return self.next_block - 1

    def _break_line(self):
        if self.line_open:
            self.line_open = False
            self.line_no += 1

    def _block_tag(self):
        for f in reversed(self.stack):
            if f.tag in BLOCK_TAGS:
                return f.tag
        return None

    def _emit(self, text='', src=None, blank=False, cell=None):
        t = self.table
        if cell is None and t is not None:
            cell = t.cell
        if not self.line_open:
            self.line_open = True
            if cell is None:
                self.cur_block = self._alloc()
        r = dict.fromkeys(COLUMNS)
        r['block'] = t.block if cell is not None else self.cur_block
        r['line'] = self.line_no
        r['text'] = text
        r['flags'] = 0
        if cell is not None:
            r['row'], r['col'] = cell.row, cell.col
            if cell.rowspan > 1 or cell.colspan > 1:
                r['span'] = f'{cell.rowspan}x{cell.colspan}'
            cell.emitted = True
        if not blank:
            r['flags'] = ((BOLD if self.bold > 0 else 0) | (ITALIC if self.italic > 0 else 0) |
                          (UNDERLINE if self.underline > 0 else 0) | (CENTERED if self.center > 0 else 0))
            r['font_size'] = round(self.font_stack[-1]) if self.font_stack else None
            r['indent'] = round(self.indent_stack[-1]) if self.indent_stack else None
            r['href'] = self.href_stack[-1] if self.href_stack else None
            r['tag'] = self._block_tag()
        if src is not None:
            r['src'] = src
        self.rows.append(r)

    # ------------------------------------------------------------------ the small "tree builder"
    def _pop_if_open(self, names, stop):
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i].tag
            if t in names:
                for _ in range(len(self.stack) - i):
                    self._pop()
                return
            if t in stop:
                return

    def _implied_closes(self, tag):
        if tag in P_CLOSERS:
            self._pop_if_open(('p',), P_STOP)
        if tag == 'li':
            self._pop_if_open(('li',), ('ul', 'ol', 'table'))
        elif tag in ('dt', 'dd'):
            self._pop_if_open(('dt', 'dd'), ('dl', 'table'))
        elif tag in ('td', 'th'):
            self._pop_if_open(('td', 'th'), END_STOP_CELL)
        elif tag == 'tr':
            self._pop_if_open(('td', 'th'), END_STOP_CELL)
            self._pop_if_open(('tr',), END_STOP_TABLE)
        elif tag in ('thead', 'tbody', 'tfoot'):
            self._pop_if_open(('td', 'th'), END_STOP_CELL)
            self._pop_if_open(('tr',), END_STOP_TABLE)
            self._pop_if_open(('thead', 'tbody', 'tfoot'), END_STOP_TABLE)

    def start(self, tag, attrs):
        if not self.in_body:
            if tag in HEAD_TAGS:
                return
            self.in_body = True
        a = attrs
        style = a.get('style')
        st = parse_style(style) if style else None

        if tag in VOID:
            if self.hidden:
                return
            if st and (st.display_none or (self.o.hide_visibility and st.vis_hidden)):
                return
            if self.o.hide_hidden_attr and 'hidden' in a:
                return
            if tag == 'br':
                self._break_line()
            elif tag == 'img':
                self._emit(a.get('alt') or '', src=a.get('src') or '')
            return

        self._implied_closes(tag)
        f = _Frame(tag)
        self.stack.append(f)
        if self.hidden:
            f.suppressed = True
            return
        if (st and (st.display_none or (self.o.hide_visibility and st.vis_hidden))) or \
                (self.o.hide_hidden_attr and 'hidden' in a):
            f.suppressed = f.hides = True
            self.hidden += 1
            return

        if st:
            if st.bold: f.bold += 1
            if st.italic: f.italic += 1
            if st.underline: f.underline += 1
            if st.center: f.center += 1
            if st.font_size is not None:
                f.font = True
                self.font_stack.append(st.font_size)
            if st.indent != 0:
                f.indent = True
                self.indent_stack.append(st.indent)
        if tag in BOLD_T: f.bold += 1
        elif tag in ITALIC_T: f.italic += 1
        elif tag in UNDER_T: f.underline += 1
        elif tag == 'a':
            f.href = True
            self.href_stack.append(a.get('href') or '')
        self.bold += f.bold; self.italic += f.italic; self.underline += f.underline; self.center += f.center

        if tag == 'table':
            self.table_depth += 1
            self._break_line()
            if self.table_depth == 1:
                f.root = True
                self.table = _Table(self._alloc())
        elif tag in ('tr', 'td', 'th'):
            f.act = self.table is not None and self.table_depth == 1
            if f.act and tag != 'tr':
                self._break_line()
                t = self.table
                while (t.row, t.col) in t.occupied:
                    t.col += 1
                rs, cs = _span(a.get('rowspan'), self.o.max_span), _span(a.get('colspan'), self.o.max_span)
                for y in range(rs):
                    for x in range(cs):
                        t.occupied.add((t.row + y, t.col + x))
                t.cell = _Cell(t.row, t.col, rs, cs)
                t.col += cs

    def _pop(self):
        f = self.stack.pop()
        if f.hides:
            self.hidden -= 1
        if f.suppressed:
            return
        self.bold -= f.bold; self.italic -= f.italic; self.underline -= f.underline; self.center -= f.center
        if f.font: self.font_stack.pop()
        if f.indent: self.indent_stack.pop()
        if f.href: self.href_stack.pop()
        t = f.tag
        if t in LINE_END:
            self._break_line()
        elif t in ('td', 'th'):
            if f.act and self.table is not None and self.table.cell is not None:
                c = self.table.cell
                if not c.emitted:
                    self._emit('', blank=True, cell=c)   # keep empty cells: they hold the grid together
                self.table.cell = None
                self._break_line()
        elif t == 'tr':
            if f.act and self.table is not None:
                self.table.row += 1
                self.table.col = 0
        elif t == 'table':
            self.table_depth -= 1
            self._break_line()
            if f.root:
                self.table = None

    def end(self, tag):
        if not self.in_body or tag in VOID or tag in ('body', 'html'):
            return
        if tag in ('td', 'th'): stop = END_STOP_CELL
        elif tag in ('tr', 'thead', 'tbody', 'tfoot'): stop = END_STOP_TABLE
        elif tag == 'table': stop = ()
        else: stop = END_STOP_OTHER
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i].tag
            if t == tag:
                for _ in range(len(self.stack) - i):
                    self._pop()
                return
            if t in stop:
                return

    def finish(self):
        while self.stack:
            self._pop()


# ----------------------------------------------------------------------------------------------- API
def normalize(tokens, options: Options = Options()) -> list:
    """tokens: iterable of (kind, a, b) from tokenizer.tokenize."""
    n = _Normalizer(options)
    for kind, a, b in tokens:
        if kind == TEXT:
            n.text(a)
        elif kind == START:
            n.start(a, b)
        else:
            n.end(a)
    n.finish()
    return n.rows


def to_columns(rows: list) -> dict:
    return {c: [r[c] for r in rows] for c in COLUMNS}


def write_parquet(rows: list, path: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table(to_columns(rows)), path)