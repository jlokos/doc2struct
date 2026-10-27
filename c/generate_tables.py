"""Generate build-time data; parsing never calls Python for Unicode or entities."""
from html.entities import html5
from pathlib import Path
from io import StringIO
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
        f.write('};\ntypedef struct { const char *name, *value; unsigned length; } Entity;\n')
        f.write('static const Entity entities[] = {\n')
        for name, value in sorted(html5.items()):
            f.write('{"%s",%s,%d},\n' % (name, literal(value), len(name)))
        f.write('};\n')
        generated = f.getvalue()
    if not destination.exists() or destination.read_text(encoding='ascii') != generated:
        destination.write_text(generated, encoding='ascii', newline='\n')

if __name__ == '__main__':
    generate(Path(__file__).with_name('unicode_data.h'))
