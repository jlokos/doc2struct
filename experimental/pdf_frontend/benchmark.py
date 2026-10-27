"""Sequential alternating-order comparisons; all inputs are preloaded by the worker."""
import argparse
import json
import platform
import statistics
import subprocess
import sys

from experiment import BUILD, HERE, ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--optimized',action='store_true')
    options=parser.parse_args()
    stock=ROOT/'python/src/doc2struct/_pdfium/doc2struct_pdfium.dll'
    custom=BUILD/('pdfium/out/doc2struct_lto/pdfium.dll' if options.optimized else 'pdfium/out/doc2struct/pdfium.dll')
    variants=[('baseline',stock),('axis',stock),('styles',stock),
              ('baseline',custom),('bridge',custom),('stream',custom)]
    if options.optimized:
        variants=[('baseline',stock),('baseline',custom),('bridge',custom),('stream',custom)]
    results={}
    for repeat in range(3):
        order=variants if repeat%2==0 else list(reversed(variants))
        for variant,engine in order:
            name=variant+('_lto' if options.optimized and engine==custom else '_custom' if engine==custom else '_stock')
            label=f'timing_{name}_{repeat}'
            command=[sys.executable,str(HERE/'experiment.py'),'measure',variant,
                     '--engine',str(engine),'--passes','1','--timing-only','--label',label]
            output=subprocess.run(command,check=True,capture_output=True,text=True)
            record=json.loads((BUILD/label/'results.json').read_text())
            result=results.setdefault(name,dict(variant=variant,engine_sha256=record['engine_sha256'],
                files=record['files'],bytes=record['bytes'],seconds=[]))
            result['seconds']+=record['seconds']
            if 'bridge_stats' in record: result['page_counts']=record['bridge_stats']
            print(name,round(record['seconds'][0],3),flush=True)
    for name,result in results.items():
        result['median_seconds']=statistics.median(result['seconds'])
        result['MB_per_second']=result['bytes']/1e6/result['median_seconds']
    report=dict(python=sys.version,platform=platform.platform(),processor=platform.processor(),
                timing='Native parse_pdf including Python result construction; preloaded bytes; no PGO; three fresh processes per variant, alternating order.',
                results=results)
    (BUILD/('benchmark_lto.json' if options.optimized else 'benchmark.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
