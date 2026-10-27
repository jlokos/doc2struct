"""Run native standardization on inspectable Python instruction rows.

A list is one row with type="list". Its matrix contains string pairs
[relative_depth, item_text], retaining any source markers in item_text.
The row's level places the whole list in the document; its text is empty.
Before grouping, lists.max_gap_rows bounds matching text rows between list
items. A confirmed chain may absorb lists.max_tail_rows after its last item.
Counts use pre-merge rows and never cross a different type, level or payload
style/font/indent. Set max_gap_rows=0 to disable or max_tail_rows=0 for no tail.

For tables, cleaned is a list of actual cleanup changes and unresolved issues.
An empty list means nothing was recorded, not that the table is verified.
Other row types have cleaned=None.

Text matching the legacy remove rules is retained with type="redundant" in
source order. These rows do not create sections or become table annotations.

After table processing, adjacent text or textsmall rows of the same type and
level are joined with spaces. Type/level changes and all other types end the block.

Adjacent titles at the same level also join when their first source runs match
in style flags, font size and indentation. This runs before table-title inheritance
and retains the first title's classification and every source item's metadata.
"""
from ._engine import _native, prepare

DEFAULT_COLUMNS = ('id', 'level', 'type', 'text', 'matrix', 'cleaned', 'preamble', 'footnotes', 'postamble')
RULE_COLUMNS = ('id', 'level', 'type', 'class', 'standardized_title', 'text', 'matrix', 'cleaned',
                'preamble', 'footnotes', 'postamble')


def convert_instructions_to_standardized_text(instructions, rules=None):
    return _native.standardize(instructions, prepare(rules), rules is not None)
