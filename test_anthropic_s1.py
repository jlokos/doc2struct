import json
import os
import webbrowser
from pathlib import Path
import polars as pl
from doc2struct import (tokenize, normalize, convert_instructions_to_standardized_text,
                        visualize_tokens, visualize_instructions, visualize_standardized_text)
from time import perf_counter

path = r"C:\Users\jgfri\Documents\datamule\oss\packages\doc2struct\data\filings\anthropic_s1\2026-10-26\000162828026067168\anthropicpbc-sx1.htm"
out = "testing/anthropic_s1"
os.makedirs(out, exist_ok=True)


def write_csv(rows, file):
    # csv cannot hold lists, so list values (e.g. matrix) are written as json text
    rows = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()} for r in rows]
    pl.DataFrame(rows, infer_schema_length=None).write_csv(file)


with open(path, "rb") as f:
    content = f.read()

num_chars = len(content.decode("utf-8", errors="replace"))
size_mb = len(content) / 1_000_000

webbrowser.open(Path(path).resolve().as_uri())   # the original html, to compare against the visualizations

s = perf_counter()
tokens = list(tokenize(content))
#visualize_tokens(tokens, f"{out}/tokens.html")

instructions = normalize(tokens)
#visualize_instructions(instructions, f"{out}/instructions.html")
#write_csv(instructions, f"{out}/instructions.csv")

standardized_text = convert_instructions_to_standardized_text(instructions, "SEC:S-1")
elapsed = perf_counter() - s
visualize_standardized_text(standardized_text, f"{out}/standardized_text.html")
#write_csv(standardized_text, f"{out}/standardized_text.csv")
print(f"HTML characters: {num_chars:,}")
print(f"HTML size: {size_mb:.3f} MB")
print(f"Parsing time: {elapsed:.3f} seconds")
print(f"Throughput: {size_mb / elapsed:.2f} MB/s | {num_chars / elapsed:,.0f} characters/s")
