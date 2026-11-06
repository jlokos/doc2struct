"""Cleanup preserves repetition and page-label behavior across cache sizes."""
import unittest

import doc2struct as d


class CleanupCache(unittest.TestCase):
    def test_styled_repetitions_across_cache_boundary(self):
        rules = {'remove': {'repeat_threshold': 3, 'page_label_regex': None}}
        for count in (31, 32, 33, 100):
            with self.subTest(count=count):
                parts = []
                for index in range(count):
                    text = 'Café ΣΟΣ' if index % 2 == 0 else f'ordinary paragraph {index}.'
                    font = 14 if index % 2 == 0 else 12
                    parts.append(f'<p style="font-size:{font}px">{text}</p>')
                html = ''.join(parts).encode()
                rows = d.parse_html(html, rules)
                repeated = [row for row in rows if row['text'] == 'Café ΣΟΣ']
                self.assertEqual(len(repeated), (count + 1) // 2)
                self.assertTrue(all(row['type'] == 'redundant' for row in repeated))
                instructions = d.convert_html_to_instructions(html, rules)
                self.assertEqual(rows, d.convert_instructions_to_standardized_text(instructions, rules))

    def test_page_labels_and_semantic_heading(self):
        for count in (31, 32, 33):
            with self.subTest(count=count):
                html = (b'<p>Page 1</p><p>Page 2</p><p>Page 3</p>' +
                        b'<p>ordinary body.</p>' * (count - 4) + b'<h1 style="font-weight:bold">Page 4</h1>')
                rules = {'remove': {'repeat_threshold': None, 'page_label_regex': '^page [0-9]+$'}}
                rows = d.parse_html(html, rules)
                self.assertTrue(all(row['type'] == 'redundant' for row in rows if row['text'] in
                                    ('Page 1', 'Page 2', 'Page 3')))
                self.assertEqual(next(row['type'] for row in rows if row['text'] == 'Page 4'), 'title')


if __name__ == '__main__':
    unittest.main()
