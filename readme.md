# doc2struct

A fast algorithmic document parser for html and (most) pdf files.

It converts a document into **instructions**, then converts those instructions into **standardized text**. Everything can be stored as parquet.

```
html bytes -> html_tokenizer -> tokens -> token_normalizer -> instructions -> convert_instructions_to_standardized_text -> standardized text
```

## terms

| Term | Meaning |
|---|---|
| instruction cell | one row of the normalizer output: a single run of text with one style, or an image |
| instruction | one block: all instruction cells that share a `block` id. A plain line of text is one instruction. A whole table is one instruction. |
| instructions | the full list of instruction cells for a document, in document order |

## rulesets

### html_tokenizer

- Skips comments, doctype, and the contents of script, style and title.
- Keeps only 7 attributes: style, colspan, rowspan, href, src, alt and hidden.
- Decodes entities and lowercases tag names.
- Self-closed non-void tags get a START and an END.

### token_normalizer

- Hidden: skips display:none elements and everything inside them. With options, it also skips the hidden attribute and visibility:hidden.
- Body only: ignores everything before the first non-head tag.
- Lines: a line ends at the end of p, div, h1–h6 or li, or at `<br>`.
- Styles: reads bold, italic, underline and centered from the tags and inline style, and takes the nearest font_size and indent.
- Links: the nearest `<a>` sets href.
- Tables: nested tables are flattened into the cell, spans are capped at max_span, and empty cells get a placeholder instruction cell.
- Repair: implied end tags for p, li, td and tr, and end tags never pop past a table.
- Whitespace: whitespace-only text at the start of a line is dropped.

Options (all default to off, except max_span):

| Option | Effect |
|---|---|
| hide_hidden_attr | also skip elements with the `hidden` attribute |
| hide_visibility | also skip `visibility:hidden` and `visibility:collapse` |
| max_span | cap on rowspan and colspan (default 100) |

### convert_instructions_to_standardized_text

- Merging: adjacent instruction cells in the same line with the same style are joined into one piece of text.
- Fake tables: a table with only one non-empty row is demoted to a plain line.
- Cleaning: page numbers, "table of contents" links and text repeated about 20 or more times (running headers and footers) are removed.
- Header rules: a rule has a class, a regex on the line's text and a level (for example `item`, `^item\s*(\d+)`, level 1). A match sets `level`, `class` and `standardized_title`.
- Predicted headers: a line that is not matched by a rule but looks like a header (bold, italic, underline, centered, all caps, proper case or a larger font size) becomes a `predicted header`. Its level comes from the order of its style combinations within the section.
- Small text: text with a smaller font size than most of the document becomes `textsmall`.
- Nesting: lines are placed under the nearest earlier header with a lower level. `level` is the nesting depth.
- Tables: matrix cleanup (empty rows and columns, duplicate and subset rows and columns, merged header rows). A single-row table becomes text. A table can also take a title, footnotes, a preamble and a postamble (see below).
- Custom columns: rules can declare extra columns (see below).

## html_tokenizer

Takes html bytes (UTF-8, falling back to cp1252), outputs tokens.

`(kind, text/tag, attributes including style)`

| kind | meaning |
|---|---|
| 0 | TEXT |
| 1 | START |
| 2 | END |

```
(1, 'p',  {'style': 'font-weight:bold'})   START p; class is dropped, we don't keep it
(0, 'Item 1 & 2', None)                    TEXT; &amp; is decoded to &
(2, 'p',  None)                            END p
(1, 'br', {})                              START br; void tag, so no END follows
(1, 'img', {'src': 'a.png', 'alt': 'logo'})
(0, '\n', None)                            whitespace between tags is still a TEXT token
(1, 'td', {'colspan': '2'})                attribute values are always strings
(0, 'Total', None)
(2, 'td', None)
(1, 'script', {})                          the comment produced nothing; script content is skipped
(2, 'script', None)                        but we still get START and END for it
```

> Ready for conversion to C + SIMD Optimization

## token_normalizer

Normalizes tokens into instructions with these columns:

`block, line, row, col, span, text, flags, font_size, indent, href, tag, src`

| Column | Meaning |
|---|---|
| block | one id per plain line, or one shared id for a whole table |
| line | the visual line |
| row, col | position in a table, empty outside tables |
| span | `RxC` (rowspan x colspan), only when the cell is bigger than 1x1 |
| text | the text of the run. For an image, its alt |
| flags | bitmask: bold 1, italic 2, underline 4, centered 8 |
| font_size | px, from the nearest enclosing font-size |
| indent | px, from the nearest enclosing element's own text-indent, padding and margin |
| href | link target of the enclosing `<a>` |
| tag | innermost enclosing block tag |
| src | image source, set only on image instruction cells |

| block | line | row | col | span | text | flags | font_size | indent | href | tag | src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 |  |  |  | `ITEM 1. BUSINESS` | 9 | 16 |  |  | p |  |
| 1 | 1 |  |  |  | `We make ` | 0 |  | 24 |  | p |  |
| 1 | 1 |  |  |  | `software` | 2 |  | 24 |  | p |  |
| 1 | 1 |  |  |  | `, see ` | 0 |  | 24 |  | p |  |
| 1 | 1 |  |  |  | `Note 4` | 0 |  | 24 | /ex.htm | p |  |
| 1 | 1 |  |  |  | `.` | 0 |  | 24 |  | p |  |
| 2 | 2 |  |  |  | `Company logo` | 0 |  |  |  |  | logo.png |
| 2 | 2 |  |  |  | `\n` | 0 |  |  |  |  |  |
| 3 | 3 | 0 | 0 |  | `Revenue` | 0 |  |  |  | td |  |
| 3 | 4 | 0 | 1 | 1x2 | `2021` | 1 |  |  |  | td |  |
| 3 | 5 | 1 | 0 |  | `Cloud` | 0 |  |  |  | td |  |
| 3 | 6 | 1 | 0 |  | `services` | 0 |  |  |  | td |  |
| 3 | 7 | 1 | 1 |  |  | 0 |  |  |  |  |  |
| 3 | 8 | 1 | 2 |  | `5` | 0 |  |  |  | td |  |

Block 1 is one instruction made of five instruction cells. Block 3 is one instruction: the whole table.

## convert_instructions_to_standardized_text

Takes instructions, converts them into standardized text, suitable for storage in a parquet file. Supports new columns.

Default

| Column | Meaning |
|---|---|
| id | increment of the individual output row |
| level | nesting depth |
| type | title, text, textsmall, table or image |
| text | the text content, the image alt if image, or the title if table |
| matrix | table content as rows of strings, empty for other types |
| cleaned | table rows only: whether table cleanup succeeded |
| preamble | table rows only: text just before the table |
| footnotes | table rows only: list of `[id, text]` pairs |
| postamble | table rows only: text just after the table's footnotes |

With rules

| Column | Meaning |
|---|---|
| id | increment of the individual output row |
| level | nesting depth |
| type | title, text, textsmall, table or image |
| class | header class, e.g. item, part, predicted header |
| standardized_title | e.g. item1a, from the mapping regex |
| text | the text content, the image alt if image, or the title if table |
| matrix | table content as rows of strings, empty for other types |
| cleaned | table rows only: whether table cleanup succeeded |
| preamble | table rows only: text just before the table |
| footnotes | table rows only: list of `[id, text]` pairs |
| postamble | table rows only: text just after the table's footnotes |

The table columns (`matrix`, `cleaned`, `preamble`, `footnotes`, `postamble`) are in the default output too. They are empty on every row that is not a table.

### tables

A table is one output row. Its `matrix` holds the cleaned data and its other columns hold what belongs to it.

**Title.** The table's `text` is the title of its section, with these rules:

- The title is copied, not moved. The section's header row stays in the output as it is, so the outline is intact and rows nested under it keep their parent. The same text appears on the header row and on the table row.
- Only a section with exactly one table directly in it gives its title. If the section has several tables, none of them gets it.
- A table that already has a title keeps it. The section title only fills an empty `text`.

**Footnotes.** Text right after the table that starts with a marker (`*`, `(a)`, `1`, `†`) is moved into `footnotes` as `[id, text]` pairs. A few following lines without a marker are added to the previous footnote. A two-column table whose first column is all markers counts as footnotes too.

**Preamble and postamble.** The first N text lines directly before the table go into `preamble`. The first N text lines after the table's footnotes go into `postamble`. Both stop at a table, an image or a header.

Footnotes, preamble and postamble are removed from the output as separate rows. Only the title is duplicated.

Table handling is on by default, with these defaults (all can be changed in the table rules):

| Setting | Default |
|---|---|
| footnote marker regex | `^(\*|\(.{1,2}\)|\d+|†+)` |
| footnote continuation lines | 3 |
| preamble lines | 7 |
| postamble lines | 7 |
| title from section | on |

Example (matrix and footnotes shown as JSON, since csv cannot hold lists):

```csv
id,level,type,text,matrix,preamble,footnotes,postamble
0,0,title,Segment results,,,,
1,1,text,Revenue grew in every segment.,,,,
2,1,table,Segment results,"[[""Segment"",""2024"",""2023""],[""Cloud"",""105.4(a)"",""87.9""],[""Gaming"",""23.5"",""15.5(b)""]]",(In millions),"[[""(a)"",""Includes acquired businesses.""],[""(b)"",""Restated.""]]",Source: company filings.
3,1,text,Operating income also rose.,,,,
```

### custom columns

Rules can declare extra columns. Every custom column is declared up front with a name and a type, so the parquet schema is the same for every filing. Rows a rule does not apply to get null. A custom column cannot reuse a default column name.

A custom column has:

| Field | Meaning |
|---|---|
| name | the column name |
| dtype | str, int, bool or list |
| source | `text` (with a regex `pattern`, case-insensitive, group 1), or an instruction column (`href`, `src`, `font_size`, `indent`, `flags`) |
| which | the first, the last, or all instruction cells of the instruction. `all` gives a list |

For example, an `href` column reads `href` from all instruction cells of a line, and an `item` column reads the number out of "Item 1A".

# todo
- port to c / optimize - hope to get 2gb.s
- make rulesets better with /goal
- make tables better
- make uhh lists better
