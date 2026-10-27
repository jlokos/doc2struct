import json
import os
import webbrowser
from pathlib import Path
import polars as pl
from doc2struct import (convert_html_to_instructions, convert_instructions_to_standardized_text,
                        tokenize, visualize_tokens, visualize_instructions, visualize_standardized_text)
from time import time

path = r"C:\Users\jgfri\Documents\datamule\oss\packages\doc2struct\data\filings\msft_10k\2021-07-29\000156459021039151\msft-10k_20210630.htm"
out = "testing"
os.makedirs(out, exist_ok=True)


def write_csv(rows, file):
    # csv cannot hold lists, so list values (e.g. matrix) are written as json text
    rows = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()} for r in rows]
    pl.DataFrame(rows, infer_schema_length=None).write_csv(file)


with open(path, "rb") as f:
    content = f.read()

webbrowser.open(Path(path).resolve().as_uri())   # the original html, to compare against the visualizations

s = time()
visualize_tokens(list(tokenize(content)), f"{out}/tokens.html")

instructions = convert_html_to_instructions(content)
visualize_instructions(instructions, f"{out}/instructions.html")
write_csv(instructions, f"{out}/instructions.csv")

standardized_text = convert_instructions_to_standardized_text(instructions, "SEC:10-K")
visualize_standardized_text(standardized_text, f"{out}/standardized_text.html")
write_csv(standardized_text, f"{out}/standardized_text.csv")
print(time() - s)