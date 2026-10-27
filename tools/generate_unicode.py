"""Generate build-time data; parsing never calls Python for Unicode or entities."""
from html.entities import html5
from pathlib import Path
from io import StringIO
from fractions import Fraction
import unicodedata

def generate(destination):
    destination = Path(destination)
    def literal(text):
        return '"' + ''.join('\\%03o' % b for b in text.encode('utf-8')) + '"'
    with StringIO() as f:
        f.write('/* Generated from Python Unicode %s and HTML5 entity tables. */\n' % unicodedata.unidata_version)
        f.write('typedef struct { unsigned cp; const char *lower; unsigned flags; } UnicodeEntry;\n')
        f.write('static const UnicodeEntry unicode_entries[] = {\n')
        for cp in range(128, 0x110000):
            ch = chr(cp)
            flags = int(ch.isspace()) | (int(ch.isupper()) << 1) | (int(ch.islower() or unicodedata.category(ch) == 'Lt') << 2)
            # Case-ignorable characters for the contextual Greek final sigma rule.
            flags |= int(unicodedata.category(ch) in ('Mn','Me','Cf','Lm','Sk') or ch in "'\u2019\u00b7\u0387\u05f4\u2027:") << 3
            lower = ch.lower()
            if flags or lower != ch:
                f.write('{%d,%s,%d},\n' % (cp, literal(lower) if lower != ch else 'NULL', flags))
        names = sorted(html5.items())
        expansion = max([Fraction(1)] + [Fraction(len(value.encode('utf-8')), len(name) + 1) for name, value in names])
        f.write('};\n#define DS_ENTITY_EXPANSION_NUMERATOR %du\n#define DS_ENTITY_EXPANSION_DENOMINATOR %du\n' % (expansion.numerator, expansion.denominator))
        f.write('#define DS_ENTITY_MAX_NAME %du\n' % max(map(len, html5)))
        f.write('typedef struct { const char *value; unsigned value_length; } Entity;\n')
        f.write('static const Entity entities[] = {\n')
        for name, value in names:
            f.write('{%s,%d},\n' % (literal(value), len(value.encode('utf-8'))))
        f.write('};\n')
        nodes = [{'children': {}, 'value': -1}]
        for index, (name, _) in enumerate(names):
            node = 0
            for char in name:
                child = nodes[node]['children'].get(char)
                if child is None:
                    child = len(nodes)
                    nodes[node]['children'][char] = child
                    nodes.append({'children': {}, 'value': -1})
                node = child
            nodes[node]['value'] = index
        edges, records = [], []
        for node in nodes:
            records.append((len(edges), len(node['children']), node['value']))
            edges.extend((target, ord(char)) for char, target in sorted(node['children'].items()))
        assert len(nodes) < 65536 and len(edges) < 65536 and len(names) < 32768
        assert max(row[1] for row in records) < 256
        f.write('typedef struct { uint16_t first; uint8_t count; int16_t value; } EntityNode;\n')
        f.write('typedef struct { uint16_t target; uint8_t byte; } EntityEdge;\n')
        f.write('static const EntityNode entity_nodes[] = {\n')
        for row in records:
            f.write('{%d,%d,%d},\n' % row)
        f.write('};\nstatic const EntityEdge entity_edges[] = {\n')
        for row in edges:
            f.write('{%d,%d},\n' % row)
        root = [nodes[0]['children'].get(chr(i), -1) + 1 for i in range(128)]
        f.write('};\nstatic const uint16_t entity_root[128] = {%s};\n' % ','.join(map(str, root)))
        generated = f.getvalue()
    if not destination.exists() or destination.read_text(encoding='ascii') != generated:
        destination.write_text(generated, encoding='ascii', newline='\n')

if __name__ == '__main__':
    generate(Path(__file__).resolve().parents[1] / 'c/src/unicode_data.h')
