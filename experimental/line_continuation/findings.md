# Line continuation experiments

These experiments are isolated from the production parser. They use a frozen
native extension and C source snapshot; no package is installed or overwritten.
All changes made for this experiment are in `experimental/line_continuation/`.

## Sample and evidence

The locked `sample.json` contains 23 files: 21 HTML filings and two PDFs, with
15 development files and eight hash-assigned holdouts. It includes old and new
10-Ks and 8-Ks, three other-issuer S-1/424B4 examples alongside Anthropic, a 20-F,
an N-CSR, S-3s, and 10-Qs. Some inputs are loose files; others are referenced by
TAR member name, byte offset, and size. Archives are never extracted. The
inventory covers metadata for the larger corpus; parsing comparisons use only
this small sample.

`results.json` contains the measurements, paired baseline totals, source and
binary hashes, and limitations. `reviewed_changes.json` retains the 26 manually
reviewed changes: 18 prose demotions and eight contact/address lines rejected as
footnotes. Summarization preserves existing annotations; new examples are
marked pending review.

Only Anthropic exercised positioned line reconstruction in this real-file
sample. The other HTML files are useful regression controls, not independent
evidence that reflow generalizes to other positioned renderers. The two PDFs
exercise native heading and annotation variants; paragraph reconstruction is
HTML-only in this prototype.

## Results for the original S-1 issues

The `measured` prototype passes all 11 targeted anchor observations:

| Observation | Baseline | Prototype |
| --- | --- | --- |
| Summary and risk introductions | Separate predicted headings | Prose |
| Standalone `business.` section fragments | Present | Absent |
| MD&A title | Two rows and levels | One complete title |
| Related person transactions title | Two rows and levels | One complete title |
| First cognitive-capabilities bullet | Continuation outside list | Complete item |
| Address / phone as first-table footnotes | `548`, `(415)` | Neither |
| Capitalization table title | Underwriting sentence fragment | Capitalization |
| Capitalization footnote (2) | Stops at “as set forth” | Complete continuation |
| Financial page labels classified as headings | 65 | 0 |
| Table matrices | 156 | All 156 identical |

The prototype makes 11,447 inter-line joins. Output shrinks from 14,588 to
3,121 rows, and lists followed by lowercase ordinary text drop from 422 to 18.
All 681 baseline list entries remain. These are diagnostic counts, not a
precision/recall score: the baseline already contains some spurious list items,
and legitimate long risk headings make simplistic heading-length metrics
misleading. Each reconstruction also checks that every non-whitespace source
character survives in the same order before standardization.

View the generated visualizations in
`artifacts/development_final/56dde07e5617/baseline.html` and `measured.html`.

## What worked, and what did not

1. **Existing removal rules can handle financial page labels.** An anchored
   `F-number` pattern removes 220 predicted page headings in the development
   sample without changing explicit section counts or table matrices. This
   remains a rule experiment, not a claim that every standalone F-number in
   every document is pagination.

2. **Keep existing footnote marker coverage.** Restricting footnotes to explicit
   punctuation markers breaks real notes: the sampled N-CSR goes from 50
   attached notes to 10 and leaves ten footnote tables unabsorbed. A more
   selective pattern retains existing markers and rejects recognizable phone
   numbers and short street-address forms. Its eight changed attachments in
   the development/holdout sample were all inspected and were contact lines.
   These English/US contact patterns are illustrative, not a universal address
   recognizer. Table matrices remain identical in all 23 files.

3. **Long italic text is not sufficient evidence of prose.** The first native
   heuristic demotes genuine one-sentence risk headings in the sampled 20-F.
   The revised heuristic requires an internal sentence boundary after a
   lowercase word of at least three letters, together with at least 28 words
   and 160 bytes. It excludes semantic heading tags, bold/centered/underlined
   text, and large type, and leaves explicit header rules alone. It demotes
   16 inspected prose passages in development and two in holdout while
   preserving those risk headings. This conservative heuristic intentionally
   misses many prose passages rather than treating all italics alike.

4. **Tightening every section prefix is too blunt.** It removes fragments but
   also changes valid `Underwriting Agreement` and `Executive Compensation
   Process` classifications. Reconstructing the containing paragraph already
   eliminates many fragment matches without changing section-name regexes.

5. **Preserve layout facts before making semantic decisions.** The HTML
   prototype retains page, top, left and right-edge observations in a sidecar,
   aligns them exactly to native normalized runs, and groups compatible lines
   before the existing list, header and table stages. Explicit paragraphs,
   tables, unknown positions, page changes, new markers, columns, font/style
   changes and separator lines are barriers. Local line spacing is compared
   in font units. It does not use issuer names or S-1 prose phrases.

6. **Heading continuation remains ambiguous.** Geometry alone merges separate
   neighboring headings. The conservative mode preserves those boundaries but
   misses a title such as `Certain Relationships and Related Person` followed
   by `Transactions`. The measured mode adds a large-type, short-continuation
   heuristic and recovers that title. It still incorrectly joins `Review of
   Annual Results` and `Next Steps` when their spacing and typography are the
   same. Of 15 hand-authored boundary scenarios, geometry-only fails two,
   conservative fails one, and measured fails this one. This is a known
   counterexample, not a passing regression suite.

## Recommended direction

Reuse the existing rule schema for removal and marker patterns. Keep generic
line reconstruction separate from document-type section definitions. Preserve
geometry and provenance as facts, reconstruct only well-supported continuations,
and let uncertain heading joins remain reviewable decisions. Do not promote the
large-heading extension as a universal default on the strength of this S-1.

The Python sidecar uses token export and a second normalization pass with opaque
alignment markers. That makes the experiment inspectable, but considerably
slower than the native pipeline. A production implementation would need to
preserve those facts natively, maintain direct/staged API parity, and find a
second independent positioned filing to validate boundaries. Nested positioning
contexts/transforms, cross-page continuation and PDF paragraph reconstruction
are not solved here.

No production defaults or parser implementation were changed.
The native `prediction_v2` variant also passes direct-versus-staged output
parity on all 23 samples. This checks that variant's existing public APIs;
the geometry sidecar remains outside those APIs.

## Reproduce and extend

Run from the repository root with the existing doc2struct Python environment
and a native compiler. The isolated build was exercised on Windows/MSVC.

```powershell
# Metadata inventory is optional when artifacts/inventory.jsonl already exists.
python experimental/line_continuation/lab.py inventory
python experimental/line_continuation/lab.py build
python experimental/line_continuation/lab.py sample

python experimental/line_continuation/lab.py run --split development --label development_final --variants baseline pages guarded_notes prediction_v2 measured
python experimental/line_continuation/review.py scenarios
python experimental/line_continuation/review.py anchor --label development_final --variant measured
python experimental/line_continuation/review.py parity

# Keep this selection untouched while changing hypotheses on development files.
python experimental/line_continuation/lab.py run --split holdout --label holdout_final --variants baseline pages guarded_notes prediction_v2 measured
python experimental/line_continuation/summarize.py
```

For quick iterations, add `--only anthropic_s1` or a sampled filename to `run`.
Use a new `--label` to retain earlier ledgers. The `artifacts/` directory is
ignored and contains source snapshots, compiled variants, bounded change
examples, full anchor join traces and visualizations. The tracked selection,
compact results and review notes avoid checking generated document dumps into
the repository. `native.py`, `variants.py`, `reflow.py`, `lab.py`, `review.py`
and `summarize.py` separate building, rule hypotheses, reconstruction,
measurement, review and reporting.
