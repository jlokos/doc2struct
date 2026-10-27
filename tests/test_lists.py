"""Grouped lists, relative nesting, and preservation of neighboring structure."""
from pathlib import Path
import unittest

from doc2struct import (
    CustomColumn, Rules, convert_instructions_to_standardized_text,
    normalize, parse_html, tokenize,
)


class ListTests(unittest.TestCase):
    def parse(self, html, rules=None):
        instructions = normalize(tokenize(html))
        rows = parse_html(html, rules)
        self.assertEqual(rows, convert_instructions_to_standardized_text(instructions, rules))
        self.assertFalse(any(r['type'] == 'listitem' for r in rows))
        self.assertEqual([r['id'] for r in rows], list(range(len(rows))))
        return rows

    def single_list(self, rows):
        lists = [r for r in rows if r['type'] == 'list']
        self.assertEqual(len(lists), 1)
        row = lists[0]
        self.assertIsNone(row['text'])
        for field in ('cleaned', 'preamble', 'footnotes', 'postamble'):
            self.assertIsNone(row[field])
        self.assertTrue(all(len(item) == 2 and all(isinstance(c, str) for c in item)
                            for item in row['matrix']))
        return row

    def test_consecutive_single_row_tables(self):
        html = '<h1>Opportunities</h1><p>We focus on:</p>'
        for text in ('Building cloud services.', 'Inventing new games.'):
            html += f'<table><tr><td></td><td>•</td><td>{text}</td></tr></table>'
        html += '<p>Our future growth depends on our products.</p>'
        for rules in (None, 'SEC:10-K'):
            with self.subTest(rules=rules):
                rows = self.parse(html, rules)
                row = self.single_list(rows)
                self.assertEqual(row['matrix'], [
                    ['0', '• Building cloud services.'], ['0', '• Inventing new games.'],
                ])
                self.assertEqual(rows[-1]['level'], row['level'])
                self.assertFalse(any(r['type'] == 'table' for r in rows))

    def test_multirow_table_with_empty_rows_and_colspans(self):
        rows = self.parse('''<h1>Steps</h1><table>
            <tr><td></td><td></td><td></td><td></td></tr>
            <tr><td></td><td>•</td><td colspan="2">Investor information</td></tr>
            <tr><td colspan="4"> </td></tr>
            <tr><td></td><td>•</td><td colspan="2">Company reports</td></tr>
            </table>''')
        self.assertEqual(self.single_list(rows)['matrix'], [
            ['0', '• Investor information'], ['0', '• Company reports'],
        ])
        self.assertFalse(any(r['type'] == 'table' for r in rows))

    def test_css_nesting_and_return_to_body(self):
        rows = self.parse('''<h1>Profitability</h1><p>Factors include:</p>
            <div style="padding-left:36pt;text-indent:-18pt">•Volume</div>
            <div style="padding-left:36pt;text-indent:-18pt">•Margin</div>
            <div style="padding-left:54pt;text-indent:-18pt">◦Market factors</div>
            <div style="padding-left:54pt;text-indent:-18pt">◦Component costs</div>
            <div style="padding-left:36pt;text-indent:-18pt">•Fixed costs</div>
            <p>Normal business conditions apply.</p>''')
        row = self.single_list(rows)
        self.assertEqual(row['matrix'], [
            ['0', '•Volume'], ['0', '•Margin'], ['1', '◦Market factors'],
            ['1', '◦Component costs'], ['0', '•Fixed costs'],
        ])
        self.assertEqual(rows[-1]['level'], row['level'])

    def test_native_list_nesting_with_block_children(self):
        rows = self.parse('''<h1>Products</h1><ul>
            <li><p>First product</p><ul><li><b>Nested product</b></li></ul></li>
            <li><div>Second product</div></li></ul><p>Ordinary prose.</p>''')
        row = self.single_list(rows)
        self.assertEqual(row['matrix'], [
            ['0', 'First product'], ['1', 'Nested product'], ['0', 'Second product'],
        ])
        self.assertEqual(rows[-1]['level'], row['level'])

    def test_numbering_and_nonmarkers(self):
        rows = self.parse('''<p>1. First step</p><p>2. Second step</p>
            <p>(a) Another step</p><p>2025. Financial results improved.</p>
            <p>1.25 percent growth.</p><p>U.S. operations grew.</p>''')
        self.assertEqual(self.single_list(rows)['matrix'], [
            ['0', '1. First step'], ['0', '2. Second step'], ['0', '(a) Another step'],
        ])

    def test_numbered_table(self):
        rows = self.parse('''<p>Follow these steps:</p><table>
            <tr><td>(a)</td><td>Read the report</td></tr>
            <tr><td>(b)</td><td>Review the results</td></tr></table>''')
        self.assertEqual(self.single_list(rows)['matrix'], [
            ['0', '(a) Read the report'], ['0', '(b) Review the results'],
        ])

    def test_financial_tables_and_adjacent_footnotes(self):
        rows = self.parse('''<h1>Costs</h1><table>
            <tr><td>Expense</td><td>2025</td></tr>
            <tr><td>• Rent</td><td>$100</td></tr>
            <tr><td>• Wages</td><td>$200</td></tr></table>
            <p>(a) Includes operating expenses.</p>''')
        table = next(r for r in rows if r['type'] == 'table')
        self.assertEqual(table['footnotes'], [['(a)', 'Includes operating expenses.']])
        self.assertFalse(any(r['type'] == 'list' for r in rows))
        rows = self.parse('''<table><tr><td>Expense</td><td>2025</td></tr>
            <tr><td>Rent</td><td>$100</td></tr></table>
            <table><tr><td>(a)</td><td>Includes operating expenses.</td></tr>
            <tr><td>(b)</td><td>Excludes other expenses.</td></tr></table>''')
        table = next(r for r in rows if r['type'] == 'table')
        self.assertEqual([note[0] for note in table['footnotes']], ['(a)', '(b)'])
        self.assertFalse(any(r['type'] == 'list' for r in rows))

    def test_bullets_with_financial_columns_remain_tables(self):
        rows = self.parse('''<table>
            <tr><td>•</td><td>Rent</td><td>$100</td></tr>
            <tr><td>•</td><td>Wages</td><td>$200</td></tr></table>''')
        self.assertEqual(sum(r['type'] == 'table' for r in rows), 1)
        self.assertFalse(any(r['type'] == 'list' for r in rows))
        rows = self.parse('''<table><tr><td>(a)</td><td>Rent</td>
            <td>$100</td></tr></table>''')
        self.assertFalse(any(r['type'] == 'list' for r in rows))

    def test_split_styles_preserve_markers_and_content(self):
        rows = self.parse('''<p><b>•</b> <a href="/first">first item</a></p>
            <p><b>•</b> second item</p>''')
        self.assertEqual(self.single_list(rows)['matrix'], [
            ['0', '• first item'], ['0', '• second item'],
        ])

    def test_list_nesting_resets_at_a_section_boundary(self):
        rows = self.parse('''<h1>First section</h1><p>• First item</p>
            <p style="margin-left:40px">◦ Nested item</p>
            <h1>Second section</h1><p style="margin-left:40px">• New list</p>''')
        lists = [r for r in rows if r['type'] == 'list']
        self.assertEqual(len(lists), 2)
        self.assertEqual(lists[0]['level'], lists[1]['level'])
        self.assertEqual(lists[0]['matrix'], [['0', '• First item'], ['1', '◦ Nested item']])
        self.assertEqual(lists[1]['matrix'], [['0', '• New list']])

    def test_paragraph_separates_lists_and_resets_depth(self):
        rows = self.parse('''<p>• First list</p><p>Explanatory paragraph.</p>
            <p style="margin-left:40px">• Second list</p>''')
        self.assertEqual([r['type'] for r in rows[1:]], ['list', 'text', 'list'])
        self.assertEqual(rows[1]['matrix'], [['0', '• First list']])
        self.assertEqual(rows[3]['matrix'], [['0', '• Second list']])
        self.assertEqual(rows[1]['level'], rows[3]['level'])

    def test_single_item_stays_a_list_and_uses_existing_columns(self):
        rows = self.parse('<p>• Only item</p>')
        row = self.single_list(rows)
        self.assertEqual(row['matrix'], [['0', '• Only item']])
        self.assertEqual(set(row), set(rows[0]))

    def test_images_stay_in_order_between_list_blocks(self):
        rows = self.parse('''<ul><li>First<img src="logo.png" alt="Logo"></li>
            <li><ul><li>Nested</li></ul></li><li>Last</li></ul>''')
        self.assertEqual([r['type'] for r in rows[1:]], ['list', 'image', 'list'])
        self.assertEqual(rows[1]['matrix'], [['0', 'First']])
        self.assertEqual(rows[2]['text'], 'Logo')
        self.assertEqual(rows[3]['matrix'], [['1', 'Nested'], ['0', 'Last']])

    def test_markers_and_repeated_list_items_survive_cleaning(self):
        rows = self.parse('<p>● Required disclosure.</p>' * 25)
        row = self.single_list(rows)
        self.assertEqual(row['matrix'], [['0', '● Required disclosure.']] * 25)

    def test_demoted_table_is_not_header_evidence(self):
        rows = self.parse('<table><tr><td>ordinary sentence.</td></tr></table>')
        self.assertEqual([(r['type'], r['text']) for r in rows[1:]],
                         [('text', 'ordinary sentence.')])

    def test_list_boundaries_stop_table_absorption(self):
        rows = self.parse('''<h1>Results</h1><table>
            <tr><td>Metric</td><td>2025</td></tr>
            <tr><td>Revenue</td><td>100</td></tr></table>
            <p>• Read the financial statements.</p><p>• Review the notes.</p>''')
        self.assertEqual(self.single_list(rows)['matrix'], [
            ['0', '• Read the financial statements.'], ['0', '• Review the notes.'],
        ])
        self.assertIsNone(next(r for r in rows if r['type'] == 'table')['postamble'])

    def test_custom_columns_and_bold_list_items(self):
        rules = Rules(columns=[CustomColumn('links', 'href', dtype='list', which='all')])
        rows = self.parse('''<table><tr><td>•</td><td><b>
            <a href="/report">Read the report</a></b></td></tr></table>
            <table><tr><td>•</td><td><a href="/notes">Read the notes</a></td></tr></table>''', rules)
        row = self.single_list(rows)
        self.assertIn('/report', row['links'])
        self.assertIn('/notes', row['links'])
        self.assertEqual(row['class'], 'list')

    def test_real_filings(self):
        root = Path(__file__).resolve().parents[1] / 'data/filings/many_10k'
        checks = [
            ('2021-07-29/000156459021039151/msft-10k_20210630.htm',
             'Inventing new gaming experiences'),
            ('2004-03-12/000095012404000885/k83502e10vk.htm', 'Investor Information'),
            ('2026-02-11/000003799626000015/f-20251231.htm', 'Wholesale unit volumes'),
        ]
        for name, text in checks:
            path = root / name
            if not path.exists():
                continue
            with self.subTest(filing=name):
                rows = self.parse(path.read_bytes(), 'SEC:10-K')
                self.assertTrue(any(text in item_text for r in rows if r['type'] == 'list'
                                    for depth, item_text in r['matrix']))


if __name__ == '__main__':
    unittest.main()
