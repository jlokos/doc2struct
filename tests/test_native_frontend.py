"""Parity checks for native tokenizer and line-builder fast paths.

Run with: python -m unittest discover -s tests
"""
import unittest

from doc2struct import (
    NormalizerOptions,
    convert_instructions_to_standardized_text,
    normalize,
    parse_html,
    tokenize,
)


class NativeFrontendTests(unittest.TestCase):
    def assert_staged_parity(self, html, options=NormalizerOptions()):
        instructions = normalize(tokenize(html), options)
        for rules in (None, "SEC:10-K"):
            with self.subTest(rules=rules):
                self.assertEqual(
                    parse_html(html, rules, options),
                    convert_instructions_to_standardized_text(instructions, rules),
                )

    def test_sampled_fingerprint_collisions(self):
        # Same length and identical first/middle/last sampled words, but the
        # unsampled font size changes. A fingerprint alone cannot authorize reuse.
        padding = "x" * 160
        fragment = (
            f'<p style="font-size:12px;unused:{padding}">ordinary text.</p>'
            f'<p style="font-size:18px;unused:{padding}">Larger heading</p>'
        )
        self.assert_staged_parity(("<body>" + fragment * 180).encode())

    def test_template_quotes_entities_and_visibility(self):
        fragment = (
            '<p style="unused:a > b;font-size:12px">ordinary text.</p>'
            '<p style="unused:a > b;font-size:18px">Larger heading</p>'
            '<p style="display:none"><span>hidden</span><div>visible</div>'
            '<span hidden>attribute hidden</span>'
            '<span style="visibility:hidden">visibility hidden</span>'
            '<a href="a&amp;b">link</a><img alt="A&amp;B" src="x&amp;y"/>'
        )
        html = ("<body>" + fragment * 200).encode()
        self.assert_staged_parity(html)
        self.assert_staged_parity(
            html, NormalizerOptions(hide_hidden_attr=True, hide_visibility=True)
        )

    def test_stack_reallocation_and_implied_closes(self):
        nested = '<span style="font-size:18px">' + "<b>" * 80
        nested += "Heading" + "</b>" * 80 + "</span>"
        fragment = (
            nested + '<p>one<div>two</div><ul><li>A<li>B</ul>'
            '<table><tr><td rowspan=2>A<td>B<tr><td>C</table>'
        )
        self.assert_staged_parity("<body>" + fragment * 100)

    def test_closing_tag_spellings(self):
        # The fast path handles only the ordinary lowercase form. Other forms
        # still use the tokenizer's original quote and name rules.
        variants = [
            "</span>", "</SPAN>", "</span >", "</span x='>'>",
            "</span/>", "</span", "</span\u00a0>", "</span\x00>",
        ]
        for closing in variants:
            with self.subTest(closing=closing):
                self.assert_staged_parity(
                    '<body><p><span style="font-weight:bold">A' + closing + "B</p>"
                )
        self.assertEqual(
            list(tokenize("<p>A</p><SPAN>B</SPAN>")),
            list(tokenize("<p>A</p ><SPAN>B</SPAN>")),
        )

    def test_custom_blank_set(self):
        # Vertical tab, form feed, and other Unicode spaces are deliberately
        # meaningful to this stage, unlike its six custom blank characters.
        blank = " \t\n\r\u00a0\u200b"
        visible = "\v\f\x1c\x00\u0085\u2003\u202f\ufffd"
        for text in [blank, "", "a", blank + "a" + blank, *visible]:
            with self.subTest(text=text):
                self.assert_staged_parity(
                    f"<body><p>{text}</p><p>A<b>{text}</b>B</p>"
                    f"<table><tr><td>{text}<td>X<tr><td>Y<td>Z</table>"
                )


if __name__ == "__main__":
    unittest.main()
