"""Text/partial-SGML frontend checks. Run: python checks/python/text.py."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import doc2struct as ds


NO_ANNOTATIONS = {'tables': {'preamble_lines': 0, 'postamble_lines': 0}}


def standardize(content, *, partial=False, rules=NO_ANNOTATIONS):
    convert = ds.convert_partialsgml_to_instructions if partial else ds.convert_text_to_instructions
    return ds.convert_instructions_to_standardized_text(convert(content), rules)


def matrices(rows):
    return [row['matrix'] for row in rows if row['type'] == 'table']


def check_dense_tables():
    source = (Path(__file__).resolve().parents[1] / 'fixtures' / 'partialsgml_tables.txt').read_text()
    runs = ds.convert_partialsgml_to_instructions(source)
    tables = matrices(ds.convert_instructions_to_standardized_text(runs, NO_ANNOTATIONS))
    assert len(tables) == 2
    assert ['Common Stock', '12-22-99', 'M', 'V', 'A', '7.04', '118,250', 'I', '(1)'] in tables[0]
    expected = ['ISO Option', '7.04', '12/22/99', 'V', 'D', '37,591', '7/94', '12/99',
                'Class A', '37,591', '$5.50', '0', 'I', '(1)']
    assert expected in tables[1]
    iso = next(r for r in runs if r['text'] == 'ISO Option')
    assert all(r['span'] is None for r in runs if r['block'] == iso['block'] and r['row'] == iso['row'])
    price = [r for r in runs if r['block'] == iso['block'] and r['text'] == 'to $7.78']
    assert len(price) == 1 and price[0]['col'] == 10
    header = [r for r in runs if r['block'] == iso['block'] and r['row'] < iso['row']]
    parent = [r for r in header if r['col'] == 4 and r['span'] == '1x2']
    assert [r['text'] for r in parent][:4] == ['Number', 'of', 'Deriv-', 'ative']
    assert parent[3]['line'] == parent[2]['line'] + 1
    assert any(r['text'] == 'Title and' and r['span'] == '1x2' and r['col'] == 8 for r in header)
    assert any('Conver-\nsion' in cell for cell in tables[1][0])

    # A currency prefix is not an extra data column, even when right alignment
    # separates the symbol and amount by several character cells.
    money = ('<TABLE>\n<S>                   <C>              <C>\n'
             'Revenue               $    12,922      $    9,562\n'
             'Assets                $    21,341      $   23,599\n'
             'Liabilities           $       183      $      392\n</TABLE>')
    table = matrices(standardize(money, partial=True))[0]
    assert len(table[0]) == 3 and table[0][1].replace(' ', '') == '$12,922'

    # An unsupported formatting marker inside the label column is discarded.
    extra = ('<TABLE>\n<S>                <C>                                 <C>                  <C>                  <C>\n'
             'Net revenues (Note 11)                                 $      12,921,600    $       9,562,700    $      12,518,500\n'
             '     Selling, general and administrative                       3,799,400            3,154,700            3,507,500\n'
             '     Interest income on shareholder notes                              -              (50,700)                   -\n</TABLE>')
    table = matrices(standardize(extra, partial=True))[0]
    assert len(table[0]) == 4
    assert ['Selling, general and administrative', '3,799,400', '3,154,700', '3,507,500'] in table

    # Contradictory body rows survive as text, never as fabricated spans.
    ambiguous = ('<TABLE>\n<S>       <C>\nAlpha     12\nBeta      24\n'
                 'AnUnbrokenDescriptionThatCrossesEveryPossibleBoundary     99\n</TABLE>')
    runs = ds.convert_partialsgml_to_instructions(ambiguous)
    assert any(r['row'] is None and 'AnUnbrokenDescription' in r['text'] for r in runs)


def main():
    check_dense_tables()
    for convert in (ds.convert_text_to_instructions, ds.convert_partialsgml_to_instructions):
        assert convert('') == convert(b'\n\r\n\r\f\t') == []
        assert convert('\ufeffcaf\u00e9\r\nlast line') == convert('caf\u00e9\r\nlast line'.encode())
        assert [r['text'] for r in convert(b'caf\xe9\r\nlast line')] == ['caf\u00e9', 'last line']
        assert [r['line'] for r in convert('one\r\ntwo\rthree\ffour')] == [0, 1, 2, 3]
        assert convert(bytearray(b'last line')) == convert('last line')
        assert convert('\tIndented', tab_size=4)[0]['indent'] == 32
        assert convert(' \tIndented', tab_size=4)[0]['indent'] == 32
        for value in (0, -1, 257):
            try:
                convert('text', tab_size=value)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid tab_size accepted')
        try:
            convert(None)
        except TypeError:
            pass
        else:
            raise AssertionError('non-text accepted')
        for run in convert('Heading\n-------\nbody text.'):
            assert set(run) == {'block', 'line', 'row', 'col', 'span', 'text', 'flags', 'font_size', 'indent', 'href', 'tag', 'src'}
            assert run['font_size'] is None

    # The caller's syntax choice matters, and unknown tags/escaped text survive.
    source = 'before<PAGE>after\n<FIELD> 42\nunfinished <TABLE'
    assert '<PAGE>' in ''.join(r['text'] for r in ds.convert_text_to_instructions(source))
    partial = ds.convert_partialsgml_to_instructions(source)
    assert [r['text'] for r in partial] == ['before', 'after', '<FIELD> 42', 'unfinished <TABLE']
    assert ds.convert_partialsgml_to_instructions('&lt;literal&gt;')[0]['text'] == '&lt;literal&gt;'
    quoted = '<UNKNOWN value="<PAGE>">literal</UNKNOWN>'
    assert ''.join(r['text'] for r in ds.convert_partialsgml_to_instructions(quoted)) == quoted
    assert ''.join(r['text'] for r in ds.convert_partialsgml_to_instructions('before<!-- <TABLE>\n<PAGE> -->after')) == 'beforeafter'

    # A capitalized wrap continuation is still prose; a wrapped explicit heading
    # reaches the standardizer as one complete logical line.
    source = ('ITEM 7. MANAGEMENT DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION\n'
              '           AND RESULTS OF OPERATIONS\n\n'
              'This paragraph has a long first line which continues with the\n'
              'Independent National Mortgage Corporation and ends here.')
    rows = standardize(source, rules='SEC:10-K')
    item = next(r for r in rows if r.get('class') == 'item')
    assert item['text'].endswith('AND RESULTS OF OPERATIONS')
    assert any(r['type'] == 'text' and 'the Independent National' in r['text'] for r in rows)
    uppercase = ' '.join(['THIS IS AN UPPERCASE PARAGRAPH WITH MANY WORDS'] * 8)
    wrapped = '\n'.join(uppercase[i:i+70] for i in range(0, len(uppercase), 70))
    runs = ds.convert_text_to_instructions(wrapped)
    assert len({r['block'] for r in runs}) == 1 and all(not r['flags'] & 16 for r in runs)

    # Inline formatting has run-level boundaries, including mixed-case tags.
    runs = ds.convert_partialsgml_to_instructions('<b>Heading</B> body text.<BR>next')
    assert [r['text'] for r in runs] == ['Heading', ' body text.', 'next']
    assert runs[0]['flags'] & 1 and not runs[1]['flags'] & 1
    assert not runs[2]['flags'] & 1
    assert any(r['type'] == 'text' and 'body text.' in r['text'] for r in standardize('<b>Heading</b> body text.', partial=True))

    aligned = 'Name       Count\nAlpha      12\nBeta       24\n'
    assert matrices(standardize(aligned)) == [[['Name', 'Count'], ['Alpha', '12'], ['Beta', '24']]]
    years = 'Year        High       Low\n\n1998\n\nFirst       12         8\nSecond      14         9\n\n1999\n\nFirst       15         10\n'
    table = matrices(standardize(years))[0]
    assert ['1998', '', ''] in table and ['1999', '', ''] in table and ['First', '15', '10'] in table
    assert not matrices(standardize('Ordinary prose.\nMore ordinary prose.\nLast line.'))
    assert not matrices(standardize('A long label with  two spaces\nAnother long  label\nShort label                                  one value'))
    packed = ('         Beginning                        Principal   Remaining  Distribution\n'
              'Class     Balance    Principal  Interest     Loss      Balance      Date\n'
              'IPP-A     391650390      595540  2121440           0   391054850  21-Jun-99\n'
              'IIPP-A-1   95600169      125062   517834           0    95475106  21-Jun-99\n'
              'IIPP-A-2   22364000           0   121138           0    22364000  21-Jun-99\n')
    assert ['IPP-A', '391650390', '595540', '2121440', '0', '391054850', '21-Jun-99'] in matrices(standardize(packed))[0]

    # Misleading column hints cannot override explicit tabs in the data.
    tabs = '<TABLE> <C>   <C>\nName\tClass\tValue\nAlpha Ltd\tCOM\t13\nBeta\t\t24\nGamma Inc\tPREF\t36\n</TABLE>'
    assert matrices(standardize(tabs, partial=True))[-1] == [
        ['Name', 'Class', 'Value'], ['Alpha Ltd', 'COM', '13'], ['Beta', '', '24'], ['Gamma Inc', 'PREF', '36']]
    mixed = 'Alpha Ltd\tCOM\t13\tSOLE       N/A       NONE\nBeta\tCOM\t24\tSOLE       N/A       NONE\nGamma\tCOM\t36\tSOLE       N/A       NONE'
    assert matrices(standardize(mixed))[0][0] == ['Alpha Ltd', 'COM', '13', 'SOLE', 'N/A', 'NONE']

    record = '000 B000000 10/31/1999\n000 C000000 0001073330\n003  000000 Y\n001 A000000 NEW WORLD FUND, INC.'
    table = matrices(standardize('<PAGE> PAGE 1\n' + record, partial=True))[-1]
    assert table == [['000', 'B000000', '10/31/1999'], ['000', 'C000000', '0001073330'],
                     ['003', '000000', 'Y'], ['001', 'A000000', 'NEW WORLD FUND, INC.']]

    # Missing closing tags and orphan marker lines still yield ordinary tables.
    data = '<S>         <C>\nAlpha       12\nBeta        24\nGamma       36'
    expected = [['Alpha', '12'], ['Beta', '24'], ['Gamma', '36']]
    assert matrices(standardize('<TABLE>\n'+data, partial=True)) == [expected]
    assert matrices(standardize(data, partial=True)) == [expected]
    financial = '<TABLE>\n<S>                             <C>\n<TOTAL-ASSETS>                   751,766\n<TOTAL-LIABILITIES>              13,129\n</TABLE>'
    assert matrices(standardize(financial, partial=True))[0] == [
        ['<TOTAL-ASSETS>', '751,766'], ['<TOTAL-LIABILITIES>', '13,129']]

    # One SGML wrapper can contain different layouts. Spanning captions retain
    # complete words in the instruction stream instead of slicing them apart.
    source = ('<TABLE>\n<S>       <C>       <C>\nAlpha     12        24\nBeta      36        48\nGamma     60        72\n'
              '------------------------------\nSecond Table\n\n'
              'Label               Value\nDelta               84\nEpsilon             96\nZeta                108\n</TABLE>')
    tables = matrices(standardize(source, partial=True))
    assert len(tables) == 2 and len(tables[0][0]) == 3 and len(tables[1][0]) == 2
    source = '<TABLE>\n<CAPTION>\nLong Heading\n<S>   <C>   <C>\nA     12    24\nB     36    48\n</TABLE>'
    runs = ds.convert_partialsgml_to_instructions(source)
    assert any(r['text'] == 'Long Heading' and r['span'] for r in runs)

    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(ds.convert_partialsgml_to_instructions, [financial]*40))
    assert all(value == actual[0] for value in actual)
    print('PASS: text and partial SGML, layout, tables, records, encodings, malformed markup, threads')


if __name__ == '__main__':
    main()
