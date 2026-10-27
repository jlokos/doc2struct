"""Conservative positioned-HTML prototype, outside the public parser.

Geometry is a sidecar keyed by normalized run, not guessed from output text.
Opaque text markers are used only in a second normalization pass to prove the
alignment. A mismatch disables reconstruction for the document. Ordinary HTML
blocks, table cells, page changes and unknown coordinate contexts are barriers.
"""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import re

from doc2struct.html_token_normalizer import to_px

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}
MARKER = re.compile('\ue000' + r'(\d+)' + '\ue001')
BULLET = re.compile(r'^\s*(?:[•●▪◦‣–—-]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)]|\([ivxlcdmIVXLCDM]{2,8}\))\s*')
PAGE = re.compile(r'^(?:[A-Z]-)?\d{1,4}$')


@lru_cache(maxsize=30000)
def style(raw):
    return dict((k.strip().lower(), v.strip().lower()) for part in raw.split(';')
                if ':' in part for k, v in [part.split(':', 1)])


def length(value):
    # Relative percentages and em units require a containing-box model we do
    # not have. Missing/unsupported coordinates must never become zero.
    if value and re.fullmatch(r'-?\d+(?:\.\d+)?(?:pt|px)?', value):
        return to_px(value)
    return None


def facts(tokens):
    stack, values, page = [], {}, 0
    for i, (kind, tag, attrs) in enumerate(tokens):
        if kind == 1:
            css = style((attrs or {}).get('style', ''))
            frame = dict(stack[-1][1]) if stack else dict(page=None, y=None, x=None,
                                                          right=None, owner=None)
            if (css.get('position') == 'relative' and length(css.get('height')) and
                    length(css.get('width'))):
                page += 1
                frame.update(page=page, y=None, x=None, right=None, owner=None)
            if tag in {'div', 'p'} and css.get('position') == 'absolute' and 'top' in css:
                frame.update(y=length(css['top']), owner=i, x=None, right=None)
            if 'left' in css:
                frame['x'] = length(css['left'])
            if frame['x'] is not None and 'width' in css:
                width = length(css['width'])
                frame['right'] = frame['x'] + width if width is not None else None
            if tag not in VOID:
                stack.append((tag, frame))
        elif kind == 2:
            for j in range(len(stack)-1, -1, -1):
                if stack[j][0] == tag:
                    del stack[j:]
                    break
        elif stack:
            values[i] = dict(stack[-1][1])
    return values


def normalize_with_facts(module, tokens):
    original = module.normalize(tokens)
    sidecar = facts(tokens)
    marked = [(kind, f'\ue000{i}\ue001' + value if kind == 0 and value.strip() else value, attrs)
              for i, (kind, value, attrs) in enumerate(tokens)]
    tagged = module.normalize(marked)
    if len(original) != len(tagged):
        return original, {}, 'run-count mismatch'
    aligned = {}
    for i, (a, b) in enumerate(zip(original, tagged)):
        match = MARKER.match(b['text'])
        restored = MARKER.sub('', b['text'])
        if a != dict(b, text=restored):
            return original, {}, 'run alignment mismatch'
        if match:
            aligned[i] = sidecar.get(int(match.group(1)), {})
    return original, aligned, None


@dataclass
class Block:
    rows: list
    indices: list
    text: str
    page: int | None
    y: float | None
    x: float | None
    right: float | None
    font: float | None
    flags: int
    eligible: bool
    bullet: bool


def blocks(rows, sidecar):
    result = []
    for i, row in enumerate(rows):
        if not result or row['block'] != result[-1].rows[0]['block']:
            result.append(Block([], [], '', None, None, None, None, None, 0, False, False))
        result[-1].rows.append(row)
        result[-1].indices.append(i)
    for block in result:
        visible = [(i, r) for i, r in zip(block.indices, block.rows) if r['text'].strip()]
        block.text = ''.join(r['text'] for r in block.rows).strip()
        positioned = [sidecar.get(i, {}) for i, r in visible]
        owners = {f.get('owner') for f in positioned}
        ys = {f.get('y') for f in positioned}
        pages = {f.get('page') for f in positioned}
        block.eligible = (bool(visible) and len(owners) == len(ys) == len(pages) == 1 and
                          None not in owners and None not in ys and None not in pages and
                          all(r['row'] is None and not r['src'] for r in block.rows) and
                          all(r['tag'] == 'div' for r in block.rows))
        if not block.eligible:
            continue
        block.page, block.y = next(iter(pages)), next(iter(ys))
        xs = [f['x'] for f in positioned if f.get('x') is not None]
        rights = [f['right'] for f in positioned if f.get('right') is not None]
        block.x = min(xs) if xs else None
        block.right = max(rights) if rights else None
        body = [(r, f) for (_, r), f in zip(visible, positioned)
                if not re.fullmatch(r'[•●▪◦‣\s]+', r['text'])]
        if body:
            sizes = Counter()
            weights = Counter()
            for r, _ in body:
                sizes[r['font_size']] += len(r['text'])
                weights[r['flags']] += len(r['text'])
            block.font = sizes.most_common(1)[0][0]
            block.flags = weights.most_common(1)[0][0]
        block.bullet = bool(BULLET.match(block.text))
    return result


def join_decision(a, b, paragraph, mode, common_font=None):
    if not a.eligible or not b.eligible or a.page != b.page:
        return None
    if None in (a.y, b.y, a.x, b.x, a.font, b.font):
        return None
    if a.font != b.font or a.flags != b.flags or b.bullet:
        return None
    if PAGE.fullmatch(a.text) or PAGE.fullmatch(b.text) or not a.text or not b.text:
        return None
    if not any(c.isalnum() for c in a.text) or not any(c.isalnum() for c in b.text):
        return None
    step = b.y - a.y
    # At least half an em excludes same-baseline fragments/columns. A maximum
    # of 1.3 em excludes typical paragraph spacing in positioned filings.
    if not .55 * a.font <= step <= 1.3 * a.font:
        return None
    if abs(b.x - a.x) > max(2, .2 * a.font):
        # A hanging bullet indent may start after the marker. Never attach a
        # line returning to the document's body margin to that list item.
        if not paragraph.bullet or b.x < paragraph.x or b.x - paragraph.x > 2.5 * a.font:
            return None
    if len(paragraph.text) + len(b.text) > 6000:
        return None
    if mode == 'geometry':
        return 'geometry'
    # Typography alone joins adjacent independent headings. Require a lexical
    # continuation or a body line that filled the same measured right edge.
    ends_sentence = bool(re.search(r'[.!?;:]\s*[”’"\)]?$', a.text))
    begins_lower = bool(re.match(r'^[a-z]', b.text))
    large = bool(common_font and a.font > 1.2 * common_font)
    heading = bool(a.flags & 1) or large
    if heading:
        if ends_sentence or len(paragraph.text.split()) > 45:
            return None
        if begins_lower or re.search(r'\b(?:of|and|or|the|to|for|with|in|our|a|an)$', a.text, re.I):
            return 'heading continuation'
        if (mode == 'measured' and large and len(a.text.split()) >= 4 and
                len(b.text.split()) <= 3 and len(paragraph.text.split()) <= 20):
            return 'large heading short continuation'
        return None
    if not ends_sentence and begins_lower:
        return 'lowercase continuation'
    # A complete sentence may continue within a paragraph, but a short final
    # line and a capitalized new line provide insufficient evidence to merge.
    if (a.right is not None and b.right is not None and abs(a.right-b.right) < a.font and
            len(a.text) >= 75 and (not ends_sentence or mode == 'measured')):
        return 'filled body line'
    return None


def reconstruct(rows, sidecar, mode='conservative'):
    source = blocks(rows, sidecar)
    sizes = Counter()
    for block in source:
        if block.eligible and block.font:
            sizes[block.font] += len(block.text)
    common_font = sizes.most_common(1)[0][0] if sizes else None
    output, events = [], []
    current, previous = None, None
    for block in source:
        reason = join_decision(previous, block, current, mode, common_font) if previous and current else None
        if reason:
            events.append(dict(reason=reason, before=previous.text, after=block.text,
                               from_block=block.rows[0]['block'], into_block=current.rows[0]['block'],
                               page=block.page, y=block.y, x=block.x, font=block.font))
            current.rows[-1] = dict(current.rows[-1], text=current.rows[-1]['text'].rstrip() + ' ')
            current.rows.extend(dict(r, block=current.rows[0]['block']) for r in block.rows)
            current.text += ' ' + block.text
        else:
            current = Block(list(block.rows), list(block.indices), block.text, block.page,
                            block.y, block.x, block.right, block.font, block.flags,
                            block.eligible, block.bullet)
            output.append(current)
        previous = block
    result = [r for b in output for r in b.rows]
    # The transformation may insert inter-line whitespace, but must preserve
    # every non-whitespace source character, including punctuation and markers.
    signature = lambda rs: re.sub(r'\s+', '', ''.join(r['text'] for r in rs))
    if signature(rows) != signature(result):
        raise AssertionError('Reflow lost or reordered source text')
    return result, events, sum(b.eligible for b in source)
