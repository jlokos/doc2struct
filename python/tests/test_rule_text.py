"""Heading rules normalize whitespace without changing display text."""
import unittest

import doc2struct as d


RULES = {
    'headers': [{'name': 'chosen', 'regex': '^target words$', 'level': 0, 'requires': []}],
    'columns': [{'name': 'matched', 'source': 'text', 'classes': ['chosen'],
                 'pattern': '.*', 'value': 'yes'}],
}


class RuleText(unittest.TestCase):
    def test_ascii_and_unicode_whitespace_matches_heading_rules(self):
        spaces = [' ', '\t', '\n', '\v', '\f', '\r', '\x1c', '\x1d', '\x1e', '\x1f',
                  '\u0085', '\u00a0', '\u1680', '\u2000', '\u2007', '\u200b',
                  '\u2028', '\u2029', '\u202f', '\u205f', '\u3000']
        for separator in spaces:
            with self.subTest(separator=repr(separator)):
                display = 'Target' + separator * 2 + 'Words'
                rows = d.parse_html(('<h1>' + display + '</h1>').encode(), RULES)
                matched = [row for row in rows if row['matched'] == 'yes']
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0]['text'], display)

    def test_non_whitespace_controls_and_letters_do_not_become_spaces(self):
        for separator in ['\x00', '\x01', '\x08', '\x0e', '\x1b', '\x7f', '\u180e', 'Σ', '🙂']:
            with self.subTest(separator=repr(separator)):
                rows = d.parse_html(('<h1>Target' + separator + 'Words</h1>').encode(), RULES)
                self.assertTrue(all(row['matched'] is None for row in rows))


if __name__ == '__main__':
    unittest.main()
