# Performance experiments

These are measured candidates for review. User-facing alternatives are experimental;
the existing `parse_html` API keeps its output and rules behavior.

The requirement is single-threaded parsing. All current candidates must work on
one thread; worker-pool scaling is outside scope.

The primary metric is now the internal C loop: bytes already in memory through
completed native standardized-text rows, including rules and table cleanup. Python
conversion, dataframe creation, and JSON export are outside this metric. The target
is approximately 2 GB/s or better on Microsoft 2026 where possible.

## Fused native parsing workflow

Implemented in the working tree. Normalization now builds native lines and table
cells directly. `parse_html` does not construct a document-wide instruction array
and then regroup it. The inspection API still materializes instructions when used.

Other changes include tag flags, word-at-a-time hashing, SIMD case conversion,
reused temporary cell storage, deferred text joining, and reused Python output keys.

Measured on Windows, CPython 3.14, MSVC optimized builds. Input bytes are already
in memory. Medians of 31 samples after five warmups; complete Python result
creation is included and output destruction is excluded. Versions were alternated.

| Filing | Rules | Before | After | Speedup |
| --- | --- | ---: | ---: | ---: |
| Microsoft 2026, 8,585,500 bytes | default | 77.90 ms | 14.38 ms | 5.42x |
| Microsoft 2026, 8,585,500 bytes | SEC:10-K | 78.63 ms | 13.72 ms | 5.73x |
| Microsoft 2021, 6,332,562 bytes | SEC:10-K | 68.96 ms | 14.48 ms | 4.76x |
| Microsoft 2006, 1,192,045 bytes | SEC:10-K | 24.30 ms | 5.75 ms | 4.22x |

These measurements are local observations, not throughput guarantees. Independent
sample groups vary with CPU and allocation state. The 2026 SEC result corresponds
to 0.63 GB/s end to end. First-call measurements were approximately 12.76 ms for
default rules and 13.47 ms for SEC rules.

Validation: exact instruction/default/SEC output comparisons on five filings;
1,500 generated malformed documents with default, SEC, and custom rules; staged
API parity; and concurrent parsing. Raw measurements and scripts are under
`build/pipeline-optimization-results.*` and `build/check_pipeline_optimization.py`.

Decision: review and retain or revise the internal workflow changes.

## Experiment candidates

- Keep a native parsed document and convert it only when requested.
- Export columns directly for dataframe consumers.
- Export UTF-8 JSON without constructing Python row dictionaries first.

Results and tradeoffs will be added below as these are measured.

## Earlier output experiments: optional native document and direct exports

Prototype: `doc2struct.experimental`, not exported from the package's stable API.

```python
from doc2struct.experimental import parse_native, parse_columns, parse_json_bytes

document = parse_native(html_bytes, "SEC:10-K")
rows = document.to_rows()
columns = document.to_columns()
json_bytes = document.to_json_bytes()
```

The handle retains the input and native allocations until it is released. Each
conversion returns independent Python data. Retaining native results defers Python
object creation; it does not remove the parsing work. Custom columns work for rows
and columns. The native JSON prototype currently rejects custom columns explicitly.

Microsoft 2026 SEC:10-K, input in memory, medians of 15 interleaved samples:

| Complete operation | Median |
| --- | ---: |
| Existing `parse_html` to Python rows | 11.01 ms |
| Parse to a retained native handle, without conversion | 10.47 ms |
| Parse directly to Python columns | 10.75 ms |
| Parse directly to compact UTF-8 JSON bytes | 11.07 ms |
| Parse to rows, then Python `json.dumps(...).encode()` | 13.80 ms |
| Parse to rows, then Polars DataFrame | 15.17 ms |
| Parse to columns, then Polars DataFrame | 14.39 ms |

Conversion alone from an already parsed native document: rows 0.42 ms, columns
0.30 ms, JSON bytes 0.38 ms. Direct JSON is approximately 20% faster for the complete
JSON-export workflow. Columns gave a smaller, approximately 5% dataframe benefit.
The retained handle is primarily useful for deferred conversion or multiple views;
its single-document parsing speed improvement is small and it retains extra memory.

JSON bytes matched compact Python JSON byte for byte on the benchmark filing.
Rows, columns, and decoded JSON matched frozen outputs on five filings. Additional
checks covered control characters, Unicode, mutable input ownership, rule-cache
eviction, and concurrent JSON conversion.

Decision: consider retaining direct JSON export; review whether the handle and
column APIs justify their additional surface area. No default API changes.
Future measurements, including dataframe experiments, will explicitly constrain
any library thread pools to one thread.

## Primary metric: standalone single-threaded C engine

`c/parser.c:ds_parse` is now the shared C entry point used by both the extension
and the standalone benchmark. Timing starts with the source bytes in memory and
ends with completed native standardized-text rows. Input validation, tokenization,
normalization, classification, rules, table cleanup, and footnotes are included.
Python conversion, JSON serialization, rule compilation, input I/O, checksumming,
and result destruction are outside this interval. Destruction is measured separately.

Seven warmups and 51 samples, one process and one parsing thread:

| Filing | Rules | Native C median | Throughput |
| --- | --- | ---: | ---: |
| Microsoft 2026 | default | 10.00 ms | 0.86 GB/s |
| Microsoft 2026 | SEC:10-K | 10.14 ms | 0.85 GB/s |
| Microsoft 2021 | SEC:10-K | 10.11 ms | 0.63 GB/s |
| Microsoft 2006 | SEC:10-K | 5.50 ms | 0.22 GB/s |

Every result is consumed by a checksum after timing. Exported complete rows were
also compared to the reference output. Scripts and raw results:
`build/run_native_pipeline_bench.py`, `build/native-loop-results.*`.

### Reusing C scratch blocks between documents

The C `ParserContext` now wraps the bounded `ArenaPool`. Initialize it with
`ds_parser_init`, parse using `ds_parser_parse`, and release cached blocks using
`ds_parser_clear`. Documents, input, and rules keep their existing ownership;
the context must outlive its attached documents. No worker threads are involved.

Python `parse_html(...)` now enables reuse automatically with an 8 MiB limit.
Output and rule inputs are unchanged. `clear_parser_cache()` releases the default
cache while leaving parsing usable. Each interpreter has its own default cache.
An overlapping call uses an independent arena rather than sharing a busy pool.

`Parser(cache_size=...)` provides a separate context with `parse_html`, `clear`,
`close`, `cached_bytes`, and context-manager support. Use `cache_size=0` to disable
retention. Each explicit instance accepts one parsing call at a time. Retained
experimental native documents keep their context alive; closing or clearing a
context does not invalidate existing results.

Earlier single-threaded C benchmark, SEC rules, warmed workspace:

| Filing | No block cache | 8 MiB limit | Retained blocks |
| --- | ---: | ---: | ---: |
| Microsoft 2026 | 10.08 ms | 8.58 ms | 5.13 MB |
| Microsoft 2021 | 9.71 ms | 8.61 ms | 5.85 MB |
| Microsoft 2006 | 5.66 ms | 4.56 ms | 4.09 MB |

The 2026 result reaches 1.00 GB/s. This helps repeated parsing, not the first
allocation in a fresh process. A 16 MiB limit did not provide a convincing further
benefit. Cached blocks retain memory until the pool is explicitly cleared. The
pool must outlive attached documents, and documents must be retired before the
pool is destroyed. Complete output checksums matched with and without reuse.

Decision: implemented in C and enabled by default in Python following approval.
The cache stays bounded. Earlier raw results: `build/pool-experiment-results.*`.

Latest measurements call the actual `ds_parser_parse` entry point. Three batches,
63 measured samples per configuration, bytes already loaded to complete native
SEC:10-K rows; Python, serialization, I/O, and destruction remain outside timing:

| Filing | Zero-byte cache | 8 MiB cache | Retained blocks |
| --- | ---: | ---: | ---: |
| Microsoft 2026 | 9.66 ms | 8.52 ms | 4.48 MB |
| Microsoft 2021 | 9.37 ms | 8.25 ms | 5.07 MB |
| Microsoft 2006 | 4.45 ms | 3.79 ms | 3.63 MB |

The 2026 pooled result is 1.01 GB/s in this run. The C API passed mixed-document
reuse, cache-limit, retained-result, clear, and failure-recovery checks. Python
pooled results matched default, SEC, and custom-column outputs across all 25
available Microsoft filings. Ownership checks include retained native documents,
mutable input, and context clear/close/deletion. Raw results:
`build/parser-context-native-results.json`, `build/parser-context-checks.log`.

### Small front cache for inline styles

Tested 0, 1, 2, 4, 8, and 16 recent styles in front of the existing full style map.
The extra cache did not help consistently; no front cache was slightly faster on
the modern filings. Removed the four-entry front cache while retaining complete
per-document style memoization. Results: `build/style-cache-experiment-results.json`.

### Reusing complete parsed tag templates

Implemented a bounded, per-document cache of 1,024 start-tag templates on the
native fused path for inputs of at least 64 KiB. Cache entries retain input
slices and prepared styles. Every hit compares the complete original tag,
including quotes and attributes, before reuse. Hash collisions only cause misses.
The standalone token API keeps its existing path. There is no cross-document
cache or worker thread.

Three interleaved batches, 63 measured samples per configuration, full native
SEC:10-K pipeline with byte-for-byte comparisons of completed output:

| Filing | No pool, before | No pool, templates | 8 MiB pool, before | 8 MiB pool, templates |
| --- | ---: | ---: | ---: | ---: |
| Microsoft 2026 | 9.82 ms | 9.10 ms | 8.50 ms | 8.06 ms |
| Microsoft 2021 | 9.67 ms | 9.27 ms | 8.37 ms | 7.98 ms |
| Microsoft 2006 | 5.25 ms | 4.96 ms | 4.45 ms | 3.98 ms |

The 2026 pooled result is 1.07 GB/s. The cache adds about 0.23 MB to retained arena
blocks in these runs. A larger cache and shorter fingerprints did not consistently
improve results. Inspection outputs, five filing references, 1,500 malformed small
documents, and 120 larger malformed/repeated-tag documents matched the reference
and staged pipelines. The larger cases exercise cache reuse, collisions, quotes,
entities, hidden elements, raw-text elements, and long attributes.

Decision: useful internal optimization with unchanged output; review the small
memory increase. Raw paired results: `build/tag-template-paired-results.*`.

### Representing empty table cells implicitly

Implemented implicit bounds-only representation for new, empty 1x1 cells emitted
by the fused normalizer. Larger spans remain explicit to preserve overlapping
cell behavior. This reduced the 2026 arena block cache from approximately 5.13 MB
to 4.45 MB before the tag-template cache was added. Latency did not improve
convincingly. Retain for memory savings, subject to review.

### Other native-path experiments

Alternative full-string hashes and direct tokenizer-to-normalizer calls gave
small, inconsistent gains and remain isolated experiments. Removing cosmetic CSS
processing changed header output and slowed the complete pipeline; it was not
adopted. The current complete native loop remains below the 2 GB/s target.
Measured time still includes rule matching and all table/footnote processing.

### Entity decoding and text assembly

Implemented a generated trie for longest-prefix HTML entity lookup, bulk copies
of ordinary text, and a generated maximum expansion bound for decoder buffers.
Removed redundant zeroing of fully written strings and an unnecessary ampersand
scan when rejecting blank text. All HTML5 entity and malformed-token comparisons
passed; scalar/SIMD guard-page checks and AddressSanitizer checks with individual
arena allocations bounded also passed. The trie helped the entity-heavy 2006
filing more than modern filings. Results: `build/entity-trie-experiment.log`.

Implemented growable native paragraph buffers. Previously every appended inline
fragment copied the accumulated paragraph into another allocation. A synthetic
0.54 MB paragraph with 1,024 inline fragments dropped from 59.44 ms to 0.72 ms
without scratch reuse, with identical output. The Microsoft filings showed
smaller gains. This synthetic result is separate from the full-filing throughput
target. Results: `build/plain-buffer-experiment.log`.

### Fused frontend experiments, October 26, 2026

Retained five changes after comparing against a frozen copy of the current C
sources: sample the first/middle/last bounded words for tag-template fingerprints;
pass cached attributes directly to the synchronous token sink; handle ordinary
lowercase closing tags directly; copy the inherited normalizer frame once, after
stack growth; and test custom blank text with a forward scan. Template reuse still
requires complete byte equality, including attributes and quotes. The fallback
tokenizer handles other closing-tag forms. The custom blank set remains space,
tab, CR, LF, NBSP, and zero-width space.

Fresh paired native benchmarks, SEC:10-K, one parsing thread, input already loaded,
seven warmups, three alternating batches of 63 samples. Values below are medians
of the three batch medians. Timing includes input validation through completed
native rows; output serialization, checksumming, and destruction occur afterward.

| Filing | 8 MiB cache: before | After | Latency reduction | No cache: before | After |
| --- | ---: | ---: | ---: | ---: | ---: |
| Microsoft 2026 | 8.319 ms | 7.214 ms | 13.3% | 9.225 ms | 8.330 ms |
| Microsoft 2021 | 8.235 ms | 7.425 ms | 9.8% | 9.416 ms | 8.495 ms |
| Microsoft 2006 | 3.702 ms | 3.532 ms | 4.6% | 4.385 ms | 4.356 ms |

The 2026 cached result is approximately 1.19 GB/s. Retained arena bytes were
identical before and after for all three filings. A later independent batch group
measured 8.376 to 7.530 ms for 2026, so the observed modern-filing improvement is
approximately 10–13%, with ordinary run-to-run variation. The 2 GB/s target is
still unmet.

Shorter fingerprint prefixes increased collisions and slowed modern filings.
Predicting the next tag template, an open-tag property mask, alternative hash-tail
handling, and `/Ob3` did not provide sufficiently consistent gains to retain.

An additional **standalone compiler experiment**, using MSVC `/GENPROFILE` then
`/USEPROFILE`, trained on the 2026, 2021, and 2006 filings. It is not enabled in
`setup.py` or the installed Python extension. A separate three-batch comparison:

| Filing | Frozen baseline | Source changes | Source changes + PGO |
| --- | ---: | ---: | ---: |
| Microsoft 2026 | 8.376 ms | 7.530 ms | 6.509 ms |
| Microsoft 2021 | 8.232 ms | 7.296 ms | 6.780 ms |
| Microsoft 2006 | 3.635 ms | 3.431 ms | 3.027 ms |
| Microsoft 2015, not used for training | 5.458 ms | 5.200 ms | 4.496 ms |
| Microsoft 2002, not used for training | 2.837 ms | 2.694 ms | 2.353 ms |

PGO reached approximately 1.32 GB/s on 2026, or 22.3% less time than that batch's
baseline. All five exported native outputs matched exactly. Shipping PGO would
require a repeatable profile-training build workflow; the experiment is retained
for review rather than changing the normal build.

Validation of the retained source changes: all 25 filings matched frozen outputs
and the staged API with default, SEC, and custom-column rules; 1,500 malformed
documents, 120 large malformed/repeated-tag documents, and 15,000 malformed/Unicode
attribute cases passed. HTML5 entity checks, AddressSanitizer with arena allocation
boundaries, and guarded input boundaries passed. Five new regression tests cover
sampled-fingerprint collisions, cached visibility/quotes/entities, stack growth,
closing-tag forms, and the custom blank set. The extension was rebuilt normally.

Run the focused regressions with `python -m unittest discover -s tests -v`.
Experiment drivers are `build/experiment_frontend_round2.py`,
`build/try_*_round2.py`, and `build/profile_*round2*.py`. Frozen sources, binaries,
raw timing samples, and exported outputs are in `build/frontend-round2/`.
Primary timings: `results-baseline-candidate.json`; PGO comparison:
`results-baseline-candidate-candidatepgo.json` in that directory.

