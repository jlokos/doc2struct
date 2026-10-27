"""Semantic probes for the isolated builds, including known parity gaps."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from experiment import BUILD, ROOT, documents, load


def form_pdf():
    content=b'q 1 0 0 1 50 100 cm /Fm1 Do Q'
    form=b'BT /F1 12 Tf 0 600 Td (Nested form) Tj ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Fm1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream',
        b'<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] /Resources << /Font << /F1 6 0 R >> >> /Length '+str(len(form)).encode()+b' >>\nstream\n'+form+b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    output=bytearray(b'%PDF-1.7\n'); offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(output)); output.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=len(output)
    output.extend(b'xref\n0 7\n0000000000 65535 f \n')
    for offset in offsets: output.extend(f'{offset:010} 00000 n \n'.encode())
    output.extend(f'trailer << /Size 7 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(output)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('variant',choices=['baseline','axis','compact','styles','bridge','stream'])
    ap.add_argument('--engine',type=Path,default=BUILD/'pdfium/out/doc2struct/pdfium.dll')
    ap.add_argument('--corpus',action='store_true',help='Compare all standardized rows against the saved variant run')
    args=ap.parse_args()
    engine=args.engine.resolve()
    baseline=load('baseline',engine)
    candidate=load(args.variant,engine)
    spec=importlib.util.spec_from_file_location('pdf_fixtures',ROOT/'checks/python/pdf.py')
    fixtures=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)
    fixture,text=fixtures.fixture,fixtures.text
    cases={
        'plain':fixture([text('Item 1. Business',font='F2',size=16)+text('Ordinary text.',y=675)]),
        'empty_pages':fixture(['',text('Text'), '']),
        'unicode':fixture([text('AB',font='F4')]),
        'italic':fixture([text('Italic',font='F3')]),
        'scale':fixture(['q 2 0 0 2 0 0 cm '+text('Scale',y=300)+'Q']),
        'split_styles':fixture([text('Hello',x=50)+text('world',x=77.336,font='F2')]),
        'kerning_space':fixture(['BT /F1 12 Tf 50 700 Td [(one) -250 (two)] TJ ET']),
        'actual_text':fixture(['/Span << /ActualText (Replacement) >> BDC '+text('Original')+'EMC']),
        'form':form_pdf(),
        'overprint':fixture([text('Same')+text('Same')]),
        'line_hyphen':fixture([text('forward-')+text('looking',y=684)]),
        'columns':fixture([''.join(text(a,50,y)+text(b,330,y) for a,b,y in
            [('Left first','Right first',700),('Left second','Right second',684),('Left third','Right third',668)])]),
        'table':fixture([''.join(text(a,50,y)+text(b,300,y) for a,b,y in
            [('Year','Sales',700),('2024','123',680),('2025','456',660)])]),
    }
    for rotation in (0,90,180,270):
        cases[f'rotation_{rotation}']=fixture([text('Rotation')],rotate=rotation,crop='20 30 600 780')
    report={}
    for name,pdf in cases.items():
        left=baseline.pdf_instructions(pdf,None); right=candidate.pdf_instructions(pdf,None)
        report[name]={'equal':left==right}
        if left!=right:
            report[name].update(baseline=left,candidate=right)
    (BUILD/args.variant/'checks.json').write_text(json.dumps(report,indent=2))
    # Core decoding and transforms must work even while known text-policy gaps
    # are kept visible as diagnostics rather than hidden by golden snapshots.
    for name in cases.keys()-{'overprint','line_hyphen'}:
        assert report[name]['equal'], (name,report[name])
    for data in (b'', b'not a PDF'):
        try: candidate.pdf_instructions(data,None)
        except ValueError: pass
        else: raise AssertionError('invalid input accepted')
    sample=cases['plain']; expected=candidate.pdf_instructions(sample,None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(output==expected for output in pool.map(lambda _:candidate.pdf_instructions(sample,None),range(32)))
    if args.variant in ('bridge','stream'):
        dll=ctypes.WinDLL(str(candidate._experiment_engine))
        counters=(ctypes.c_uint64*4)()
        getattr(dll,'DS_PDF_GetStreamStats' if args.variant=='stream' else 'DS_PDF_GetStats')(counters)
        assert counters[2]>0, 'fallback path was not exercised'
    print(json.dumps({name:result['equal'] for name,result in report.items()},indent=2))
    if args.corpus:
        saved=json.loads((BUILD/args.variant/'results.json').read_text())
        reference=saved['row_hashes']
        rules=candidate.prepare_preset('SEC:10-K')
        differences=[]
        inputs=list(documents())
        for (name,data),expected in zip(inputs,reference,strict=True):
            rows=candidate.parse_pdf(data,rules,True,None)
            actual=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
            if actual!=expected: differences.append(name)
        result=dict(files=len(inputs),different_documents=differences,
                    engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                    reference_engine_sha256=saved['engine_sha256'])
        (BUILD/args.variant/'checks_corpus.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
        assert not differences, result


if __name__=='__main__': main()
