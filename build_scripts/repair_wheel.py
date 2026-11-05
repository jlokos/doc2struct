"""Repair platform dependencies, then refresh bundled PDFium hashes and RECORD.

PDFium is loaded at runtime rather than linked to the extension. On Windows,
analyze existing DLLs as well as the extension; on Linux auditwheel examines all
ELF files, including the private engine. Changes to RPATH/install names made by
repair tools must also be reflected in our runtime metadata.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import zipfile


def repair(wheel, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='doc2struct-repair-') as temp:
        if sys.platform == 'win32':
            command = ['delvewheel', 'repair', '--analyze-existing', '--include', 'vcruntime140.dll', '--no-mangle-all']
        elif sys.platform == 'darwin':
            command = ['delocate-wheel', '--require-archs', platform.machine()]
        else:
            command = ['auditwheel', 'repair', '--plat', 'manylinux_2_34_' + platform.machine()]
        subprocess.run(command + ['-w', temp, str(wheel)], check=True)
        repaired, = Path(temp).glob('*.whl')
        with zipfile.ZipFile(repaired) as archive:
            entries = [(info, archive.read(info)) for info in archive.infolist()]
        contents = {info.filename: data for info, data in entries}
        metadata_name, = (name for name in contents if name.endswith('doc2struct/_pdfium/version.json'))
        engine_name, = (name for name in contents if '/_pdfium/doc2struct_pdfium.' in name)
        metadata = json.loads(contents[metadata_name])
        metadata['sha256'] = hashlib.sha256(contents[engine_name]).hexdigest()
        contents[metadata_name] = (json.dumps(metadata, indent=2) + '\n').encode()
        record, = (name for name in contents if name.endswith('.dist-info/RECORD'))
        output = io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\n')
        for name, data in sorted(contents.items()):
            if name != record and not name.endswith('/'):
                digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
                writer.writerow((name, 'sha256=' + digest, len(data)))
        writer.writerow((record, '', ''))
        contents[record] = output.getvalue().encode()
        with zipfile.ZipFile(destination / repaired.name, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for info, _ in entries:
                archive.writestr(info, contents[info.filename])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    repair(args.wheel, args.destination)
