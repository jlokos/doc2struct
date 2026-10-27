# Production integration

The winning tokenizer changes are now in `c/tokenizer.c`, with SSE2 guards and a scalar / `memcmp` fallback. The local extension was rebuilt with PGO. `build_support.py` supplies opt-in MSVC x64 PGO through `setup.py build_ext --pgo-training ...`; normal installs remain portable.

Final production comparison: 146 filings, 434.667 MB, 12 measured rounds after a warmup, pinned to one performance core. Builds alternate file by file; all six execution orders are balanced every six rounds. Inputs and rules are prepared before timing. Output disposal is included.

| Production build | Median paired full-parser throughput |
|---|---:|
| baseline | 1.0000x |
| integrated_plain | 1.0270x |
| integrated_pgo | 1.1109x |

The PGO build improves full-parser throughput by approximately 11.1% in this comparison. The earlier 20% result measured the tokenizer/normalizer frontend in the experimental harness; this integration check measures full parsing. Independent corpus-level medians were unstable during a system-speed shift, so the final comparison uses balanced per-file timing and median paired ratios.

Normal, forced-scalar, and PGO builds matched baseline tokens and rows on all 146 files and 17,729 generated token cases. They also matched 3,556 extra parse cases and 22 additional filings under both default and SEC:10-K rules. The final installed PGO binary was rechecked on the token fixtures and full corpus.

A wheel was successfully built from the source distribution. A deliberately failed PGO training run left the installed extension unchanged. The source distribution includes the new build helper and performance instructions. No README edits or tests/ directory were added.

Raw samples, binary/source hashes and check counts are in [integration_results.json](integration_results.json). Build instructions are in [PERFORMANCE.md](../../PERFORMANCE.md). Reproduce the paired comparison after building with `python experimental/tokenizer_simd/integration.py paired --rounds 12`.
