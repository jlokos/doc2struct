"""types.py - rule types. Plain data, no stage logic. Every type converts to and from JSON-able dicts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .defaults import (DEFAULT_FOOTNOTE_LINES, DEFAULT_FOOTNOTE_REGEX, DEFAULT_POSTAMBLE_LINES,
                       DEFAULT_PREAMBLE_LINES, DEFAULT_REPEAT_THRESHOLD, KNOWN_STYLES, KNOWN_TABLE_STEPS,
                       RESERVED_COLUMNS, STANDARD_REMOVE)


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
    patterns: Tuple[Tuple[str, bool], ...] = STANDARD_REMOVE   # (regex on lowercased text, only_if_link)
    repeat_threshold: Optional[int] = DEFAULT_REPEAT_THRESHOLD  # drop text occurring this often; None = off

    def to_dict(self):
        return {'patterns': [list(p) for p in self.patterns], 'repeat_threshold': self.repeat_threshold}

    @classmethod
    def from_dict(cls, d):
        base = cls()
        pats = d.get('patterns')
        return cls(patterns=tuple((p[0], bool(p[1])) for p in pats) if pats is not None else base.patterns,
                   repeat_threshold=d.get('repeat_threshold', base.repeat_threshold))


@dataclass(frozen=True)
class HeaderRule:
    name: str                          # class, e.g. 'item'
    regex: str                         # matched against the complete lowercased, whitespace-normalized line
    level: int                         # nesting level, 0 = outermost
    requires: Tuple[str, ...] = ()     # styles the first piece must have (see defaults.KNOWN_STYLES)

    def to_dict(self):
        d = {'name': self.name, 'regex': self.regex, 'level': self.level}
        if self.requires:
            d['requires'] = list(self.requires)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d['name'], d['regex'], int(d['level']), tuple(d.get('requires', ())))


@dataclass(frozen=True)
class TableRules:
    steps: Tuple[str, ...] = KNOWN_TABLE_STEPS
    single_row_to_text: bool = True        # a cleaned table with one row becomes text
    title_from_section: bool = True        # a section with exactly one table gives it its title (a copy)
    footnote_regex: Optional[str] = DEFAULT_FOOTNOTE_REGEX   # marker at the start of a footnote; None = off
    footnote_lines: int = DEFAULT_FOOTNOTE_LINES              # continuation lines per footnote
    preamble_lines: int = DEFAULT_PREAMBLE_LINES              # 0 = off
    postamble_lines: int = DEFAULT_POSTAMBLE_LINES            # 0 = off

    def to_dict(self):
        return {'steps': list(self.steps), 'single_row_to_text': self.single_row_to_text,
                'title_from_section': self.title_from_section, 'footnote_regex': self.footnote_regex,
                'footnote_lines': self.footnote_lines, 'preamble_lines': self.preamble_lines,
                'postamble_lines': self.postamble_lines}

    @classmethod
    def from_dict(cls, d):
        base = cls()
        return cls(steps=tuple(d.get('steps', base.steps)),
                   single_row_to_text=d.get('single_row_to_text', base.single_row_to_text),
                   title_from_section=d.get('title_from_section', base.title_from_section),
                   footnote_regex=d.get('footnote_regex', base.footnote_regex),
                   footnote_lines=int(d.get('footnote_lines', base.footnote_lines)),
                   preamble_lines=int(d.get('preamble_lines', base.preamble_lines)),
                   postamble_lines=int(d.get('postamble_lines', base.postamble_lines)))


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

    def validate(self):
        for h in self.headers:
            re.compile(h.regex)
            bad = [s for s in h.requires if s not in KNOWN_STYLES]
            if bad:
                raise ValueError(f'header rule {h.name!r}: unknown style(s) {bad}; known: {KNOWN_STYLES}')
        if self.tables.footnote_regex:
            re.compile(self.tables.footnote_regex)
        bad = [s for s in self.tables.steps if s not in KNOWN_TABLE_STEPS]
        if bad:
            raise ValueError(f'unknown table step(s) {bad}; known: {KNOWN_TABLE_STEPS}')
        names = [c.name for c in self.columns]
        for n in names:
            if n in RESERVED_COLUMNS:
                raise ValueError(f'custom column {n!r} reuses a default column name')
        if len(set(names)) != len(names):
            raise ValueError('duplicate custom column name')
        for c in self.columns:
            if c.source not in ('text', 'href', 'src', 'font_size', 'indent', 'flags'):
                raise ValueError(f'custom column {c.name!r}: unknown source {c.source!r}')
            if c.which not in ('first', 'last', 'all'):
                raise ValueError(f'custom column {c.name!r}: which must be first, last or all')
            if c.dtype not in ('str', 'int', 'bool', 'list'):
                raise ValueError(f'custom column {c.name!r}: unknown dtype {c.dtype!r}')
            if c.pattern:
                re.compile(c.pattern)
        return self

    def to_dict(self):
        return {'name': self.name, 'headers': [h.to_dict() for h in self.headers], 'remove': self.remove.to_dict(),
                'tables': self.tables.to_dict(), 'columns': [c.to_dict() for c in self.columns]}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d.get('name', 'custom'),
                   headers=[HeaderRule.from_dict(h) for h in d.get('headers', ())],
                   remove=RemoveRules.from_dict(d.get('remove', {})),
                   tables=TableRules.from_dict(d.get('tables', {})),
                   columns=[CustomColumn.from_dict(c) for c in d.get('columns', ())]).validate()
