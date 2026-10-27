"""
rules - every judgment the pipeline makes, as data.

    rules = load_rules('SEC:10-K')                     # a form in a bundled rule pack: NAMESPACE:FORM
    rules = load_rules('path/to/my_rules.json')        # your own file
    rules = load_rules('SEC:10-K', extend={...})       # a bundled form plus extra rules
    rules = load_rules({...})                          # a dict

A rule pack (rules/presets/*.json) is one file for a family of documents:

    {"namespace": "SEC",
     "rule_sets": {"10k": {"headers": [...]}, ...},     # named rule sets; anything a Rules dict can hold
     "forms":     {"10-K": "10k", "10-K/A": "10k", ...}} # form name -> rule set

Form names match case-insensitively. A rule set lists only what differs from the defaults (rules/defaults.py).
Stage code contains no rule data.
"""
import json
from pathlib import Path
from typing import Optional, Union

from .types import (CustomColumn, HeaderRule, NormalizerOptions, RemoveRules, Rules, TableRules)

PRESET_DIR = Path(__file__).parent / 'presets'
_PACKS = None


def _packs() -> dict:
    """{NAMESPACE: pack dict}, read once from rules/presets/*.json"""
    global _PACKS
    if _PACKS is None:
        _PACKS = {}
        for p in sorted(PRESET_DIR.glob('*.json')):
            with open(p, encoding='utf-8') as f:
                pack = json.load(f)
            ns = pack['namespace'].upper()
            if ns in _PACKS:
                raise ValueError(f'namespace {ns!r} is defined by more than one file in {PRESET_DIR}')
            missing = sorted({s for s in pack['forms'].values() if s not in pack['rule_sets']})
            if missing:
                raise ValueError(f'{p.name}: forms point at unknown rule sets {missing}')
            pack['_forms_upper'] = {k.upper(): v for k, v in pack['forms'].items()}
            _PACKS[ns] = pack
    return _PACKS


def list_namespaces():
    return sorted(_packs())


def list_forms(namespace: str):
    pack = _packs().get(namespace.upper())
    if pack is None:
        raise KeyError(f'unknown namespace {namespace!r}; known: {list_namespaces()}')
    return list(pack['forms'])


def _from_pack(namespace: str, form: str) -> Rules:
    pack = _packs()[namespace.upper()]
    set_name = pack['_forms_upper'].get(form.strip().upper())
    if set_name is None:
        raise KeyError(f'no form {form!r} in {namespace.upper()}; known forms: {list_forms(namespace)}')
    d = dict(pack['rule_sets'][set_name])
    d['name'] = f'{namespace.upper()}:{form.strip().upper()}'
    return Rules.from_dict(d)


def _read(source) -> dict:
    if isinstance(source, dict):
        return source
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f'no rules file {str(source)!r}; bundled rules are named NAMESPACE:FORM, '
                                f'namespaces: {list_namespaces()}')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _resolve(source) -> Rules:
    if isinstance(source, Rules):
        return source
    if isinstance(source, str) and ':' in source:
        ns, form = source.split(':', 1)
        if ns.strip().upper() in _packs():
            return _from_pack(ns.strip(), form)
    return Rules.from_dict(_read(source))


def merge(base: Rules, extra: Rules) -> Rules:
    """extra's headers and columns are appended; extra's remove/tables replace base's when they are not default."""
    remove = extra.remove if extra.remove != RemoveRules() else base.remove
    tables = extra.tables if extra.tables != TableRules() else base.tables
    return Rules(name=f'{base.name}+{extra.name}', headers=base.headers + extra.headers, remove=remove,
                 tables=tables, columns=base.columns + extra.columns).validate()


def load_rules(source: Union[str, Path, dict, Rules], extend: Optional[Union[str, Path, dict, Rules]] = None) -> Rules:
    rules = _resolve(source if not isinstance(source, Path) else str(source))
    if extend is not None:
        rules = merge(rules, _resolve(extend if not isinstance(extend, Path) else str(extend)))
    return rules


__all__ = ['load_rules', 'merge', 'list_namespaces', 'list_forms', 'Rules', 'HeaderRule', 'RemoveRules', 'TableRules',
           'CustomColumn', 'NormalizerOptions']