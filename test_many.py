from doc2struct import parse_html
from pathlib import Path
from time import perf_counter
import tarfile

directory = Path(r"C:\Users\jgfri\Documents\datamule\oss\packages\doc2struct\data\filings\10k_2025")

def html_documents(directory):
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".tar":
            # Read members directly; no extraction or whole-archive buffering.
            with tarfile.open(path, "r|*") as archive:
                for member in archive:
                    if member.isfile() and Path(member.name).suffix.lower() in {".htm", ".html"}:
                        with archive.extractfile(member) as document:
                            yield document.read()
        elif path.suffix.lower() in {".htm", ".html"}:
            yield path.read_bytes()


if __name__ == "__main__":
    total_parse_time = 0.0
    total_bytes = 0
    total_files = 0
    for html_bytes in html_documents(directory):
        start = perf_counter()
        rows = parse_html(html_bytes, "SEC:10-K")
        total_parse_time += perf_counter() - start
        total_bytes += len(html_bytes)
        total_files += 1

    print(f"Total parsing time for {total_files} files: {total_parse_time:.3f} seconds")
    print(f"Total parsed: {total_bytes / 1_000_000:.3f} MB")
