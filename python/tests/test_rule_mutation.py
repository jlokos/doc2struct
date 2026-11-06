"""Preparation must observe mutable rules and edits to configuration files."""
import json
from pathlib import Path
import tempfile
import unittest

import doc2struct as d


HTML = b'<p>ordinary content.</p>'
MARKER = {'name': 'marker', 'source': 'text', 'pattern': '.', 'value': 'changed'}


class RuleMutation(unittest.TestCase):
    def test_rule_object_mutations_remain_visible(self):
        rules = d.Rules()
        original = d.parse_html(HTML, rules)
        self.assertNotIn('marker', original[1])
        rules.columns.append(d.CustomColumn(**MARKER))
        self.assertEqual(d.parse_html(HTML, rules)[1]['marker'], 'changed')
        rules.columns[0] = d.CustomColumn(**dict(MARKER, value='again'))
        self.assertEqual(d.parse_html(HTML, rules)[1]['marker'], 'again')
        rules.columns.clear()
        self.assertNotIn('marker', d.parse_html(HTML, rules)[1])
        self.assertNotIn('marker', original[1])

    def test_dictionary_mutations_remain_visible(self):
        rules = {'columns': []}
        self.assertNotIn('marker', d.parse_html(HTML, rules)[1])
        rules['columns'].append(dict(MARKER))
        self.assertEqual(d.parse_html(HTML, rules)[1]['marker'], 'changed')
        rules['columns'][0]['value'] = 'again'
        self.assertEqual(d.parse_html(HTML, rules)[1]['marker'], 'again')

    def test_file_edits_remain_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rules.json'
            path.write_text(json.dumps({'columns': []}), encoding='utf-8')
            self.assertNotIn('marker', d.parse_html(HTML, str(path))[1])
            path.write_text(json.dumps({'columns': [MARKER]}), encoding='utf-8')
            self.assertEqual(d.parse_html(HTML, str(path))[1]['marker'], 'changed')


if __name__ == '__main__':
    unittest.main()
