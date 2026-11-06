"""Large exports keep fresh mutable containers, field order, and false values."""
import unittest

import doc2struct as d
from doc2struct.convert_instructions_to_standardized_text import DEFAULT_COLUMNS
from doc2struct.html_token_normalizer import COLUMNS


class ExportRows(unittest.TestCase):
    def test_large_instruction_exports_keep_none_empty_and_zero(self):
        rows = d.convert_html_to_instructions(b'<img src="" alt="">' * 40)
        self.assertEqual(len(rows), 40)
        for row in rows:
            self.assertEqual(tuple(row), COLUMNS)
            self.assertEqual((row['block'], row['line'], row['flags']), (0, 0, 0))
            self.assertEqual((row['text'], row['src']), ('', ''))
            self.assertIsNone(row['span'])
        rows[0]['text'] = 'changed'
        self.assertEqual(rows[1]['text'], '')

    def test_large_exports_keep_custom_column_order_and_false_values(self):
        rules = {'columns': [
            {'name': 'number', 'source': 'flags', 'dtype': 'int'},
            {'name': 'truth', 'source': 'flags', 'dtype': 'bool'},
            {'name': 'label', 'source': 'text', 'pattern': '^$', 'value': ''},
            {'name': 'values', 'source': 'font_size', 'dtype': 'list', 'which': 'all'},
        ]}
        rows = d.parse_html(b'<img src="" alt="">' * 40, rules)
        for row in rows:
            self.assertEqual(tuple(row), DEFAULT_COLUMNS + ('number', 'truth', 'label', 'values'))
        images = [row for row in rows if row['type'] == 'image']
        self.assertEqual(len(images), 40)
        for row in images:
            self.assertEqual(row['number'], 0)
            self.assertIs(row['truth'], False)
            self.assertEqual(row['label'], '')
            self.assertEqual(row['values'], [])
        images[0]['values'].append('changed')
        self.assertEqual(images[1]['values'], [])

    def test_table_lists_and_matrices_remain_independent(self):
        html = b'<table><tr><td>left</td><td>right</td></tr><tr><td>1</td><td>2</td></tr></table>' * 40
        rules = {'tables': {'steps': [], 'title_from_section': False, 'preamble_lines': 0,
                            'postamble_lines': 0, 'footnote_lines': 0}}
        rows = [row for row in d.parse_html(html, rules) if row['type'] == 'table']
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0]['cleaned'], [])
        rows[0]['cleaned'].append('changed')
        rows[0]['matrix'][0][0] = 'changed'
        rows[0]['text'] = 'changed'
        self.assertEqual(rows[1]['cleaned'], [])
        self.assertEqual(rows[1]['matrix'][0][0], 'left')
        self.assertIsNone(rows[1]['text'])


if __name__ == '__main__':
    unittest.main()
