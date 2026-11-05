"""Build, install, verify, and archive the C SDK and standalone CLI.

Run from any directory with a C toolchain and CMake on PATH. PDFium must already
be present in c/vendor/pdfium/runtime/<platform> (or supplied as a CMake option).
Linux releases run this in manylinux_2_34 on the target architecture.
"""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from smoke_release import native_smoke

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', required=True, help='Archive platform label, e.g. linux_aarch64')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build/native-release')
    parser.add_argument('--cmake-arg', action='append', default=[])
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.platform):
        parser.error('Invalid platform label')
    output, build = args.output.resolve(), args.build_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cmake', '-S', str(ROOT), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release', '-DDOC2STRUCT_BUILD_PYTHON=OFF', '-DDOC2STRUCT_BUILD_CLI=ON'] + args.cmake_arg, check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release', '--parallel', '2'], check=True)
    header = (ROOT / 'c/include/doc2struct/doc2struct.h').read_text()
    version = re.search(r'#define DOC2STRUCT_VERSION "([^"]+)"', header).group(1)
    for kind in ('sdk', 'cli'):
        name = f'doc2struct-{version}-{args.platform}-{kind}'
        with tempfile.TemporaryDirectory(prefix='doc2struct-package-') as temp:
            stage = Path(temp) / name
            for component in (('sdk', 'cli') if kind == 'sdk' else ('cli',)):
                subprocess.run(['cmake', '--install', str(build), '--config', 'Release', '--component', component, '--prefix', str(stage)], check=True)
            usage = '''doc2struct {version} ({platform})

Run the standalone parser from any directory:
  bin/doc2struct_parse input.html SEC:10-K
  bin/doc2struct_parse input.pdf

Output is JSON on stdout. Keep the private PDFium library beside the executable
in bin/. DOC2STRUCT_PDFIUM_LIBRARY can override it with an absolute path.
The CLI currently accepts HTML and PDF. The C/Python APIs also accept text and
partial SGML; callers choose the input syntax explicitly.

This archive includes redistribution notices in share/doc2struct/.
Linux binaries require glibc 2.34 or newer (including Amazon Linux 2023).
Mac binaries require macOS 14 or newer. Windows binaries target x64 Windows 10+.
'''.format(version=version, platform=args.platform)
            if kind == 'sdk':
                usage += '''
This SDK contains a static C11 library, headers, the CLI, and private PDFium.
Windows SDK consumers need an MSVC-compatible toolchain and its dynamic CRT.
Configure your CMake project with -DCMAKE_PREFIX_PATH=/path/to/unpacked/sdk:

  find_package(doc2struct CONFIG REQUIRED)
  target_link_libraries(your_app PRIVATE doc2struct::doc2struct)

The package exports doc2struct_PDFIUM_LIBRARY, an absolute path to its bundled
engine. Pass that UTF-8 path to doc2struct_pdfium_init() before parsing PDFs.
When distributing your own executable, copy the runtime and accompanying
licenses, then initialize it using the runtime's deployed absolute path.
'''
            (stage / 'USAGE.txt').write_text(usage, encoding='utf-8')
            archive_format = 'zip' if args.platform.startswith('win') else 'gztar'
            archive = Path(shutil.make_archive(str(output / name), archive_format, root_dir=temp, base_dir=name))
            # Relocate the archive before checking it; original build/stage paths
            # must not supply libraries, headers, or the PDF runtime by accident.
            unpacked = Path(temp) / 'unpacked'
            shutil.unpack_archive(archive, unpacked)
            native_smoke(unpacked / name, sdk=kind == 'sdk')
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
            print('Verified ' + str(archive), flush=True)


if __name__ == '__main__':
    main()
