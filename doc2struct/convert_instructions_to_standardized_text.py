"""Run native standardization on inspectable Python instruction rows.

A list is one row with type="list". Its matrix contains string pairs
[relative_depth, item_text], retaining any source markers in item_text.
The row's level places the whole list in the document; its text is empty.

For tables, cleaned is a list of actual cleanup changes and unresolved issues.
An empty list means nothing was recorded, not that the table is verified.
Other row types have cleaned=None.
"""
from ._engine import _native, prepare

DEFAULT_COLUMNS = ('id', 'level', 'type', 'text', 'matrix', 'cleaned', 'preamble', 'footnotes', 'postamble')
RULE_COLUMNS = ('id', 'level', 'type', 'class', 'standardized_title', 'text', 'matrix', 'cleaned',
                'preamble', 'footnotes', 'postamble')


def convert_instructions_to_standardized_text(instructions, rules=None):
    return _native.standardize(instructions, prepare(rules), rules is not None)
