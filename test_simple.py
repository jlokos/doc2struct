from doc2struct import parse_html
from time import time

path = r"C:\Users\jgfri\Documents\datamule\oss\packages\doc2struct\data\filings\msft_10k\2021-07-29\000156459021039151\msft-10k_20210630.htm"
with open(path, "rb") as f:
    html_bytes = f.read()


s = time()
#rows = parse_html(html_bytes)                # default columns
rows = parse_html(html_bytes, "SEC:10-K")    # with rules
print(time()-s)