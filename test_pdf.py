import json
import os
import tarfile
import webbrowser
from pathlib import Path
import polars as pl
from doc2struct import (convert_pdf_to_instructions, convert_instructions_to_standardized_text,
                        visualize_instructions, visualize_standardized_text)
from time import time

path = Path(__file__).parent / "data/filings/10k_pdf_sample/batch_000001.tar"
out = "testing/pdf"
os.makedirs(out, exist_ok=True)


def write_csv(rows, file):
    # csv cannot hold lists, so list values (e.g. matrix) are written as json text
    rows = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()} for r in rows]
    pl.DataFrame(rows, infer_schema_length=None).write_csv(file)


with tarfile.open(path, "r|*") as archive:
    member = next(m for m in archive if m.isfile() and Path(m.name).suffix.lower() == ".pdf")
    with archive.extractfile(member) as document:
        content = document.read()

original = Path(out) / "original.pdf"
original.write_bytes(content)
webbrowser.open(original.resolve().as_uri())  # the original PDF, to compare against the visualizations

s = time()
instructions = convert_pdf_to_instructions(content)
#visualize_instructions(instructions, f"{out}/instructions.html")
#write_csv(instructions, f"{out}/instructions.csv")

standardized_text = convert_instructions_to_standardized_text(instructions, "SEC:10-K")
visualize_standardized_text(standardized_text, f"{out}/standardized_text.html")
#write_csv(standardized_text, f"{out}/standardized_text.csv")
print(time() - s)
