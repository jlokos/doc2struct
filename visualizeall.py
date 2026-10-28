from doc2struct import parse_html, parse_pdf, visualize_standardized_text
from pathlib import Path
from time import perf_counter
import tarfile

directory = Path(r"C:\Users\jgfri\Documents\datamule\oss\packages\doc2struct\data\filings\2005_13fhr")
output_directory = Path(__file__).parent / "testing" / "visualizeall"

def documents(directory):
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".tar":
            # Read members directly; no extraction or whole-archive buffering.
            with tarfile.open(path, "r|*") as archive:
                for member in archive:
                    member_path = Path(member.name)
                    if member_path.name.startswith("R"):
                        continue
                    if member.isfile() and member_path.suffix.lower() in {".pdf", ".htm", ".html"}:
                        with archive.extractfile(member) as document:
                            yield member_path, document.read()
        elif path.suffix.lower() in {".pdf", ".htm", ".html"}:
            if path.name.startswith("R"):
                continue
            yield path, path.read_bytes()


if __name__ == "__main__":
    total_parse_time = 0.0
    total_bytes = 0
    total_chars = 0
    total_files = 0
    output_directory.mkdir(parents=True, exist_ok=True)
    for path, content in documents(directory):
        extension = path.suffix.lower()
        start = perf_counter()
        if extension == ".pdf":
            rows = parse_pdf(content, "SEC:10-K")
        elif extension in {".htm", ".html"}:
            rows = parse_html(content, "SEC:10-K")
        else:
            continue
        total_parse_time += perf_counter() - start
        total_bytes += len(content)
        if extension in {".htm", ".html"}:
            total_chars += len(content.decode("utf-8", errors="replace"))
        total_files += 1
        visualize_standardized_text(rows, output_directory / f"{total_files:06d}_{path.stem}.html")
        if total_files % 10 == 0:
            input("Press Enter to generate the next 3 visualizations...")

    print(f"Total parsing time for {total_files} files: {total_parse_time:.3f} seconds")
    print(f"Total parsed: {total_bytes / 1_000_000:.3f} MB")
    print(f"Total HTML characters: {total_chars:,}")
