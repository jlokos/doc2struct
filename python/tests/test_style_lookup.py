"""Long style histories retain ordered merges, links, and IEEE font behavior."""
import unittest

import doc2struct as d


RULES = {'columns': [
    {'name': 'links', 'source': 'href', 'dtype': 'list', 'which': 'all'},
    {'name': 'fonts', 'source': 'font_size', 'dtype': 'list', 'which': 'all'},
]}


def runs(fonts, flags=None):
    return [dict(block=0, line=0, row=None, col=None, span=None, text=f'piece{i} ',
                 flags=flags[i] if flags else 0, font_size=font, indent=None,
                 href=f'/{i}', tag='p', src=None) for i, font in enumerate(fonts)]


class StyleLookup(unittest.TestCase):
    def test_truncated_history_and_images_keep_ordered_merges(self):
        source = runs(list(range(1, 81)) + [1] + list(range(100, 141)) + [1])
        source.insert(-2, dict(source[0], text='picture', src='image.png', href=None))
        rows = d.convert_instructions_to_standardized_text(source, RULES)
        expected = ''.join(run['text'] for run in source if run['src'] is None).strip()
        self.assertEqual(rows[1]['text'], expected)
        self.assertEqual(rows[1]['links'], [run['href'] for run in source if run['href'] is not None])
        self.assertEqual(rows[1]['fonts'], ['1.0'])
        self.assertEqual(len(rows), 2)

    def test_nan_fonts_do_not_match(self):
        source = runs([float('nan')] * 80)
        rows = d.convert_instructions_to_standardized_text(source, RULES)
        self.assertEqual(rows[1]['fonts'], ['nan'] * 80)
        self.assertEqual(rows[1]['text'], ''.join(run['text'] for run in source).strip())

    def test_signed_zero_fonts_match(self):
        source = runs([0.0] + list(range(1, 81)) + [-0.0])
        rows = d.convert_instructions_to_standardized_text(source, RULES)
        self.assertEqual(rows[1]['fonts'], ['0.0'])
        self.assertEqual(rows[1]['text'], ''.join(run['text'] for run in source).strip())

    def test_infinite_fonts_match(self):
        source = runs([float('inf')] + list(range(1, 81)) + [float('inf')])
        rows = d.convert_instructions_to_standardized_text(source, RULES)
        self.assertEqual(rows[1]['fonts'], ['inf'])
        self.assertEqual(rows[1]['text'], ''.join(run['text'] for run in source).strip())

    def test_colliding_flag_summaries_keep_exact_comparisons(self):
        source = runs([None] * 81, [64 * i for i in range(80)] + [0])
        rows = d.convert_instructions_to_standardized_text(source, RULES)
        self.assertEqual(rows[1]['text'], ''.join(run['text'] for run in source).strip())
        self.assertEqual(rows[1]['links'], [run['href'] for run in source])


if __name__ == '__main__':
    unittest.main()
