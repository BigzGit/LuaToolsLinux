"""Exercise isolated shell functions with network and privileged operations stubbed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_ui_injector_finds_debian_root_once(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / 'backend'))
        import ui_injector
        with tempfile.TemporaryDirectory() as d:
            steam = Path(d, '.steam')
            (steam / 'steamui').mkdir(parents=True)
            (steam / 'root').symlink_to(steam, target_is_directory=True)
            index = steam / 'steamui/index.html'
            index.write_text('<html><body></body></html>')
            public = Path(d, 'plugin/public')
            public.mkdir(parents=True)
            (public / 'luatools.js').write_text('console.log("test");')
            with patch.dict(os.environ, HOME=d):
                stats = ui_injector.ensure_ui_injection(str(public.parent))
                self.assertEqual(stats['roots_seen'], 1)
                self.assertEqual(stats['roots_patched'], 1)
                self.assertEqual(ui_injector.ensure_ui_injection(str(public.parent))['roots_patched'], 0)
            self.assertIn(ui_injector.MARKER_START, index.read_text())

    def test_millennium_checksum_failure_stops_before_changes(self):
        source=(ROOT/'Install-Millenium.sh').read_text().rsplit('main "$@"',1)[0]
        with tempfile.TemporaryDirectory() as d:
            script=source+'''
is_root() { return 1; }
verify_platform() { echo linux-x86_64; }
check_dependencies() { :; }
confirm_installation() { :; }
format_size() { echo 1; }
curl() { echo invalid-checksum; }
download_package() { touch "$2"; }
sha256sum() { return 1; }
remove_old_installation() { touch "$MARKER"; }
extract_package() { touch "$MARKER"; }
install_millennium() { touch "$MARKER"; }
post_install() { touch "$MARKER"; }
main
'''
            result=subprocess.run(['bash'],input=script,text=True,cwd=d,env=dict(os.environ,MARKER=d+'/mutation'),capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(Path(d,'mutation').exists())
            self.assertIn('FAILED',result.stdout)

    def test_extractors_reject_symlinks_and_traversal(self):
        for filename in ('install.sh','update.sh','install_with_slssteam.sh'):
            source=(ROOT/filename).read_text()
            function=source[source.index('extract_zip() {'):source.index('\n}',source.index('extract_zip() {'))+2]
            for name in ('../escape','/escape','480/../../escape'):
                with self.subTest(script=filename,member=name),tempfile.TemporaryDirectory() as d:
                    archive=Path(d,'input.zip');dest=Path(d,'out');dest.mkdir()
                    with zipfile.ZipFile(archive,'w') as z:z.writestr(name,'bad')
                    result=subprocess.run(['bash','-c',function+'\nextract_zip "$1" "$2"','test',str(archive),str(dest)],capture_output=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertFalse(Path(d,'escape').exists())
                    self.assertEqual(list(dest.iterdir()),[])

    def test_generated_wrappers_quote_custom_home(self):
        source=(ROOT/'install_with_slssteam.sh').read_text()
        start=source.index('    mkdir -p "$BIN_DIR"')
        end=source.index('    local ui_output',start)
        block=source[start:end]
        with tempfile.TemporaryDirectory() as d:
            script='''set -euo pipefail
INSTALL_ROOT="$1/path with spaces;$(not-executed)"
VENV_DIR="$INSTALL_ROOT/.venv"
BIN_DIR="$1/bin"
WRAPPER_PATH="$BIN_DIR/luatools"
BRIDGE_STARTER="$BIN_DIR/luatools-bridge"
UI_HEALER="$BIN_DIR/luatools-heal-ui"
generate() {
'''.replace('$(not-executed)', '\\$(not-executed)')+block+'\n}\ngenerate\n'
            result=subprocess.run(['bash','-s','--',d],input=script,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for path in Path(d,'bin').iterdir():
                result=subprocess.run(['bash','-n',str(path)],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('\\;',Path(d,'bin/luatools').read_text())

    def test_embedded_hashes_match_lockfile(self):
        import json
        lock = json.loads((ROOT / 'dependencies.lock.json').read_text())['resources']
        source = (ROOT / 'install.sh').read_text()
        start = source.index('declare -A EMBEDDED_REMOTE_HASHES=(')
        end = source.index('\n}', source.index('lookup_remote_hash() {')) + 2
        block = source[start:end]
        for url, meta in lock.items():
            with self.subTest(url=url):
                result = subprocess.run(
                    ['bash', '-s', url], input=block + '\nlookup_remote_hash "$1"\n',
                    text=True, capture_output=True,
                    env=dict(os.environ, LUATOOLS_LOCK_FILE=''),
                )
                self.assertEqual(result.stdout.strip(), meta['sha256'])

    def test_remote_script_hash_verification_is_enforced(self):
        import hashlib
        import json
        source=(ROOT/'install.sh').read_text()
        start=source.index('lookup_remote_hash() {')
        end=source.index('\n}\n',source.index('run_remote_script() {'))+3
        block=source[start:end]
        with tempfile.TemporaryDirectory() as d:
            fixture=Path(d,'remote.sh'); fixture.write_text('#!/bin/bash\ntouch "$1"\n')
            digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
            url='https://example.test/installer'
            marker=Path(d,'ran')
            lock=Path(d,'lock.json')
            harness='''fail() { echo "FAIL: $*" >&2; exit 1; }
curl() {
    local dest="" arg
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "-o" ]; then dest="$2"; shift 2; else shift; fi
    done
    cp "$STUB_SRC" "$dest"
}
''' + block + '\nrun_remote_script "$@"\n'

            # Pinned and matching: executes.
            lock.write_text(json.dumps({'resources':{url:{'sha256':digest}}}))
            result=subprocess.run(['bash','-s',url,str(marker)],input=harness,text=True,
                                  env=dict(os.environ,LUATOOLS_LOCK_FILE=str(lock),STUB_SRC=str(fixture)),
                                  capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(marker.exists())

            # Pinned but mismatching: fatal, no execution.
            marker.unlink()
            lock.write_text(json.dumps({'resources':{url:{'sha256':'0'*64}}}))
            result=subprocess.run(['bash','-s',url,str(marker)],input=harness,text=True,
                                  env=dict(os.environ,LUATOOLS_LOCK_FILE=str(lock),STUB_SRC=str(fixture)),
                                  capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('mismatch',(result.stdout+result.stderr).lower())
            self.assertFalse(marker.exists())

            # Unpinned: fatal, no execution.
            lock.write_text(json.dumps({'resources':{}}))
            result=subprocess.run(['bash','-s',url,str(marker)],input=harness,text=True,
                                  env=dict(os.environ,LUATOOLS_LOCK_FILE=str(lock),STUB_SRC=str(fixture)),
                                  capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(marker.exists())


if __name__=='__main__':unittest.main()
