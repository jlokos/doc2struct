"""Postamble attachment preserves following-table reservations and limits."""
import unittest

import doc2struct as d


TABLE = b'<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>'
RULES = {
    'remove': {'patterns': [], 'repeat_threshold': None, 'page_label_regex': None},
    'tables': {'steps': [], 'single_row_to_text': False, 'title_from_section': False,
               'preamble_lines': 0, 'footnote_lines': 0, 'postamble_lines': 7},
}


class TableAttachments(unittest.TestCase):
    def test_postamble_stops_at_title_and_reserves_following_table(self):
        for tail, postamble, ambiguous in [
            (b'<p>one.</p><p>two.</p>', 'one. two.', False),
            (b'<p>one.</p><p>two.</p>' + TABLE, None, True),
            (b'<p>one.</p><h1>Title</h1><p>two.</p>', 'one.', False),
        ]:
            rows = d.parse_html(TABLE + tail, RULES)
            self.assertEqual(rows[1]['postamble'], postamble)
            self.assertEqual('ambiguous_text_attachment' in rows[1]['cleaned'], ambiguous)

    def test_zero_limit_leaves_trailing_text(self):
        rules = RULES | {'tables': RULES['tables'] | {'postamble_lines': 0}}
        rows = d.parse_html(TABLE + b'<p>one.</p><p>two.</p>', rules)
        self.assertIsNone(rows[1]['postamble'])
        self.assertEqual(rows[2]['text'], 'one. two.')


if __name__ == '__main__':
    unittest.main()
