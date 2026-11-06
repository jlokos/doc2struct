"""Public instruction dictionaries retain their ordering and error behavior."""
import unittest

import doc2struct as d
from doc2struct.html_token_normalizer import COLUMNS


class InstructionBoundary(unittest.TestCase):
    def test_exported_keys_keep_order_and_rows_are_independent(self):
        rows = d.convert_html_to_instructions(b'<p>first</p><p>second</p>')
        for row in rows:
            self.assertEqual(tuple(row), COLUMNS)
        rows[0]['text'] = 'changed'
        self.assertEqual(rows[1]['text'], 'second')
        self.assertEqual(d.convert_html_to_instructions(b'<p>first</p>')[0]['text'], 'first')

    def test_missing_required_fields_keep_key_errors(self):
        run = d.convert_html_to_instructions(b'<table><tr><td>value</td></tr></table>')[0]
        for field in COLUMNS:
            if field == 'tag':
                continue
            with self.subTest(field=field):
                incomplete = dict(run)
                del incomplete[field]
                with self.assertRaises(KeyError) as error:
                    d.convert_instructions_to_standardized_text([incomplete])
                self.assertEqual(error.exception.args, ('missing field: ' + field,))

    def test_optional_tag_and_dictionary_subclasses(self):
        class Dictionary(dict):
            def __getitem__(self, key):
                raise AssertionError('Native dictionary lookup must retain its existing behavior')

        runs = d.convert_html_to_instructions(b'<p>ordinary content.</p>')
        expected = d.convert_instructions_to_standardized_text(runs)
        self.assertEqual(d.convert_instructions_to_standardized_text([Dictionary(runs[0])]), expected)
        del runs[0]['tag']
        self.assertEqual(d.convert_instructions_to_standardized_text(runs), expected)

    def test_failed_conversion_does_not_affect_the_next_call(self):
        runs = d.convert_html_to_instructions(b'<p>ordinary content.</p>')
        expected = d.convert_instructions_to_standardized_text(runs)
        for _ in range(20):
            with self.assertRaisesRegex(TypeError, 'expected a dictionary'):
                d.convert_instructions_to_standardized_text([None])
            self.assertEqual(d.convert_instructions_to_standardized_text(runs), expected)


if __name__ == '__main__':
    unittest.main()
