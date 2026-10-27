"""Configure/build the private chromium/7825 checkout in build/pdf-fast/pdfium.

Run with --fetch to populate the private checkout and dependencies first.
Windows build recipe for this machine's VS 2026 / SDK 26100 installation.
All patches affect the private checkout only.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'build/pdf-fast/pdfium'
PDFIUM_REVISION='d5960c8270a7d06203316c2d6f0ba606547fdb07'
DEPOT_REVISION='3218cfc968b246bf2498fd13f707851a0b1cd408'


def fetch():
    workspace=SOURCE.parent
    workspace.mkdir(parents=True,exist_ok=True)
    depot=workspace/'depot_tools'
    env=dict(os.environ,DEPOT_TOOLS_WIN_TOOLCHAIN='0',DEPOT_TOOLS_UPDATE='0',
             CIPD_CACHE_DIR=str(workspace/'cipd-cache'))
    env['PATH']=str(depot)+os.pathsep+str(Path(sys.executable).parent)+os.pathsep+env['PATH']
    for path,url,revision in [
        (depot,'https://chromium.googlesource.com/chromium/tools/depot_tools.git',DEPOT_REVISION),
        (SOURCE,'https://pdfium.googlesource.com/pdfium.git',PDFIUM_REVISION),
    ]:
        if not (path/'.git').exists():
            subprocess.run(['git','init',str(path)],check=True,env=env)
            subprocess.run(['git','-C',str(path),'remote','add','origin',url],check=True,env=env)
            subprocess.run(['git','-C',str(path),'fetch','--depth','1','origin',revision],check=True,env=env)
            subprocess.run(['git','-C',str(path),'checkout','--detach','FETCH_HEAD'],check=True,env=env)
    (workspace/'.gclient').write_text("solutions = [{'name':'pdfium','url':'https://pdfium.googlesource.com/pdfium.git','managed':False,'custom_vars':{'checkout_configuration':'minimal'}}]\ntarget_os=['win']\n")
    subprocess.run([sys.executable,str(depot/'gclient.py'),'sync','--no-history','--nohooks','-j','8'],
                   cwd=workspace,env=env,check=True)
    # Minimal checkout omits this dependency, although GN still loads its test target.
    simd=SOURCE/'third_party/simdutf'
    if not (simd/'.git').exists():
        subprocess.run(['git','init',str(simd)],check=True,env=env)
        subprocess.run(['git','-C',str(simd),'fetch','--depth','1',
            'https://chromium.googlesource.com/chromium/src/third_party/simdutf',
            'f7356eed293f8208c40b3c1b344a50bd70971983'],check=True,env=env)
        subprocess.run(['git','-C',str(simd),'checkout','--detach','FETCH_HEAD'],check=True,env=env)


def replace(path, old, new):
    text=path.read_text()
    if new in text:
        return
    if old not in text:
        assert new in text, (path,old)
        return
    path.write_text(text.replace(old,new,1))


def main():
    arguments=argparse.ArgumentParser()
    arguments.add_argument('--fetch',action='store_true')
    arguments.add_argument('--optimized',action='store_true',help='Official release settings and ThinLTO; no PGO')
    options=arguments.parse_args()
    if options.fetch: fetch()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
    if revision!=PDFIUM_REVISION:
        raise RuntimeError(f'Expected PDFium {PDFIUM_REVISION}, found {revision}')
    replace(SOURCE/'.gn', 'script_executable = "python3"',
            'script_executable = "' + Path(sys.executable).as_posix() + '"')
    # This revision's explicit-toolchain branch returns a list to exec_script,
    # which requires a nonempty string argument on Windows.
    toolchain=SOURCE/'build/config/win/visual_studio_version.gni'
    value='visual_studio_runtime_dirs = visual_studio_path + "/VC/Redist/MSVC/14.51.36231/x64/Microsoft.VC145.CRT"'
    contents=toolchain.read_text().replace('visual_studio_runtime_dirs = []',value)
    contents=contents.replace('visual_studio_runtime_dirs = ""',value)
    toolchain.write_text(contents)
    replace(SOURCE/'build/vs_toolchain.py', '    _CopyDebugger(target_dir, target_cpu)',
            '    # Standalone release experiment does not package Windows debugging tools.')
    replace(SOURCE/'build/vs_toolchain.py', '\n  _CopyDebugger(target_dir, target_cpu)',
            '\n  # Standalone release experiment does not package Windows debugging tools.')
    for name in ['bridge.cpp','bridge.h']:
        text=(HERE/name).read_text()
        if name=='bridge.h': text=text.replace('"fpdfview.h"','"public/fpdfview.h"')
        target=SOURCE/'fpdfsdk'/name
        if not target.exists() or target.read_text()!=text: target.write_text(text)
    sdk=SOURCE/'fpdfsdk/BUILD.gn'
    sdk.write_text(sdk.read_text().replace('    "bridge.cpp",\n','').replace('    "bridge.h",\n',''))
    replace(SOURCE/'fpdfsdk/BUILD.gn','source_set("fpdfsdk") {\n  sources = [',
            'source_set("fpdfsdk") {\n  sources = [\n    "bridge.cpp",\n    "bridge.h",')
    replace(SOURCE/'BUILD.gn','component("pdfium") {','shared_library("pdfium") {')
    replace(SOURCE/'BUILD.gn','config("pdfium_public_config") {\n  defines = []',
            'config("pdfium_public_config") {\n  defines = [ "FPDF_SHARED_LIBRARY" ]')
    replace(SOURCE/'public/fpdfview.h', '#if defined(COMPONENT_BUILD)\n',
            '#if defined(COMPONENT_BUILD) || defined(FPDF_SHARED_LIBRARY)\n')
    parser=SOURCE/'core/fpdfapi/page/cpdf_streamcontentparser.cpp'
    replace(parser,'namespace {', '''// Experimental callbacks are unset for every normal PDFium parse.
bool (*ds_pdf_text_sink)(CPDF_TextObject*) = nullptr;
void (*ds_pdf_form_sink)() = nullptr;

namespace {''')
    replace(parser,'    object_holder_->AppendPageObject(std::move(pText));',
            '''    if (!ds_pdf_text_sink || !ds_pdf_text_sink(pText.get()))
      object_holder_->AppendPageObject(std::move(pText));''')
    replace(parser,'  if (type == "Form") {',
            '  if (type == "Form") {\n    if (ds_pdf_form_sink) ds_pdf_form_sink();')
    output='out/doc2struct_lto' if options.optimized else 'out/doc2struct'
    destination=SOURCE/output
    destination.mkdir(parents=True,exist_ok=True)
    args='''is_debug = false
is_component_build = false
pdf_enable_v8 = false
pdf_enable_xfa = false
pdf_use_skia = false
pdf_use_partition_alloc = false
pdf_enable_fontations = false
pdf_enable_rust_png = false
enable_rust = false
use_custom_libcxx = false
clang_use_chrome_plugins = false
treat_warnings_as_errors = false
symbol_level = 0
icu_use_data_file = false
visual_studio_path = "C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools"
visual_studio_version = "2026"
windows_sdk_path = "C:/Program Files (x86)/Windows Kits/10"
wdk_path = "C:/Program Files (x86)/Windows Kits/10"
windows_sdk_version = "10.0.26100.0"
'''
    if options.optimized:
        # Chromium's official Windows timestamp helper assumes chrome/VERSION.
        # A standalone DLL can use the PDFium source commit time directly.
        (SOURCE/'build/doc2struct_timestamp.py').write_text(
            'from pathlib import Path\nprint((Path(__file__).parent / "util/LASTCHANGE.committime").read_text().strip())\n')
        args+='is_official_build = true\nuse_thin_lto = true\nchrome_pgo_phase = 0\ncompute_build_timestamp = "//build/doc2struct_timestamp.py"\n'
    (destination/'args.gn').write_text(args)
    env=dict(os.environ,DEPOT_TOOLS_WIN_TOOLCHAIN='0',DEPOT_TOOLS_UPDATE='0')
    env['vs2026_install']='C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools'
    env['GYP_MSVS_OVERRIDE_PATH']=env['vs2026_install']
    env['GYP_MSVS_VERSION']='2026'
    env['PATH']=str(ROOT/'build/pdf-fast/depot_tools')+os.pathsep+env['PATH']
    subprocess.run([sys.executable,'build/util/lastchange.py','-o','build/util/LASTCHANGE'],cwd=SOURCE,env=env,check=True)
    subprocess.run([str(SOURCE/'buildtools/win/gn.exe'),'gen',output],cwd=SOURCE,env=env,check=True)
    subprocess.run([str(SOURCE/'third_party/ninja/ninja.exe'),'-C',output,'pdfium','-j','8'],
                   cwd=SOURCE,env=env,check=True)


if __name__=='__main__': main()
