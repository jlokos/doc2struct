"""Token import keeps generator, optional-attribute, and error semantics."""
import unittest

import doc2struct as d


class TokenAttributeExports(unittest.TestCase):
    def test_self_closing_void_and_nonvoid_tags_keep_token_shapes(self):
        for name in ['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                     'link', 'meta', 'param', 'source', 'track', 'wbr']:
            for spelling in [name, name.upper()]:
                with self.subTest(tag=spelling):
                    tokens = list(d.tokenize(('<' + spelling + '/>').encode()))
                    self.assertEqual([(kind, text) for kind, text, _ in tokens], [(1, name)])
        for name in ['div', 'span', 'custom', 'script', 'style', 'title', 'area2']:
            with self.subTest(tag=name):
                tokens = list(d.tokenize(('<' + name + '/>').encode()))
                self.assertEqual([(kind, text) for kind, text, _ in tokens], [(1, name), (2, name)])

    def test_key_order_and_independent_dicts_across_bulk_threshold(self):
        tag = (b'<a hidden alt="" src="x" href="/?a=1&amp;b=2" rowspan="3" '
               b'colspan="2" style="font-size:12px">t</a>')
        expected = {'style': 'font-size:12px', 'colspan': '2', 'rowspan': '3',
                    'href': '/?a=1&b=2', 'src': 'x', 'alt': '', 'hidden': ''}
        for count in [10, 11, 12, 64]:
            with self.subTest(count=count):
                starts = [attrs for kind, _, attrs in d.tokenize(tag * count) if kind == 1]
                self.assertEqual(len(starts), count)
                for attrs in starts:
                    self.assertEqual(tuple(attrs), tuple(expected))
                    self.assertEqual(attrs, expected)
                starts[0]['href'] = 'changed'
                del starts[0]['style']
                self.assertEqual(starts[1], expected)


class TokenBoundary(unittest.TestCase):
    @staticmethod
    def tokens(count, attrs):
        for _ in range(count):
            yield 1, 'span', attrs
        yield 0, 'payload', None
        for _ in range(count):
            yield 2, 'span', None

    def test_generators_and_optional_attributes_across_key_cache_boundary(self):
        for count in (31, 32, 33, 100):
            with self.subTest(count=count):
                expected = d.normalize(list(self.tokens(count, {})))
                self.assertEqual(d.normalize(self.tokens(count, {})), expected)
                self.assertEqual(d.normalize(self.tokens(count, {'style': None, 'hidden': None})), expected)

    def test_dictionary_subclasses_retain_direct_lookup(self):
        class Dictionary(dict):
            def __getitem__(self, key):
                raise AssertionError('Native import must retain direct dictionary lookup')

        attrs = {'style': 'font-size:12px;font-weight:bold'}
        expected = d.normalize(self.tokens(50, attrs))
        self.assertEqual(d.normalize(self.tokens(50, Dictionary(attrs))), expected)
        self.assertEqual(expected[0]['font_size'], 12)
        self.assertEqual(expected[0]['flags'], 1)

    def test_late_generator_and_attribute_errors_leave_import_usable(self):
        def failing():
            for _ in range(40):
                yield 1, 'span', {}
            raise RuntimeError('late token marker')

        for _ in range(10):
            with self.assertRaisesRegex(RuntimeError, 'late token marker'):
                d.normalize(failing())
            prefix = [(1, 'span', {})] * 40
            with self.assertRaisesRegex(TypeError, 'start token attributes must be a dict'):
                d.normalize(prefix + [(1, 'span', None)])
            with self.assertRaisesRegex(TypeError, 'expected a string'):
                d.normalize(prefix + [(1, 'span', {'style': 42})])
            self.assertEqual(d.normalize([(1, 'p', {}), (0, 'valid', None), (2, 'p', None)])[0]['text'], 'valid')

    def test_exported_attribute_dictionaries_are_independent(self):
        tokens = list(d.tokenize(b'<span style="font-size:12px">x</span>' * 40))
        attrs = [value for kind, _, value in tokens if kind == 1]
        attrs[0]['style'] = 'font-weight:bold'
        self.assertEqual(attrs[1]['style'], 'font-size:12px')
        runs = d.normalize(tokens)
        self.assertEqual(runs[0]['flags'], 1)
        self.assertEqual(runs[1]['flags'], 0)

    def test_exact_and_generic_token_sequences(self):
        class Token:
            def __iter__(self):
                return iter((0, 'payload', None))

        expected = d.normalize([(0, 'payload', None)])
        self.assertEqual(d.normalize([[0, 'payload', None]]), expected)
        self.assertEqual(d.normalize([Token()]), expected)
        for value in ((), [0], (0, 'payload', None, 'extra')):
            with self.assertRaisesRegex(ValueError, 'token must contain three values'):
                d.normalize([value])

    def test_exported_token_tuple_shape(self):
        for kind, text, attrs in d.tokenize(b'<div style="font-weight:bold">text &amp; more</div>'):
            self.assertIs(type(kind), int)
            self.assertIs(type(text), str)
            self.assertIs(type(attrs), dict if kind == 1 else type(None))

    def test_empty_attribute_dictionaries_are_fresh(self):
        tokens = list(d.tokenize(b'<p>payload</p>' * 40))
        attrs = [value for kind, _, value in tokens if kind == 1]
        attrs[0]['href'] = '/changed'
        self.assertEqual(attrs[1], {})


if __name__ == '__main__':
    unittest.main()
