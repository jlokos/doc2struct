"""defaults.py - generic rule values that apply when a rule set does not override them."""

# (regex on the lowercased text, only_if_link)
STANDARD_REMOVE = (
    (r'^\d+$', False),
    (r'^-\d+-$', False),
    (r'(^\s*\d+\s*\||\|\s*\d+\s*$)', False),
    (r'^_+$', False),
    (r'^●(\s*●)*', False),
    (r'^table\s+of\s+contents$', True),
)

DEFAULT_REPEAT_THRESHOLD = 20

# table notes (doc2dict's values)
DEFAULT_FOOTNOTE_REGEX = r'^(\*|\(.{1,2}\)|\d+|†+)'
DEFAULT_FOOTNOTE_LINES = 3       # extra lines without a marker that continue a footnote
DEFAULT_PREAMBLE_LINES = 7       # text lines directly before a table
DEFAULT_POSTAMBLE_LINES = 7      # text lines directly after a table's footnotes

# the table steps the standardized-text stage knows how to run, in the order they run
KNOWN_TABLE_STEPS = (
    'validate_structure', 'merge_formatting_chars', 'remove_empty_rows', 'remove_empty_columns',
    'remove_subset_rows_bottom_to_top', 'remove_subset_rows_top_to_bottom',
    'remove_subset_columns_left_to_right', 'remove_subset_columns_right_to_left', 'merge_duplicate_header_rows_down',
)

# styles a header rule may require of the line's first piece
KNOWN_STYLES = ('bold', 'italic', 'underline', 'centered', 'all_caps', 'proper_case', 'fake_table')

# columns every output already has; custom columns may not reuse them
RESERVED_COLUMNS = ('id', 'level', 'type', 'class', 'standardized_title', 'text', 'matrix', 'cleaned', 'preamble',
                    'footnotes', 'postamble')