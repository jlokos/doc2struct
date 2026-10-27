"""Review parser changes using the staged pipeline from test.py.

Run normally to open each original HTML beside its standardized-text preview.
Use --forms "SC 13G" to review one form, or --no-open to generate files only.
Missing originals are downloaded through datamulehub; XML/PDF are never used.
"""
import argparse
import json
import webbrowser
from pathlib import Path
from time import time

from doc2struct import (
    tokenize, normalize, convert_instructions_to_standardized_text,
    visualize_standardized_text,
)


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "data" / "filings" / "test_work"
OUT = ROOT / "testing" / "test_work"

# Form, accession, exact HTML document filename, issuer, review focus.
# Includes all base forms sharing the changed presets, plus global-rule examples.
# Amendment aliases use the same rules; no separate amendment examples are selected.
SAMPLES = [
    ("20-F", "0001140361-25-016316", "ef20039042_20f.htm", "Nordic American Tankers", "Letter headings and list precedence"),
    ("20-F", "0001140361-25-015768", "ef20038949_20f.htm", "Credicorp", "Letter headings and list precedence"),
    ("SC 13E3", "0001292814-25-002491", "elp20250618_sc13e3.htm", "Energy Company of Parana", "Letter headings and phone numbers"),
    ("EX-99.CERT", "0001193125-25-134542", "d945773dex99cert.htm", "Virtus", "Letter and numbered Item headings"),
    ("N-CSRS", "0000100334-25-000064", "ck0000100334-20250430.htm", "American Century", "Item headings"),
    ("T-3", "0001193125-25-074866", "d925286dt3.htm", "Cannabist", "Numbered sections and list precedence"),
    ("T-3", "0001193805-25-000910", "e664642_t3-gghi.htm", "Greenidge", "Phone numbers; unresolved section layout"),
    ("10-Q", "0000950170-25-064417", "mfin-20250331.htm", "Medallion", "Quarterly Part hierarchy"),
    ("S-1", "0001437749-25-013165", "bkyi20250410_s1.htm", "BIO-key", "Business and Management headings"),
    ("S-1", "0001683168-25-004741", "athbitcoin_is1.htm", "Athena Bitcoin", "Main headings and risk hierarchy"),
    ("10-D", "0001193125-25-081335", "d921428d10d.htm", "Citibank", "Distribution Part hierarchy"),
    ("SD", "0001437749-25-017428", "occ20250514_sd.htm", "Optical Cable", "Sections above Items"),
    ("10-K", "0000320193-25-000079", "aapl-20250927.htm", "Apple", "Phone numbers"),
    ("SC 13D", "0001493152-24-044359", "formsc13d.htm", "MGT Capital", "Signatures and layout tables"),
    ("SC 13G", "0001193125-24-255288", "d839680dsc13g.htm", "Henry Schein", "Item subparts and signatures"),
    ("SC 13G", "0000354204-24-004734", "SEC13G_Filing.htm", "Nordic American Tankers", "Layout tables"),
    ("1-K", "0001213900-25-037678", "ea0239752-1k_2020biolabs.htm", "20/20 Biolabs, Part II HTML", "Signatures"),
    ("1-SA", "0001683168-25-004432", "liquidpiston_1sa.htm", "LiquidPiston", "Signatures"),
    ("8-A12B", "0001104659-25-051541", "tm2515739d2_8a12b.htm", "Wintrust", "Signatures and hyperlink preservation"),
    ("8-A12G", "0001096906-25-000835", "cbds_8a.htm", "Dogecoin Cash", "Signatures and hyperlink preservation"),
    ("DSTRBRPT", "0001193125-25-076186", "d823827ddstrbrpt.htm", "International Finance Corporation", "Signatures"),
    ("8-K12B", "0001193125-25-152807", "d936172d8k12b.htm", "Penguin Solutions", "Alignment overrides inherited centering"),
]


def find_original(accession, filename):
    # Only use this script's datamulehub download directory.
    matches = [p for p in SOURCE_DIR.rglob(filename)
               if p.parent.name.replace("-", "") == accession.replace("-", "")]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple originals found for {accession}/{filename}")
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forms", nargs="+", choices=sorted({s[0] for s in SAMPLES}))
    parser.add_argument("--no-open", action="store_true", help="Generate previews without opening browser tabs")
    args = parser.parse_args()
    samples = [s for s in SAMPLES if not args.forms or s[0] in args.forms]
    missing = [s for s in samples if find_original(s[1], s[2]) is None]
    if missing:
        from datamulehub import sec_filings_archive

        SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {len(missing)} exact HTML examples through datamulehub...", flush=True)
        # The lookup filename filter is an exact string, not a list of names.
        # Separate destinations also let completed examples stay cached.
        for form, accession, filename, issuer, focus in missing:
            destination = SOURCE_DIR / f"{form.replace(' ', '_')}_{accession}"
            print(f"  {form}: {issuer}", flush=True)
            sec_filings_archive.download_tar(
                accession=accession, filename=filename,
                output_dir=str(destination), tar_max_size_mb=None,
                max_workers=8, decomp_workers=2,
            )
            if find_original(accession, filename) is None:
                raise FileNotFoundError(f"datamulehub did not return {accession}/{filename}")

    originals = []
    for form, accession, filename, issuer, focus in samples:
        path = find_original(accession, filename)
        if path is None:
            raise FileNotFoundError(f"datamulehub did not return {form}: {accession}/{filename}")
        if path.suffix.lower() not in (".htm", ".html"):
            raise ValueError(f"HTML input required: {path}")
        originals.append(path)

    OUT.mkdir(parents=True, exist_ok=True)
    previews = []
    for (form, accession, filename, issuer, focus), path in zip(samples, originals):
        s = time()
        content = path.read_bytes()
        tokens = list(tokenize(content))
        instructions = normalize(tokens)
        standardized_text = convert_instructions_to_standardized_text(instructions, f"SEC:{form}")
        name = f"{form.replace(' ', '_')}_{accession}"
        preview = OUT / f"{name}.html"
        visualize_standardized_text(standardized_text, str(preview), open_browser=False)
        (OUT / f"{name}.json").write_text(
            json.dumps(standardized_text, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        previews.append((path, preview))
        print(f"{form} | {issuer} | {focus} | {len(standardized_text)} rows | {time() - s:.2f}s", flush=True)
        print(f"  Original: {path}\n  Preview:  {preview}", flush=True)

    if not args.no_open:
        for path, preview in previews:
            webbrowser.open(path.resolve().as_uri(), new=2)
            webbrowser.open(preview.resolve().as_uri(), new=2)


if __name__ == "__main__":
    main()
