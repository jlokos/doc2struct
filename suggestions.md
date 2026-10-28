# Implemented shared heading-style default

The implementation and cleanup are on `shared-heading-cleanup` in this checkout. The `master` branch reference is unchanged.

- Shared `header_styles` default: `bold`, `all_caps`, or `proper_case` (any one).
- Shared `lists.max_tail_rows` remains **1**.
- Heading rules without `requires` inherit the shared style policy.
- An explicit `requires` overrides it: `[]` permits unstyled headings; a nonempty list requires every listed style.
- `header_styles: []` disables the shared gate for a custom ruleset.
- Numbered SEC headings have explicit opt-outs so plain item, part, article, section, proposal, and number headings remain recognized. Existing per-rule style requirements are preserved.

The repeated S-1 alternatives are removed. Original regexes, numeric redundancy rules, page labels, ownership-field handling, and table annotations are unchanged. All other experimental candidates were discarded.

Validation passed:

- Native extension build and standalone CMake build.
- Existing Python checks, including shared-style inheritance/overrides, serialization, configuration errors, merge behavior, list-tail default, and 207 fixtures.
- Python/CLI parity and PDF checks.
- Both native C checks.
- All 3,424 survey inputs: 98 outputs changed; no missing payload tokens in the comparison. This checks content preservation, not complete semantic accuracy.

Old investigation outputs, candidate JSON files, experiment labs, temporary scripts, caches, package metadata, logs, and build intermediates were removed. This checkout retains the implementation and this short record; the redundant investigation clone was removed after transferring the implementation. The existing `readme.md` edit and filing data were preserved.
