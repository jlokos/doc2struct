"""Prepare configuration at the Python boundary; document processing stays in C.

Patterns run on PCRE2 in UTF/UCP mode. Bundled presets are supported; custom
patterns using Python-specific regex extensions may require adjustment.
"""
from functools import lru_cache
import json

try:
    from . import _native
except ImportError as exc:
    raise ImportError(
        'doc2struct requires its C extension. Build it with '
        '`python -m pip install -e ./python` from the repository root.'
    ) from exc

from .rules import Rules, load_rules, list_namespaces


@lru_cache(maxsize=128)
def _compile(serialized):
    return _native.prepare_rules(serialized)


@lru_cache(maxsize=128)
def _preset(source):
    return _native.prepare_preset(source)


@lru_cache(maxsize=1)
def _default():
    return _native.prepare_preset(None)


def prepare(rules):
    if rules is None:
        return _default()
    if isinstance(rules, str) and rules.partition(':')[0].strip().upper() in list_namespaces():
        return _preset(rules)
    resolved = load_rules(rules)
    return _compile(json.dumps(resolved.to_dict(), ensure_ascii=False))
