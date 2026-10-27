"""visualizer.py - open tokens or normalizer rows in the browser."""
import os
import webbrowser
from html import escape

from .html_token_normalizer import BOLD, CENTERED, ITALIC, UNDERLINE
from .html_tokenizer import END, START, TEXT

_CSS = """<html><head><meta charset="utf-8"><style>
body{font-family:Arial,sans-serif;max-width:1200px;margin:0 auto;padding:20px}
span{display:inline-block;padding:5px 8px;margin:3px 0;border-radius:4px;white-space:pre-wrap}
.tok{font-family:monospace;font-size:13px;padding:2px 5px;margin:1px;border-radius:3px}
.start{background:#C8E6C9}.end{background:#FFCDD2}.text{background:#E8EAF6}
.first{background:#DCEDC8}.rest{background:#F9FBE7}.single{background:#E8EAF6}
.table-wrapper{text-align:center;margin:15px 0}
.table-container{display:inline-block;border-radius:8px;padding:8px;box-shadow:0 2px 5px rgba(0,0,0,.1);background:#FFECB3}
table{border-collapse:collapse;background:white}
td{border:2px solid #ddd;padding:10px;text-align:left;vertical-align:top}
td.empty{background:#fafafa}
.meta{font-size:11px;color:#888}
.st{margin:4px 0;padding:2px 8px;border-left:3px solid transparent}
.st-title{font-weight:bold;background:#DCEDC8;border-left-color:#7CB342;padding:6px 8px;margin-top:12px}
.st-text{background:#E8EAF6}
.st-textsmall{background:#F5F5F5;font-size:12px;color:#555}
.st-image{background:#FFF3E0;font-style:italic}
.badge{font-family:monospace;font-size:11px;background:#fff;border:1px solid #bbb;border-radius:3px;padding:0 4px;margin-left:8px;font-weight:normal;color:#555}
.cleaned{background:#B2DFDB}.dirty{background:#FFECB3}
.tbl{display:inline-block;max-width:100%;margin:10px 0}
.tbl-title{font-weight:bold;margin:0 0 4px}
.tbl-pre{font-style:italic;color:#555;margin:0 0 6px}
.tbl-foot{font-size:12px;color:#444;margin:6px 0 0}
.tbl-foot b{margin-right:4px}
.tbl-post{font-size:12px;color:#555;margin:6px 0 0}
.tag{font-family:monospace;font-size:10px;background:#fff;border:1px solid #bbb;border-radius:3px;padding:0 4px;margin-right:6px;color:#666;font-weight:normal;font-style:normal}
</style></head><body>"""


def _open(html, filename, open_browser):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    if open_browser:
        webbrowser.open('file://' + os.path.abspath(filename))


def visualize_tokens(tokens, filename='tokens_visualization.html', open_browser=True):
    out = [_CSS]
    for kind, a, b in tokens:
        if kind == START:
            attrs = ''.join(f' {k}="{v}"' for k, v in (b or {}).items())
            out.append(f"<span class='tok start'>&lt;{escape(a)}{escape(attrs)}&gt;</span>")
        elif kind == END:
            out.append(f"<span class='tok end'>&lt;/{escape(a)}&gt;</span>")
        else:
            out.append(f"<span class='tok text'>{escape(a)}</span>")
    out.append('</body></html>')
    _open(''.join(out), filename, open_browser)


def _style(r):
    s = []
    f = r['flags']
    if f & BOLD: s.append('font-weight:bold')
    if f & ITALIC: s.append('font-style:italic')
    if f & UNDERLINE: s.append('text-decoration:underline')
    if r['font_size']: s.append(f"font-size:{r['font_size']}px")
    if r['indent']: s.append(f"margin-left:{r['indent']}px")
    return ';'.join(s)


def _run(r, cls):
    if r['src'] is not None:
        return f"<span class='{cls}'><img src='{escape(r['src'])}' alt='{escape(r['text'] or '')}' style='max-width:300px'></span>"
    text = escape(r['text'] or '')
    if r['href'] is not None and r['href'] != '':
        text = f"<a href='{escape(r['href'])}'>{text}</a>"
    return f"<span class='{cls}' style='{_style(r)}'>{text}</span>"


def _line(runs):
    center = 'text-align:center;' if runs[0]['flags'] & CENTERED else ''
    out = [f"<div style='{center}'>"]
    for i, r in enumerate(runs):
        cls = 'single' if len(runs) == 1 else ('first' if i == 0 else 'rest')
        out.append(_run(r, cls))
    out.append('</div>')
    return ''.join(out)


def _table(runs):
    cells, order = {}, []
    for r in runs:
        k = (r['row'], r['col'])
        if k not in cells:
            rs, cs = (int(x) for x in (r['span'] or '1x1').split('x'))
            cells[k] = {'rs': rs, 'cs': cs, 'lines': {}}
            order.append(k)
        cells[k]['lines'].setdefault(r['line'], []).append(r)
    rows = {}
    for k in order:
        rows.setdefault(k[0], []).append(k)
    out = ["<div class='table-wrapper'><div class='table-container'><table>"]
    for y in sorted(rows):
        out.append('<tr>')
        for k in sorted(rows[y], key=lambda k: k[1]):
            c = cells[k]
            has = any((r['text'] or r['src'] is not None) for ls in c['lines'].values() for r in ls)
            out.append(f"<td rowspan={c['rs']} colspan={c['cs']}{'' if has else ' class=empty'}>")
            out.append(''.join(_line(c['lines'][n]) for n in sorted(c['lines'])) if has else '')
            out.append('</td>')
        out.append('</tr>')
    out.append('</table></div></div>')
    return ''.join(out)


def visualize_instructions(rows, filename='instructions_visualization.html', open_browser=True):
    out = [_CSS]
    i, n = 0, len(rows)
    while i < n:
        r = rows[i]
        j = i
        if r['row'] is not None:
            while j < n and rows[j]['row'] is not None and rows[j]['block'] == r['block']:
                j += 1
            out.append(_table(rows[i:j]))
        else:
            while j < n and rows[j]['row'] is None and rows[j]['line'] == r['line']:
                j += 1
            out.append(_line(rows[i:j]))
        i = j
    out.append('</body></html>')
    _open(''.join(out), filename, open_browser)


def _st_table(r):
    """A table with its title, preamble, footnotes and postamble, in document order."""
    cls = 'dirty' if r.get('cleaned') is False else 'cleaned'
    out = [f"<div class='table-wrapper' style='margin-left:{r['level'] * 24}px'><div class='tbl'>"]
    if r.get('text'):
        out.append(f"<div class='tbl-title'><span class='tag'>title</span>{escape(r['text'])}</div>")
    if r.get('preamble'):
        out.append(f"<div class='tbl-pre'><span class='tag'>preamble</span>{escape(r['preamble'])}</div>")
    out.append(f"<div class='table-container {cls}'><table>")
    for row in r['matrix']:
        out.append('<tr>' + ''.join(f'<td>{escape(c)}</td>' for c in row) + '</tr>')
    out.append('</table></div>')
    for fid, ftext in (r.get('footnotes') or ()):
        out.append(f"<div class='tbl-foot'><span class='tag'>footnote</span><b>{escape(fid)}</b>{escape(ftext)}</div>")
    if r.get('postamble'):
        out.append(f"<div class='tbl-post'><span class='tag'>postamble</span>{escape(r['postamble'])}</div>")
    out.append('</div></div>')
    return ''.join(out)


def visualize_standardized_text(rows, filename='standardized_text_visualization.html', open_browser=True):
    """rows: output of convert_instructions_to_standardized_text. Indented by level; titles show class and standardized_title."""
    out = [_CSS]
    for r in rows:
        kind = r['type']
        if kind == 'table':
            out.append(_st_table(r))
            continue
        pad = f"margin-left:{r['level'] * 24}px"
        text = escape(r['text'] or '')
        if kind == 'title':
            badge = ' '.join(x for x in (r.get('class'), r.get('standardized_title')) if x)
            badge = f"<span class='badge'>{escape(badge)}</span>" if badge else ''
            out.append(f"<div class='st st-title' style='{pad}'>{text}{badge}</div>")
        elif kind == 'image':
            out.append(f"<div class='st st-image' style='{pad}'>[image] {text}</div>")
        else:
            out.append(f"<div class='st st-{kind}' style='{pad}'>{text}</div>")
    out.append('</body></html>')
    _open(''.join(out), filename, open_browser)