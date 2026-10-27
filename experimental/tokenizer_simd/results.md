# Tokenizer SIMD experiments — 2026-10-27

The winning source changes have since been integrated. See
[production integration results](integration_results.md) for the current build;
the measurements below describe the original isolated experiment.

Best measured full-parser throughput: **1.108x baseline** with `equal_fused_pgo`. Best source-only result: **1.049x** with `equal_fused`. Production sources were not modified.

The corpus contains **146 HTML filings, 434.667 MB** from `data/filings/many_10k`. Other files in that directory are excluded. The exact paths and content hashes are in [corpus_manifest.json](corpus_manifest.json).

| Configuration | Full parse, seconds | MB/s | Full parse throughput | Frontend, seconds | Frontend throughput |
|---|---:|---:|---:|---:|---:|
| Current source baseline | 1.111855 | 390.9 | 1.000x | 0.665884 | 1.000x |
| Combined text / entity scan (SSE2) | 1.080460 | 402.3 | 1.029x | 0.640809 | 1.039x |
| Combined scan + short tag equality (SSE2) | 1.059560 | 410.2 | 1.049x | 0.621917 | 1.071x |
| Baseline + PGO | 1.040901 | 417.6 | 1.068x | 0.595947 | 1.117x |
| Combined scan + PGO | 1.018977 | 426.6 | 1.091x | 0.575197 | 1.158x |
| Combined scan + short tag equality + PGO | 1.003846 | 433.0 | 1.108x | 0.554700 | 1.200x |

The winning build reduces full-parse time by **9.7%** and raises throughput by **10.8%**. PGO affects the entire native extension, so its gain is not attributed solely to the tokenizer.

These are medians of **11 measured full-corpus passes**, after one complete warmup for each configuration and mode. Variants ran sequentially in seeded shuffled order, pinned to Windows logical CPU 4, a performance-class core. Inputs and compiled rules were prepared before timing; timing includes parsing, Python row export, and output disposal. The existing 8 MiB native arena cache is enabled. No disk reads, compilation, equality checks, or other benchmark variants ran concurrently with a timed pass.

`frontend` is a lab-only native hook covering input validation/decoding, tokenization, normalization, flow construction, finish, and document cleanup. It excludes standardization and Python row export. It is **not a tokenizer-only measurement**. All variants include the identical hook. Full parse uses the native entry point called by `parse_html(data, "SEC:10-K")`, with default visibility options; Python rule preparation is outside timing.

The first unpinned three-run baseline was 0.891023 seconds (487.8 MB/s). Later CPU placement and system state differ. Use the contemporaneous pinned baseline above for speedup claims, not that preliminary absolute time. Raw samples from every phase are preserved in [results.json](results.json).

The strongest source changes are available as unapplied review patches:

- [fused_text.patch](fused_text.patch): find the next `<` while tracking whether the preceding text contains `&`; bypass the redundant entity search for text known to be entity-free.
- [equal_fused.patch](equal_fused.patch): add bounded SSE2 equality checks for short repeated tags to the combined scan. Every cache hit still requires complete byte equality.

The attribute masks were a useful negative result. The existing template cache already reuses 275.5 MB of markup (63.4% of the input). Computing broad delimiter masks for cache misses adds work without helping those hits. Retained 16-/64-byte masks, wider text scans, AVX2 quote scans, scalar class tables, bulk comment/raw-content skipping, and three cache sizes were all measured.

| Screening variant | Full parse throughput vs paired baseline | Frontend throughput vs paired baseline |
|---|---:|---:|
| `bulk_skip` | 0.994x | 0.999x |
| `fused_text` | 1.034x | 1.059x |
| `avx_quote` | 1.009x | 0.995x |
| `masks16` | 0.981x | 0.958x |
| `masks64` | 0.996x | 0.967x |
| `fused_bulk` | 1.024x | 0.997x |
| `text32` | 1.023x | 1.036x |
| `text64` | 1.013x | 1.006x |
| `avx_codegen` | 1.004x | 0.947x |
| `text32_bulk` | 1.018x | 1.036x |
| `classes` | 1.007x | 0.987x |
| `classes_fused` | 1.022x | 1.048x |
| `cache256` | 0.995x | 0.973x |
| `cache4096` | 0.996x | 1.004x |
| `cache16384` | 0.931x | 0.896x |

The screen used three measured passes per configuration. Small differences there are exploratory; the finalists received a separate nine-pass comparison and the eleven-pass confirmation above. The vector equality experiments are recorded in the nine-pass phase. A total of 22 configurations (baseline plus 21 candidates, including PGO builds) were timed.

**Validation:** every finalist matched baseline token lists and parsed rows on all 146 corpus files and matched 17,729 generated token cases. The extended checks matched 3,556 full-parse cases, including malformed markup, every single-byte input value, Unicode whitespace, visibility settings, cache activation thresholds, and comparison lengths around SIMD boundaries. Twenty-two additional filings matched under both default and SEC:10-K configurations. This establishes parity with the existing parser, not independent HTML-standard conformance.

**PGO:** MSVC instruments the native extension, observes three passes over six local `data/filings/test_work` filings, then relinks using that profile. Training inputs are disjoint from the timing corpus by SHA-256 content, including across alternate filenames. Training paths/hashes are recorded in `results.json`. No timing-corpus data trained the PGO builds.

**Scope:** this lab targets Windows x64/MSVC. All variants use `/O2 /GL /std:c11 /utf-8` and `/LTCG /OPT:REF`; AVX2 experiments additionally use `/arch:AVX2` for the tokenizer translation unit. The winning SSE2 source does not require AVX2. The lab does not implement production CPU dispatch or validate performance on other machines. Compiler flags and PGO are experimental, not new package defaults. The corpus was used to select source variants; cross-machine and unseen-corpus speedups remain unmeasured.

Reproduce from the repository root with Python 3.14 and MSVC installed:

```powershell
python experimental/tokenizer_simd/lab.py build baseline fused_text equal_fused
python experimental/tokenizer_simd/pgo.py baseline fused_text equal_fused
python experimental/tokenizer_simd/check.py fused_text equal_fused baseline_pgo fused_text_pgo equal_fused_pgo
python experimental/tokenizer_simd/extended_check.py fused_text equal_fused baseline_pgo fused_text_pgo equal_fused_pgo
python experimental/tokenizer_simd/lab.py measure baseline fused_text equal_fused baseline_pgo fused_text_pgo equal_fused_pgo --rounds 11 --label confirmation
```

The first build freezes the current C sources and rules under `artifacts/snapshot`; later builds use that snapshot. Generated sources, binaries, build logs, and complete raw phase results remain under `artifacts/`. The original C-source hashes are retained in [source_manifest.json](source_manifest.json); all production C files still match them. `readme.md` was not edited and no `tests/` directory was added.
