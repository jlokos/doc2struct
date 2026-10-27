"""
rules - every judgment the pipeline makes, as data.

    rules = load_rules('sec_10k')                      # a bundled preset
    rules = load_rules('path/to/my_rules.json')        # your own file
    rules = load_rules('sec_10k', extend={...})        # a preset plus extra rules
    rules = load_rules({...})                          # a dict

A rule file lists only what differs from the defaults (rules/defaults.py). Stage code contains no rule data.
"""
import json
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

from .types import (CustomColumn, HeaderRule, NormalizerOptions, RemoveRules, Rules, TableRules)

PRESET_DIR = Path(__file__).parent / 'presets'


def list_presets():
    return sorted(p.stem for p in PRESET_DIR.glob('*.json'))


def _read(source) -> dict:
    if isinstance(source, dict):
        return source
    p = Path(source)
    if not p.suffix and (PRESET_DIR / f'{source}.json').exists():
        p = PRESET_DIR / f'{source}.json'
    if not p.exists():
        raise FileNotFoundError(f'no rule set {str(source)!r}; bundled presets: {list_presets()}')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def merge(base: Rules, extra: Rules) -> Rules:
    """extra's headers and columns are appended; extra's remove/tables replace base's when they are not default."""
    remove = extra.remove if extra.remove != RemoveRules() else base.remove
    tables = extra.tables if extra.tables != TableRules() else base.tables
    return Rules(name=f'{base.name}+{extra.name}', headers=base.headers + extra.headers, remove=remove,
                 tables=tables, columns=base.columns + extra.columns).validate()


def load_rules(source: Union[str, Path, dict, Rules], extend: Optional[Union[str, Path, dict, Rules]] = None) -> Rules:
    rules = source if isinstance(source, Rules) else Rules.from_dict(_read(source))
    if extend is not None:
        extra = extend if isinstance(extend, Rules) else Rules.from_dict(_read(extend))
        rules = merge(rules, extra)
    return rules


SEC_10K = load_rules('sec_10k')

__all__ = ['load_rules', 'merge', 'list_presets', 'SEC_10K', 'Rules', 'HeaderRule', 'RemoveRules', 'TableRules',
           'CustomColumn', 'NormalizerOptions']