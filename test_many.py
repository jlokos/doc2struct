from doc2struct import parse_html
from pathlib import Path
from time import perf_counter

directory = Path(r"C:\Users\jgfri\Documents\datamule\oss\packages\doc2struct\data\filings\many_10k")
paths = sorted(
    path for path in directory.rglob("*")
    if path.is_file() and path.suffix.lower() in {".htm", ".html"}
)

total_parse_time = 0.0
total_bytes = 0
for path in paths:
    html_bytes = path.read_bytes()
    start = perf_counter()
    rows = parse_html(html_bytes, "SEC:10-K")
    total_parse_time += perf_counter() - start
    total_bytes += len(html_bytes)

print(f"Total parsing time for {len(paths)} files: {total_parse_time:.3f} seconds")
print(f"Total parsed: {total_bytes / 1_000_000:.3f} MB")
