"""Run native standardization on inspectable Python instruction rows."""
from ._engine import _native, prepare

DEFAULT_COLUMNS = ('id', 'level', 'type', 'text', 'matrix', 'cleaned', 'preamble', 'footnotes', 'postamble')
RULE_COLUMNS = ('id', 'level', 'type', 'class', 'standardized_title', 'text', 'matrix', 'cleaned',
                'preamble', 'footnotes', 'postamble')


def convert_instructions_to_standardized_text(instructions, rules=None):
    return _native.standardize(instructions, prepare(rules), rules is not None)
