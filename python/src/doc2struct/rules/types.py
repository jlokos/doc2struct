"""types.py - rule types. Plain data, no stage logic. Every type converts to and from JSON-able dicts."""
from __future__ import annotations

import json
from .. import _native
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .defaults import (DEFAULT_HEADER_STYLES, DEFAULT_FOOTNOTE_LINES, DEFAULT_FOOTNOTE_REGEX, DEFAULT_POSTAMBLE_LINES,
                       DEFAULT_PREAMBLE_LINES, DEFAULT_REPEAT_THRESHOLD, KNOWN_STYLES, KNOWN_TABLE_STEPS,
                       RESERVED_COLUMNS, STANDARD_REMOVE, DEFAULT_SINGLE_ROW_TO_TEXT, DEFAULT_PAGE_LABEL_REGEX,
                       DEFAULT_TITLE_FROM_SECTION, DEFAULT_UNWRAP_LAYOUT, DEFAULT_ANNOTATION_EXCLUDE_REGEX,
                       DEFAULT_LIST_GAP_ROWS, DEFAULT_LIST_TAIL_ROWS)


# -------------------------------------------------------------------------------------------- normalizer
@dataclass(frozen=True)
class NormalizerOptions:
    hide_hidden_attr: bool = False   # also hide elements with the `hidden` attribute
    hide_visibility: bool = False    # also hide visibility:hidden|collapse
    max_span: int = 100              # clamp rowspan/colspan

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


# ------------------------------------------------------------------------------------ standardized text
@dataclass(frozen=True)
class RemoveRules:
    """Legacy configuration name: matches are preserved as redundant rows.

    Page-label candidates also require small type or repeated distinct labels;
    semantic headings and large type are protected.
    """
    patterns: Tuple[Tuple[str, bool], ...] = STANDARD_REMOVE   # (regex on lowercased text, only_if_link)
    repeat_threshold: Optional[int] = DEFAULT_REPEAT_THRESHOLD  # mark text occurring this often; None = off
    page_label_regex: Optional[str] = DEFAULT_PAGE_LABEL_REGEX  # candidate labels; None = off

    def to_dict(self):
        return {'patterns': [list(p) for p in self.patterns], 'repeat_threshold': self.repeat_threshold,
                'page_label_regex': self.page_label_regex}

    @classmethod
    def from_dict(cls, d):
        base = cls()
        pats = d.get('patterns')
        return cls(patterns=tuple((p[0], bool(p[1])) for p in pats) if pats is not None else base.patterns,
                   repeat_threshold=d.get('repeat_threshold', base.repeat_threshold),
                   page_label_regex=d.get('page_label_regex', base.page_label_regex))


@dataclass(frozen=True)
class HeaderRule:
    name: str                          # class, e.g. 'item'
    regex: str                         # matched against the complete lowercased, whitespace-normalized line
    level: int                         # nesting level, 0 = outermost
    requires: Optional[Tuple[str, ...]] = None  # None inherits any shared style; () permits unstyled; otherwise all required

    def to_dict(self):
        d = {'name': self.name, 'regex': self.regex, 'level': self.level}
        if self.requires is not None:
            d['requires'] = list(self.requires)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d['name'], d['regex'], int(d['level']), tuple(d['requires']) if 'requires' in d else None)


@dataclass(frozen=True)
class TableRules:
    steps: Tuple[str, ...] = KNOWN_TABLE_STEPS
    single_row_to_text: bool = DEFAULT_SINGLE_ROW_TO_TEXT  # a cleaned table with one row becomes text
    title_from_section: bool = DEFAULT_TITLE_FROM_SECTION  # a section with exactly one table gives it its title
    footnote_regex: Optional[str] = DEFAULT_FOOTNOTE_REGEX   # marker at the start of a footnote; None = off
    footnote_lines: int = DEFAULT_FOOTNOTE_LINES              # continuation lines per footnote
    preamble_lines: int = DEFAULT_PREAMBLE_LINES              # 0 = off
    postamble_lines: int = DEFAULT_POSTAMBLE_LINES            # 0 = off
    unwrap_layout: bool = DEFAULT_UNWRAP_LAYOUT  # unwrap prose tables containing explicit section headings
    annotation_exclude_regex: Optional[str] = DEFAULT_ANNOTATION_EXCLUDE_REGEX  # keep matching contact lines as text

    def to_dict(self):
        return {'steps': list(self.steps), 'single_row_to_text': self.single_row_to_text,
                'title_from_section': self.title_from_section, 'footnote_regex': self.footnote_regex,
                'footnote_lines': self.footnote_lines, 'preamble_lines': self.preamble_lines,
                'postamble_lines': self.postamble_lines, 'unwrap_layout': self.unwrap_layout,
                'annotation_exclude_regex': self.annotation_exclude_regex}

    @classmethod
    def from_dict(cls, d):
        base = cls()
        return cls(steps=tuple(d.get('steps', base.steps)),
                   single_row_to_text=d.get('single_row_to_text', base.single_row_to_text),
                   title_from_section=d.get('title_from_section', base.title_from_section),
                   footnote_regex=d.get('footnote_regex', base.footnote_regex),
                   footnote_lines=int(d.get('footnote_lines', base.footnote_lines)),
                   preamble_lines=int(d.get('preamble_lines', base.preamble_lines)),
                   postamble_lines=int(d.get('postamble_lines', base.postamble_lines)),
                   unwrap_layout=bool(d.get('unwrap_layout', base.unwrap_layout)),
                   annotation_exclude_regex=d.get('annotation_exclude_regex', base.annotation_exclude_regex))


@dataclass(frozen=True)
class ListRules:
    """Limits count source text rows before ordinary text merging.

    Bridge matching rows between same-level list items, then allow a bounded
    tail on that confirmed chain. Zero max_gap_rows disables inference; zero
    max_tail_rows disables the tail. Matching uses payload style/font/indent.
    """
    max_gap_rows: int = DEFAULT_LIST_GAP_ROWS
    max_tail_rows: int = DEFAULT_LIST_TAIL_ROWS

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        base = cls()
        return cls(max_gap_rows=int(d.get('max_gap_rows', base.max_gap_rows)),
                   max_tail_rows=int(d.get('max_tail_rows', base.max_tail_rows)))


@dataclass(frozen=True)
class CustomColumn:
    name: str                          # must not reuse a default column name
    source: str                        # 'text' or one of: href, src, font_size, indent, flags
    dtype: str = 'str'                 # str | int | bool | list
    pattern: Optional[str] = None      # source 'text': case-insensitive regex, group 1 (else the whole match)
    which: str = 'first'               # first | last | all (all gives a list)
    types: Optional[Tuple[str, ...]] = None   # only for these row types; default: every type except table

    def to_dict(self):
        d = {'name': self.name, 'source': self.source, 'dtype': self.dtype, 'which': self.which}
        if self.pattern is not None:
            d['pattern'] = self.pattern
        if self.types is not None:
            d['types'] = list(self.types)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d['name'], d['source'], d.get('dtype', 'str'), d.get('pattern'), d.get('which', 'first'),
                   tuple(d['types']) if d.get('types') is not None else None)


@dataclass
class Rules:
    name: str = 'default'
    headers: List[HeaderRule] = field(default_factory=list)
    remove: RemoveRules = field(default_factory=RemoveRules)
    tables: TableRules = field(default_factory=TableRules)
    columns: List[CustomColumn] = field(default_factory=list)
    lists: ListRules = field(default_factory=ListRules)
    header_styles: Tuple[str, ...] = DEFAULT_HEADER_STYLES  # any listed style; empty disables the shared gate

    def validate(self):
        _native.prepare_rules(json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False))
        return self

    def to_dict(self):
        return {'name': self.name, 'headers': [h.to_dict() for h in self.headers], 'remove': self.remove.to_dict(),
                'tables': self.tables.to_dict(), 'columns': [c.to_dict() for c in self.columns],
                'lists': self.lists.to_dict(), 'header_styles': list(self.header_styles)}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d.get('name', 'custom'),
                   headers=[HeaderRule.from_dict(h) for h in d.get('headers', ())],
                   remove=RemoveRules.from_dict(d.get('remove', {})),
                   tables=TableRules.from_dict(d.get('tables', {})),
                   columns=[CustomColumn.from_dict(c) for c in d.get('columns', ())],
                   lists=ListRules.from_dict(d.get('lists', {})),
                   header_styles=tuple(d.get('header_styles', DEFAULT_HEADER_STYLES))).validate()
