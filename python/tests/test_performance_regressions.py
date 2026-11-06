"""Behavioral coverage for stack summaries, table growth and text assembly.

Run against an installed build: python -m unittest discover -s python/tests
Timings belong in benchmark_performance.py, not in machine-dependent assertions.
"""
import unittest

import doc2struct as d


class SpanBounds(unittest.TestCase):
    def test_single_digit_spans_obey_the_configured_limit(self):
        for cap in [1, 3, 100]:
            for value in range(1, 10):
                with self.subTest(cap=cap, value=value):
                    html = f'<table><tr><td colspan="{value}">value</td></tr></table>'.encode()
                    runs = d.convert_html_to_instructions(html, {'adapters': {'html': {'max_span': cap}}})
                    run = next(run for run in runs if run['text'] == 'value')
                    width = min(value, cap)
                    self.assertEqual(run['span'], f'1x{width}' if width > 1 else None)


class PerformanceRegressions(unittest.TestCase):
    def test_tokenizer_vector_boundaries(self):
        for width in range(66):
            with self.subTest(width=width):
                html = b'<p>' + b'x' * width + b'&amp; mid &lt; end</p><p>&quot;tail</p>'
                texts = [text for kind, text, _ in d.tokenize(html) if kind == 0]
                self.assertEqual(texts, ['x' * width + '& mid < end', '"tail'])
                html = b'<p style="padding-left:' + b' ' * width + b'12px">value</p>'
                self.assertEqual(d.convert_html_to_instructions(html)[0]['indent'], 12)

    def test_many_fragments_keep_exact_text(self):
        html = b'<p>' + b'<span>fragment </span>' * 8192 + b'</p>'
        runs = d.convert_html_to_instructions(html)
        rows = d.convert_instructions_to_standardized_text(runs)
        self.assertEqual(rows[1]['text'], ('fragment ' * 8192).strip())
        self.assertEqual(rows, d.parse_html(html))

    def test_style_merges_keep_link_order_and_images(self):
        html = (b'<p><a href="a">first </a><b><a href="b">bold </a></b>'
                b'<a href="c">last</a><img src="x" alt="pic">after</p>')
        rules = {'columns': [
            {'name': 'links', 'source': 'href', 'dtype': 'list', 'which': 'all'},
            {'name': 'sources', 'source': 'src', 'dtype': 'list', 'which': 'all'},
            {'name': 'styles', 'source': 'flags', 'dtype': 'list', 'which': 'all'},
        ]}
        rows = d.convert_instructions_to_standardized_text(d.convert_html_to_instructions(html), rules)
        self.assertEqual([row['type'] for row in rows], ['title', 'text', 'image'])
        self.assertEqual(rows[1]['text'], 'first bold lastafter')
        self.assertEqual(rows[1]['links'], ['a', 'b', 'c'])
        self.assertEqual(rows[1]['styles'], ['0', '0'])
        self.assertEqual(rows[2]['text'], 'pic')
        self.assertEqual(rows[2]['sources'], ['x'])
        self.assertEqual(rows, d.parse_html(html, rules))

    def test_relocated_item_arrays_preserve_first_run_metadata(self):
        runs = [dict(block=0, line=0, row=None, col=None, span=None, text=f'piece{i} ',
                     flags=0, font_size=float(10 + i), indent=float(i), href=f'/{i}',
                     tag='p', src=None) for i in range(80)]
        runs.append(dict(runs[0], text='end', href='/end'))
        rules = {'header_styles': [], 'columns': [
            {'name': 'links', 'source': 'href', 'dtype': 'list', 'which': 'all'},
            {'name': 'font', 'source': 'font_size', 'dtype': 'int'},
            {'name': 'indent', 'source': 'indent', 'dtype': 'int'},
        ]}
        rows = d.convert_instructions_to_standardized_text(runs, rules)
        self.assertEqual(rows[1]['text'], ''.join(f'piece{i} ' for i in range(80)) + 'end')
        self.assertEqual(rows[1]['links'], [f'/{i}' for i in range(80)] + ['/end'])
        self.assertEqual(rows[1]['font'], 10)
        self.assertEqual(rows[1]['indent'], 0)

    def test_table_growth_preserves_rowspan_occupancy(self):
        for width in (31, 32, 33, 63, 64, 65, 129):
            with self.subTest(width=width):
                html = (b'<table><tr>' + b'<td rowspan="2">span</td>' * width +
                        b'</tr><tr><td>tail</td></tr></table>')
                runs = d.convert_html_to_instructions(html)
                self.assertEqual([run['col'] for run in runs[:-1]], list(range(width)))
                self.assertEqual(runs[-1]['col'], width)
                self.assertEqual(runs[-1]['row'], 1)
                self.assertTrue(all(run['span'] == '2x1' for run in runs[:-1]))
                self.assertEqual(d.parse_html(html), d.convert_instructions_to_standardized_text(runs))

    def test_table_occupancy_resets_between_tables(self):
        html = (b'<table><tr><td rowspan="3" colspan="65">wide</table>'
                b'<table><tr><td>fresh</table>')
        runs = d.convert_html_to_instructions(html)
        self.assertEqual((runs[-1]['row'], runs[-1]['col']), (0, 0))

    def test_alternating_table_sizes_keep_cells_independent(self):
        tables = []
        expected = []
        for index, width in enumerate([129, 2, 3, 65, 1, 129]):
            cells = [[f'{index}:{row}:{col}' for col in range(width)] for row in range(2)]
            expected.append(cells)
            tables.append('<table>' + ''.join('<tr>' + ''.join(
                '<td>' + cell + '</td>' for cell in row) + '</tr>' for row in cells) + '</table>')
        html = ''.join(tables).encode()
        rules = {'tables': {'steps': [], 'single_row_to_text': False}}
        rows = d.parse_html(html, rules)
        matrices = [row['matrix'] for row in rows if row['type'] == 'table']
        self.assertEqual(matrices, expected)
        self.assertEqual(rows, d.convert_instructions_to_standardized_text(
            d.convert_html_to_instructions(html, rules), rules))
        matrices[-1][0][0] = 'changed'
        self.assertEqual(matrices[0], expected[0])

    def test_occupancy_resets_after_cells_without_row_tags(self):
        for first in [b'<td rowspan="3" colspan="129">wide',
                      b'<tr><td rowspan="3" colspan="129">wide</tr>']:
            html = (b'<table>' + first + b'</table>' +
                    b'<table><td>fresh</table>' +
                    b'<table><tr><td rowspan="2" colspan="129">wide again</tr>'
                    b'<tr><td>tail</table>')
            runs = d.convert_html_to_instructions(html)
            self.assertEqual((runs[1]['row'], runs[1]['col']), (0, 0))
            self.assertEqual((runs[-1]['row'], runs[-1]['col']), (1, 100))

    def test_unmatched_closing_tag_cache_is_invalidated_by_push(self):
        html = (b'<div>' * 128 + b'</b><b><span>bold</b>plain</span>' + b'</div>' * 128)
        with d.Parser(65536) as parser:
            for _ in range(2):
                runs = d.convert_html_to_instructions(html)
                self.assertEqual([(run['text'], run['flags']) for run in runs],
                                 [('bold', 1), ('plain', 0)])
                self.assertEqual(parser.parse_html(html), d.parse_html(html))

    def test_table_barrier_does_not_record_a_global_tag_miss(self):
        html = (b'<div>' * 128 +
                b'<b><table><tr><td>cell</b></td></tr></table><span></b>plain</span>' +
                b'</div>' * 128)
        runs = d.convert_html_to_instructions(html)
        self.assertEqual([(run['text'], run['flags']) for run in runs],
                         [('cell', 1), ('plain', 0)])

    def test_implied_closes_restore_ancestor_summary(self):
        html = b'<p><span>one<div>two</div><p>three</p><div>four</div>'
        runs = d.convert_html_to_instructions(html)
        self.assertEqual([(run['block'], run['text'], run['tag']) for run in runs],
                         [(0, 'one', 'p'), (1, 'two', 'div'), (2, 'three', 'p'), (3, 'four', 'div')])
        self.assertEqual(d.parse_html(html)[1]['text'], 'one two three four')

    def test_suppressed_frames_and_table_barriers(self):
        html = (b'<p hidden><span>hidden</span><div>visible</div>'
                b'<table><tr><td><p>cell<p>next</td></tr></table><p>last')
        rules = {'adapters': {'html': {'hide_hidden_attr': True}}}
        runs = d.convert_html_to_instructions(html, rules)
        self.assertEqual([run['text'] for run in runs], ['visible', 'cell', 'next', 'last'])
        self.assertEqual([run['row'] for run in runs], [None, 0, 0, None])

    def test_deep_html_and_reused_parser(self):
        html = b'<div>' * 10000 + b'<p>deep content.</p>' + b'</div>' * 10000
        with d.Parser(65536) as parser:
            for _ in range(3):
                self.assertEqual(parser.parse_html(html)[1]['text'], 'deep content.')
                self.assertLessEqual(parser.cached_bytes, parser.cache_size)
                parser.clear()
                self.assertEqual(parser.cached_bytes, 0)
                self.assertEqual(parser.parse_html(b'<p>next.</p>')[1]['text'], 'next.')
        self.assertTrue(parser.closed)


if __name__ == '__main__':
    unittest.main()
