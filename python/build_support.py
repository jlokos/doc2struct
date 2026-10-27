"""Native build support; optional MSVC PGO never changes default CPU targets."""
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

from setuptools.command.build_ext import build_ext
from setuptools.errors import OptionError, SetupError


class BuildNative(build_ext):
    user_options = build_ext.user_options + [
        ('pgo-training=', None, 'directory of representative HTML files for MSVC x64 PGO'),
        ('pgo-rules=', None, 'rules preset for PGO training (default: SEC:10-K)'),
    ]

    def initialize_options(self):
        super().initialize_options()
        self.pgo_training = None
        self.pgo_rules = 'SEC:10-K'
        self._pgo_output = None

    def finalize_options(self):
        super().finalize_options()
        if self.pgo_training:
            self.pgo_training = str(Path(self.pgo_training).resolve())
            if not html_files(self.pgo_training):
                raise OptionError('--pgo-training must contain .htm or .html files')

    def run(self):
        # Ship a private engine so another PDFium wrapper cannot initialize or
        # destroy our engine, or bypass the C library's PDFium mutex.
        arch=platform.machine().lower()
        arch={'amd64':'x86_64','aarch64':'arm64'}.get(arch,arch)
        if sys.platform=='win32':
            key='win_'+('amd64' if sys.maxsize>2**32 and arch=='x86_64' else 'arm64' if arch=='arm64' else 'x86')
        else:
            key=('macos' if sys.platform=='darwin' else 'linux')+'_'+arch
        override=os.environ.get('DOC2STRUCT_PDFIUM_LIBRARY')
        source=Path(override).resolve().parent if override else Path(__file__).resolve().parent/'_native_source/c/vendor/pdfium/runtime'/key
        binaries=[Path(override).resolve()] if override else list(source.glob('doc2struct_pdfium.*'))
        binaries=[p for p in binaries if p.suffix in ('.dll','.so','.dylib') and p.is_file()]
        if len(binaries) != 1:
            raise SetupError('Custom PDFium runtime is required for '+key+'. Run tools/build_pdfium.py --fetch, or set DOC2STRUCT_PDFIUM_LIBRARY to a bundled custom runtime.')
        binary = binaries[0]
        metadata=source/'version.json'
        if not metadata.is_file():
            raise SetupError('Custom PDFium version.json is missing beside the library')
        version=json.loads(metadata.read_text())
        if version.get('bridge_abi')!=1 or version.get('sha256')!=hashlib.sha256(binary.read_bytes()).hexdigest():
            raise SetupError('Custom PDFium ABI or binary checksum does not match version.json')
        import ctypes
        try:
            engine=ctypes.CDLL(str(binary))
            if engine.DS_PDF_BridgeVersion()!=1: raise ValueError('unsupported ABI')
        except (OSError,AttributeError,ValueError) as error:
            raise SetupError('Cannot load the required doc2struct PDFium bridge: '+str(error)) from error
        licenses=list((source/'licenses').glob('*'))
        if not licenses: raise SetupError('Custom PDFium redistribution licenses are missing')
        super().run()
        destinations = [Path(self.build_lib) / 'doc2struct' / '_pdfium']
        if self.inplace:
            destinations.append(Path(self.get_finalized_command('build_py').get_package_dir('doc2struct')) / '_pdfium')
        for destination in destinations:
            destination.mkdir(parents=True, exist_ok=True)
            if binary.resolve()!=(destination / ('doc2struct_pdfium' + binary.suffix)).resolve():
                shutil.copy2(binary, destination / ('doc2struct_pdfium' + binary.suffix))
            if metadata.resolve()!=(destination/'version.json').resolve():
                shutil.copy2(metadata, destination / 'version.json')
            (destination / 'licenses').mkdir(exist_ok=True)
            for license in licenses:
                target=destination/'licenses'/license.name
                if license.is_file() and license.resolve()!=target.resolve(): shutil.copy2(license,target)

    def get_ext_fullpath(self, name):
        if self._pgo_output is not None:
            return str(self._pgo_output)
        return super().get_ext_fullpath(name)

    def build_extension(self, ext):
        if not self.pgo_training:
            return super().build_extension(ext)
        if (self.compiler.compiler_type != 'msvc' or self.plat_name != 'win-amd64'
                or sys.maxsize <= 2**32):
            raise OptionError('PGO currently requires MSVC on Windows x64; omit --pgo-training for a portable build')

        destination = Path(self.get_ext_fullpath(ext.name)).resolve()
        scratch = Path(self.build_temp).resolve() / 'pgo'
        scratch.mkdir(parents=True, exist_ok=True)
        # A fresh profile prevents stale training data from affecting a new build.
        stage = Path(tempfile.mkdtemp(prefix='native-', dir=scratch))
        binary = stage / destination.name
        old_temp, old_force = self.build_temp, self.force
        old_compiler_force = self.compiler.force
        old_compile, old_link = ext.extra_compile_args, ext.extra_link_args
        flags = list(old_link or []) + ['/LTCG', '/OPT:REF', '/PGD:' + str(stage / 'native.pgd')]
        try:
            self._pgo_output = binary
            self.build_temp = str(stage / 'obj')
            self.force = self.compiler.force = True
            ext.extra_compile_args = list(old_compile or []) + ['/GL']
            ext.extra_link_args = flags + ['/GENPROFILE']
            super().build_extension(ext)

            compiler_bin = Path(self.compiler.cc).parents[2] / 'Hostx64/x64'
            self.announce('Training PGO on ' + self.pgo_training, level=2)
            subprocess.run([
                sys.executable, str(Path(__file__).resolve()), str(binary),
                self.pgo_training, self.pgo_rules, str(compiler_bin),
            ], check=True)

            # Relink the same objects used to collect the profile. Do not publish
            # an instrumented extension if compilation, training or relinking fails.
            objects = sorted(str(p) for p in Path(self.build_temp).rglob('*.obj'))
            if not objects:
                raise SetupError('PGO build produced no object files')
            self.compiler.link_shared_object(
                objects + list(ext.extra_objects or []), str(binary),
                libraries=self.get_libraries(ext), library_dirs=ext.library_dirs,
                runtime_library_dirs=ext.runtime_library_dirs,
                export_symbols=self.get_export_symbols(ext), debug=self.debug,
                extra_postargs=flags + ['/USEPROFILE'], target_lang='c',
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(binary, destination)
            self.announce('PGO build installed; profile and training manifest: ' + str(stage), level=2)
        finally:
            self._pgo_output = None
            self.build_temp, self.force = old_temp, old_force
            self.compiler.force = old_compiler_force
            ext.extra_compile_args, ext.extra_link_args = old_compile, old_link


def html_files(directory):
    return sorted(p for p in Path(directory).rglob('*')
                  if p.is_file() and p.suffix.lower() in {'.htm', '.html'})


def train(binary, directory, rules, compiler_bin):
    # Keep the runtime directory handle alive until the instrumented DLL unloads.
    with os.add_dll_directory(compiler_bin):
        spec = importlib.util.spec_from_file_location('doc2struct._native', binary)
        native = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = native
        spec.loader.exec_module(native)
        definition = json.loads(native.resolve_rules(rules, True))
        prepared = native.prepare_preset(rules)
        inputs = [(p, p.read_bytes()) for p in html_files(directory)]
        if not inputs:
            raise ValueError('PGO training directory contains no HTML files')
        manifest = {
            'rules': rules, 'definition': definition, 'passes': 3,
            'files': [{'path': str(p), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                      for p, data in inputs],
        }
        Path(binary).with_name('training.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        for _ in range(3):
            for _, data in inputs:
                native.parse_html(data, prepared, True, False, False, 100)
        print(f'PGO training completed: {len(inputs)} HTML files, 3 passes', flush=True)


if __name__ == '__main__':
    train(*sys.argv[1:])
