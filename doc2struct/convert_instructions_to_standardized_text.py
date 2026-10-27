"""
convert_instructions_to_standardized_text.py - instructions (from html or pdf) -> standardized text rows.

    rows = convert_instructions_to_standardized_text(instructions)            # default columns
    rows = convert_instructions_to_standardized_text(instructions, SEC_10K)   # with rules

Input: list of instruction cells with the columns block, line, row, col, span, text, flags, font_size, indent, href,
src (tag is ignored). Any source that produces those columns works, html or pdf. Knows nothing about html.

Output: list of dicts, one per element, in document order. Every row has every column (None when not applicable).

    default      id, level, type, text, matrix, cleaned, preamble, footnotes, postamble
    with rules   id, level, type, class, standardized_title, text, matrix, cleaned, preamble, footnotes, postamble
                 (+ the rules' custom columns)

    id                  increment of the output row
    level               nesting depth
    type                title | text | textsmall | table | image
    class               header class from a header rule, 'predicted header', or 'introduction'; else the type
    standardized_title  class + regex groups, e.g. item1a
    text                text of the line (image: its alt, table: its title); None for a table with no title
    matrix              table as rows of strings; None for other types
    cleaned             table rows: True if the table passed structural validation
    preamble            table rows: text lines just before the table (moved off their own rows)
    footnotes           table rows: [[id, text], ...] from the lines or tables just after it (moved)
    postamble           table rows: text lines just after the footnotes (moved)

Pipeline: group -> clean -> split headers -> classify -> build (nesting) -> tables -> custom columns.
Heuristics follow doc2dict (most common font size, +20% = big, smaller = small, bold/italic/underline/centered/
all-caps/proper-case = header-like). Not ported: the PDF font-size-only level mode.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

from .rules import Rules, load_rules

EMPTY_CHARS = ' \t\n\r\xa0​'
BOLD, ITALIC, UNDERLINE, CENTERED = 1, 2, 4, 8
HEADER_FLAGS = BOLD | ITALIC | UNDERLINE | CENTERED


# ===================================================================================================== rules
# rule types and presets live in the rules package; this file only runs them

DEFAULT_COLUMNS = ('id', 'level', 'type', 'text', 'matrix', 'cleaned', 'preamble', 'footnotes', 'postamble')
RULE_COLUMNS = ('id', 'level', 'type', 'class', 'standardized_title', 'text', 'matrix', 'cleaned', 'preamble',
                'footnotes', 'postamble')


# ==================================================================================================== helpers
def _check_string_style(text):
    if not text or not text.strip():
        return {}
    if text.isupper():
        return {'all_caps': True}
    t = re.sub(r'\b(and|or|of|the|in|on|at|to|for|with|by|a|an)\b', 'STOP', text, flags=re.IGNORECASE)
    if re.match(r'^[A-Z][a-zA-Z]*(\s+(STOP|[A-Z][a-zA-Z]*))*$', t) and re.search(r'[A-Z]', t):
        return {'proper_case': True}
    return {}


def _is_image(item):
    return item.get('src') is not None


def _item(r):
    return {'text': r['text'] or '', 'flags': r['flags'] or 0, 'font_size': r['font_size'],
            'indent': r['indent'], 'href': r['href'], 'src': r['src']}


def _empty(item):
    return not _is_image(item) and not item['text'].strip(EMPTY_CHARS)


_MERGE_KEYS = ('flags', 'font_size')


def _same_style(a, b):
    return all(a[k] == b[k] for k in _MERGE_KEYS)


def _merge_items(items):
    """Join neighbouring pieces of a line that share a style; whitespace-only pieces join the previous piece."""
    if len(items) <= 1:
        return items
    out = [items[0]]
    for cur in items[1:]:
        prev = out[-1]
        if _is_image(cur) or _is_image(prev):
            out.append(cur)
        elif _empty(cur) or _same_style(cur, prev):
            prev['text'] += cur['text']
        else:
            for j in range(len(out) - 1, -1, -1):          # rejoin an earlier piece of the same style
                earlier = out[j]
                if not _is_image(earlier) and _same_style(cur, earlier):
                    earlier['text'] += ''.join(o['text'] for o in out[j + 1:] if not _is_image(o)) + cur['text']
                    out = out[:j + 1]
                    break
            else:
                out.append(cur)
    return out


# ===================================================================================================== group
def _span(s):
    if not s:
        return 1, 1
    a, b = s.split('x')
    return int(a), int(b)


def _table_matrix(rows):
    """Instruction cells of one table -> matrix of cell dicts (a spanned cell is repeated at every position)."""
    cells, order = {}, []
    for r in rows:
        key = (r['row'], r['col'])
        if key not in cells:
            cells[key] = {'span': _span(r['span']), 'lines': {}}
            order.append(key)
        cells[key]['lines'].setdefault(r['line'], []).append(r)
    max_r = max(k[0] + cells[k]['span'][0] for k in order)
    max_c = max(k[1] + cells[k]['span'][1] for k in order)
    matrix = [[{'text': '', 'flags': 0, 'font_size': None, 'indent': None, 'href': None} for _ in range(max_c)]
              for _ in range(max_r)]
    for key in order:
        c = cells[key]
        texts, flags, font, indent, href = [], 0, None, None, None
        for ln in sorted(c['lines']):
            line_text = ''
            for r in c['lines'][ln]:
                if r['src'] is not None:
                    line_text += f"[ALT: {r['text']}. SRC: {r['src']}]"
                else:
                    line_text += r['text'] or ''
                flags |= r['flags'] or 0
                font = r['font_size'] if r['font_size'] is not None else font
                indent = r['indent'] if r['indent'] is not None else indent
                href = r['href'] if r['href'] is not None else href
            texts.append(line_text)
        cell = {'text': '\n'.join(texts).strip(EMPTY_CHARS), 'flags': flags, 'font_size': font, 'indent': indent,
                'href': href}
        for y in range(c['span'][0]):
            for x in range(c['span'][1]):
                matrix[key[0] + y][key[1] + x] = cell
    return matrix


def _group(instructions):
    """-> list of lines: {'items': [...]} for text/images, {'matrix': [[str]]} for tables."""
    lines = []
    i, n = 0, len(instructions)
    while i < n:
        r = instructions[i]
        j = i
        while j < n and instructions[j]['block'] == r['block']:
            j += 1
        block = instructions[i:j]
        i = j
        if r['row'] is not None:
            matrix = _table_matrix(block)
            meaningful = [[c for c in row if c['text']] for row in matrix]
            meaningful = [m for m in meaningful if m]
            if len(meaningful) == 1:                      # "fake table": layout table with one real row
                items = [dict(c, src=None, fake_table=True) for c in meaningful[0]]
                lines.append({'items': items})
            elif meaningful:
                lines.append({'matrix': [[c['text'] for c in row] for row in matrix]})
            continue
        items = [_item(x) for x in block]
        while items and _empty(items[0]):
            items.pop(0)
        items = _merge_items(items)
        if len(items) == 1 and not _is_image(items[0]):
            items[0]['text'] = items[0]['text'].strip(EMPTY_CHARS)
        if any(not _empty(it) for it in items):
            lines.append({'items': items})
    return lines


# ====================================================================================================== clean
def _clean(lines, rules):
    threshold = rules.remove.repeat_threshold
    counts = {}
    if threshold:
        for ln in lines:
            for it in ln.get('items', ()):
                t = it['text'].strip(EMPTY_CHARS).lower()
                if t and not _is_image(it):
                    counts[t] = counts.get(t, 0) + 1
    repeated = {t for t, c in counts.items() if threshold and c >= threshold}
    patterns = [(re.compile(p), needs_href) for p, needs_href in rules.remove.patterns]
    out = []
    for ln in lines:
        if 'items' not in ln:
            out.append(ln)
            continue
        kept = []
        for it in ln['items']:
            if _is_image(it):
                kept.append(it)
                continue
            text = it['text'].strip().lower()
            if text in repeated or any(rx.match(text) and (not nh or it['href'] is not None) for rx, nh in patterns):
                continue
            kept.append(it)
        if kept:
            out.append({'items': kept})
    return out


# ============================================================================================= split headers
def _font_stats(lines):
    counts = {}
    for ln in lines:
        first = ln['items'][0] if ln.get('items') else None
        if first and not _is_image(first) and first['font_size'] is not None:
            counts[first['font_size']] = counts.get(first['font_size'], 0) + 1
    if not counts:
        return None, False
    size, n = max(counts.items(), key=lambda kv: kv[1])
    return size, n > 0.5 * len(lines)


def _header_like(first, big):
    if _is_image(first):
        return False
    return (big or bool(first['flags'] & HEADER_FLAGS) or first.get('fake_table')
            or bool(_check_string_style(first['text'])))


def _is_big(first, common, dominant):
    return bool(dominant and first['font_size'] is not None and first['font_size'] > 1.2 * common)


def _split_headers(lines):
    common, dominant = _font_stats(lines)
    out = []
    for ln in lines:
        items = ln.get('items')
        if items and len(items) > 1 and _header_like(items[0], _is_big(items[0], common, dominant)):
            out.append({'items': [items[0]]})
            out.append({'items': items[1:]})
        else:
            out.append(ln)
    return out


# ==================================================================================================== classify
def _predicted_levels(levels):
    predicted = [l for l in levels if l['class'] == 'predicted header']
    if not predicted:
        return levels
    base = min(h['level'] for h in predicted)
    section_level, attr_level = -1, {}
    for item in levels:
        if item['class'] not in ('predicted header', 'text', 'textsmall'):
            if item['level'] <= section_level:
                attr_level = {}
            section_level = item['level']
            continue
        if item['class'] != 'predicted header':
            continue
        key = '_'.join(sorted(item['attrs'])) or 'none'
        if key not in attr_level:
            attr_level[key] = base + len(attr_level)
        item['level'] = attr_level[key]
    return levels


def _classify(lines, rules):
    compiled = [(re.compile(r.regex), r.name, r.level, set(r.requires)) for r in rules.headers]
    predicted_level = (max(r.level for r in rules.headers) + 1) if rules.headers else 0
    common, dominant = _font_stats(lines)
    levels = []
    for ln in lines:
        first = ln['items'][0] if ln.get('items') else None
        lvl = {'level': -1, 'class': 'text', 'title': '', 'attrs': set()}
        if first and not _is_image(first):
            big = _is_big(first, common, dominant)
            style = _check_string_style(first['text'])
            attrs = set(style)
            for name, bit in (('bold', BOLD), ('italic', ITALIC), ('underline', UNDERLINE), ('centered', CENTERED)):
                if first['flags'] & bit:
                    attrs.add(name)
            if first.get('fake_table'):
                attrs.add('fake_table')
            header_like = big or bool(attrs)
            if dominant and first['font_size'] is not None and first['font_size'] < common:
                lvl = {'level': -2, 'class': 'textsmall', 'title': '', 'attrs': set()}
            elif header_like:
                text = first['text'].lower().strip()
                for rx, name, level, requires in compiled:
                    m = rx.match(text)
                    if m and requires <= attrs:
                        groups = ''.join(g for g in m.groups() if g is not None)
                        lvl = {'level': level, 'class': name, 'title': f'{name}{groups}', 'attrs': attrs}
                        break
                else:
                    lvl = {'level': predicted_level, 'class': 'predicted header', 'title': '', 'attrs': attrs}
        levels.append(lvl)
    return _predicted_levels(levels)


# ====================================================================================================== build
def _line_text(items):
    texts = [it['text'] for it in items if not _is_image(it)]
    if items and items[0].get('fake_table'):
        return ' '.join(t.strip() for t in texts)
    return ''.join(texts)


def _build(lines, labels):
    rows = []

    def add(**kw):
        r = {'id': len(rows), 'level': None, 'type': None, 'class': None, 'standardized_title': None,
             'text': None, 'matrix': None, 'cleaned': None, 'preamble': None, 'footnotes': None,
             'postamble': None, '_items': []}
        r.update(kw)
        rows.append(r)
        return r

    intro = add(level=0, type='title', text='introduction', **{'class': 'introduction'})
    stack = [-1, 0]                                   # nesting levels; the introduction closes at level 0
    for ln, lab in zip(lines, labels):
        level = lab['level']
        if 'matrix' in ln:
            add(level=len(stack) - 1, type='table', matrix=ln['matrix'], **{'class': 'table'})
            continue
        items = ln['items']
        if level >= 0:
            while len(stack) > 1 and stack[-1] >= level:
                stack.pop()
            text = _line_text(items) if not _is_image(items[0]) else '[Non-text header]'
            add(level=len(stack) - 1, type='title', text=text, standardized_title=lab['title'] or None,
                _items=items[:1], **{'class': lab['class']})
            stack.append(level)
            continue
        depth = len(stack) - 1
        text_items = [it for it in items if not _is_image(it)]
        text = _line_text(items)
        if text.strip(EMPTY_CHARS):
            add(level=depth, type=lab['class'], text=text.strip(EMPTY_CHARS), _items=text_items,
                **{'class': lab['class']})
        for it in items:
            if _is_image(it):
                add(level=depth, type='image', text=it['text'], _items=[it], **{'class': 'image'})
    return rows


# ====================================================================================================== tables
def _is_left(t):
    return bool(t) and all(ch in '$(–-' for ch in t)


def _is_right(t):
    return bool(t) and all(ch in ')%–-' for ch in t)


def _is_content(t):
    return any(ch not in '$()%–-' for ch in t)


def _merge_formatting(table):
    table = [row[:] for row in table]
    for row in table:
        for j, t in enumerate(row):
            if _is_left(t):
                for k in range(j + 1, len(row)):
                    if _is_content(row[k]):
                        row[k], row[j] = t + row[k], ''
                        break
    for row in table:
        for j, t in enumerate(row):
            if _is_right(t):
                for k in range(j - 1, -1, -1):
                    if _is_content(row[k]):
                        row[k], row[j] = row[k] + t, ''
                        break
    return table


_BLANK = ('', '–', '-')


def _subset(a, b):
    return all(x in _BLANK or x == y for x, y in zip(a, b))


def _clean_table(table, steps):
    """table: rows of strings -> (table, cleaned)"""
    cleaned = True
    table = [[c.strip(EMPTY_CHARS) for c in row] for row in table]
    if 'validate_structure' in steps and (not table or any(len(r) != len(table[0]) for r in table)):
        cleaned = False
    if 'merge_formatting_chars' in steps:
        table = _merge_formatting(table)
    if 'remove_empty_rows' in steps:
        table = [r for r in table if any(c not in _BLANK for c in r)]
    if 'remove_empty_columns' in steps and table and table[0]:
        keep = [j for j in range(len(table[0])) if any(j < len(r) and r[j] not in _BLANK for r in table)]
        table = [[r[j] for j in keep if j < len(r)] for r in table]
    if 'remove_subset_rows_bottom_to_top' in steps:
        keep = [True] * len(table)
        for i in range(len(table) - 1, 0, -1):
            if _subset(table[i], table[i - 1]):
                keep[i] = False
        table = [r for r, k in zip(table, keep) if k]
    if 'remove_subset_rows_top_to_bottom' in steps:
        keep = [True] * len(table)
        for i in range(len(table) - 1):
            if _subset(table[i], table[i + 1]):
                keep[i] = False
        table = [r for r, k in zip(table, keep) if k]
    for name in ('remove_subset_columns_left_to_right', 'remove_subset_columns_right_to_left'):
        if name not in steps or not table:
            continue
        width = min(len(r) for r in table)
        left = name.endswith('left_to_right')
        keep = [True] * width
        for j in (range(width - 1) if left else range(width - 1, 0, -1)):
            other = j + 1 if left else j - 1
            if _subset([r[j] for r in table], [r[other] for r in table]):
                keep[j] = False
        table = [[r[j] for j in range(width) if keep[j]] for r in table]
    if 'merge_duplicate_header_rows_down' in steps and len(table) >= 2:
        top = table[0]
        if any(top[i] == top[i + 1] for i in range(len(top) - 1)):
            second = table[1]
            merged = [t if i >= len(second) or t == second[i] else t + '\n' + second[i] for i, t in enumerate(top)]
            table = [merged] + table[2:]
    return table, cleaned


_TEXT_TYPES = ('text', 'textsmall')


def _footnotes_from_table(matrix, rx):
    """A table of exactly two columns whose first column is all footnote markers -> [[id, text], ...]."""
    if not matrix or not all(len(row) == 2 for row in matrix):
        return None
    notes = []
    for marker, text in matrix:
        m = rx.match(marker.strip())
        if not m:
            return None
        notes.append([m.group(1), text.strip()])
    return notes


def _absorb_notes(rows, t):
    """Move preamble, footnotes and postamble text lines onto the table row they belong to."""
    rx = re.compile(t.footnote_regex) if t.footnote_regex else None
    removed = set()
    n = len(rows)
    for i, r in enumerate(rows):
        if r['type'] != 'table' or i in removed:
            continue
        if t.preamble_lines > 0:                                  # walk backwards over text lines
            parts, j = [], i - 1
            while j >= 0 and len(parts) < t.preamble_lines and rows[j]['type'] in _TEXT_TYPES and j not in removed:
                parts.insert(0, rows[j]['text'])
                removed.add(j)
                j -= 1
            if parts:
                r['preamble'] = ' '.join(parts)
        last = i
        if rx:                                                    # footnote lines and footnote tables
            notes, j = [], i + 1
            while j < n and j not in removed:
                x = rows[j]
                if x['type'] == 'table':
                    found = _footnotes_from_table(x['matrix'], rx)
                    if found is None:
                        break
                    notes.extend(found)
                    removed.add(j)
                    last = j
                    j += 1
                    continue
                if x['type'] not in _TEXT_TYPES:
                    break
                m = rx.match(x['text'].strip())
                if not m:
                    break
                text = x['text'].strip()[len(m.group(0)):].strip()
                removed.add(j)
                k, extra = j + 1, 0
                while (k < n and extra < t.footnote_lines and rows[k]['type'] in _TEXT_TYPES
                       and k not in removed and not rx.match(rows[k]['text'].strip())):
                    text += ' ' + rows[k]['text'].strip()
                    removed.add(k)
                    extra += 1
                    k += 1
                notes.append([m.group(1), text])
                last = k - 1
                j = k
            if notes:
                r['footnotes'] = notes
        if t.postamble_lines > 0:                                 # text lines after the footnotes
            parts, j = [], last + 1
            while j < n and len(parts) < t.postamble_lines and rows[j]['type'] in _TEXT_TYPES and j not in removed:
                parts.append(rows[j]['text'])
                removed.add(j)
                j += 1
            if parts:
                r['postamble'] = ' '.join(parts)
    return [r for i, r in enumerate(rows) if i not in removed]


def _title_tables(rows):
    """A section with exactly one table directly in it gives that table a copy of its title (never overwrites)."""
    heads = [i for i, r in enumerate(rows) if r['type'] == 'title']
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(rows)
        tables = [r for r in rows[i + 1:end] if r['type'] == 'table']
        if len(tables) == 1 and not tables[0]['text']:
            tables[0]['text'] = rows[i]['text']


def _process_tables(rows, rules):
    out = []
    for r in rows:
        if r['type'] == 'table':
            matrix, cleaned = _clean_table(r['matrix'], rules.tables.steps)
            if not matrix:
                continue
            if rules.tables.single_row_to_text and len(matrix) == 1:
                r.update(type='text', text=' '.join(matrix[0]), matrix=None, cleaned=None)
                r['class'] = 'text'
            else:
                r.update(matrix=matrix, cleaned=cleaned)
        out.append(r)
    out = _absorb_notes(out, rules.tables)
    if rules.tables.title_from_section:
        _title_tables(out)
    for i, r in enumerate(out):
        r['id'] = i
    return out


# =============================================================================================== custom columns
def _cast(v, dtype):
    if v is None:
        return None
    try:
        if dtype == 'int':
            return int(v)
        if dtype == 'bool':
            return bool(v)
        return str(v)
    except (TypeError, ValueError):
        return None


def _custom_value(col, row, regex):
    if row['type'] == 'table' or (col.types and row['type'] not in col.types):
        return None
    items = row['_items']
    if col.source == 'text':
        m = regex.search(row['text'] or '') if regex else None
        if regex is None:
            return _cast(row['text'], col.dtype)
        return _cast(m.group(1) if m and m.groups() else (m.group(0) if m else None), col.dtype)
    vals = [it.get(col.source) for it in items if it.get(col.source) is not None]
    if col.which == 'all' or col.dtype == 'list':
        return [_cast(v, 'str' if col.dtype == 'list' else col.dtype) for v in vals]
    if not vals:
        return None
    return _cast(vals[0] if col.which == 'first' else vals[-1], col.dtype)


# ========================================================================================================= API
def convert_instructions_to_standardized_text(instructions, rules: Optional[Union[Rules, str, Path, dict]] = None) -> list:
    """rules: None (default columns), a Rules object, a preset name like 'sec_10k', a JSON path, or a dict."""
    with_rules = rules is not None
    rules = load_rules(rules) if with_rules else Rules()
    lines = _split_headers(_clean(_group(instructions), rules))
    rows = _process_tables(_build(lines, _classify(lines, rules)), rules)
    regexes = {c.name: (re.compile(c.pattern, re.IGNORECASE) if c.pattern else None) for c in rules.columns}
    columns = RULE_COLUMNS if with_rules else DEFAULT_COLUMNS
    out = []
    for r in rows:
        row = {k: r[k] for k in columns}
        for c in rules.columns:
            row[c.name] = _custom_value(c, r, regexes[c.name])
        out.append(row)
    return out