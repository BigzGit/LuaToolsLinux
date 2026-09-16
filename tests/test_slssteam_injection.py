"""SLSsteam installation/injection detection and launcher patching."""
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import linux_platform


@contextmanager
def _env(sls_dir, launchers, desktop_sources, desktop_target):
    with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES',
                      [str(sls_dir)] if sls_dir else []), \
         patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES',
                      [str(p) for p in launchers]), \
         patch.object(linux_platform, '_STEAM_DESKTOP_SOURCES',
                      [str(p) for p in desktop_sources]), \
         patch.object(linux_platform, 'get_user_desktop_path',
                      return_value=str(desktop_target)):
        yield


def _install_sls(directory):
    sls_dir = Path(directory) / '.local/share/SLSsteam'
    sls_dir.mkdir(parents=True)
    (sls_dir / 'SLSsteam.so').touch()
    (sls_dir / 'library-inject.so').touch()
    return sls_dir


def _launcher(directory):
    launcher = Path(directory) / '.steam/steam.sh'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/usr/bin/env bash\nexec client\n# and launch steam\n')
    return launcher


def _desktop_source(directory):
    source = Path(directory) / 'source.desktop'
    source.write_text('[Desktop Entry]\nName=Steam\nExec=/usr/games/steam %U\n'
                      '[Desktop Action Store]\nExec=/usr/games/steam steam://store\n')
    return source


class SLSsteamInjectionTests(unittest.TestCase):
    def test_not_installed(self):
        with tempfile.TemporaryDirectory() as d:
            with _env(None, [], [], Path(d) / 'out.desktop'):
                status = linux_platform.slssteam_injection_status()
        self.assertFalse(status['installed'])
        self.assertFalse(status['injected'])
        self.assertEqual(status['error'], 'SLSsteam not installed')

    def test_installed_but_no_launcher_or_desktop(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir = _install_sls(d)
            with _env(sls_dir, [], [], Path(d) / 'out.desktop'):
                status = linux_platform.slssteam_injection_status()
        self.assertTrue(status['installed'])
        self.assertFalse(status['injected'])
        self.assertEqual(status['error'], 'steam.sh not found')

    def test_desktop_override_alone_counts_as_injected(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir = _install_sls(d)
            target = Path(d) / 'steam.desktop'
            target.write_text('Exec=env LD_AUDIT="/x/library-inject.so:/x/SLSsteam.so" /steam\n')
            with _env(sls_dir, [], [], target):
                status = linux_platform.slssteam_injection_status()
        self.assertTrue(status['injected'])
        self.assertFalse(status['launcher'])
        self.assertTrue(status['desktop'])

    def test_repair_injects_launcher_and_desktop_then_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir = _install_sls(d)
            launcher = _launcher(d)
            source = _desktop_source(d)
            target = Path(d) / 'applications/steam.desktop'
            with _env(sls_dir, [launcher], [source], target):
                first = linux_platform.verify_slssteam_injected()
                launcher_content = launcher.read_text()
                desktop_content = target.read_text()
                second = linux_platform.verify_slssteam_injected()
                status = linux_platform.slssteam_injection_status()
        self.assertTrue(first['patched'])
        self.assertFalse(first['already_ok'])
        self.assertIn('LD_AUDIT', launcher_content)
        self.assertLess(launcher_content.index('SLSsteam injection'),
                        launcher_content.index('# and launch steam'))
        self.assertEqual(launcher_content.count('LD_AUDIT'), 1)
        self.assertEqual(desktop_content.count('LD_AUDIT'), 2)
        self.assertIn('Exec=env LD_AUDIT=', desktop_content)
        self.assertFalse(second['patched'])
        self.assertTrue(second['already_ok'])
        self.assertTrue(status['injected'])

    def test_repair_does_not_duplicate_existing_export(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir = _install_sls(d)
            launcher = _launcher(d)
            launcher.write_text('#!/usr/bin/env bash\n'
                                'export LD_AUDIT="/old/library.so:/old/SLSsteam.so"\n'
                                '# and launch steam\n')
            source = _desktop_source(d)
            target = Path(d) / 'out.desktop'
            with _env(sls_dir, [launcher], [source], target):
                result = linux_platform.verify_slssteam_injected()
                content = launcher.read_text()
        self.assertTrue(result['already_ok'])
        self.assertEqual(content.count('LD_AUDIT'), 1)

    def test_unsupported_launcher_reports_error(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir = _install_sls(d)
            launcher = Path(d) / 'steam.sh'
            launcher.write_text('#!/bin/sh\necho no anchors here\n')
            with _env(sls_dir, [launcher], [], Path(d) / 'out.desktop'):
                result = linux_platform.verify_slssteam_injected()
        self.assertIn('unsupported launcher layout', result['error'])


if __name__ == '__main__':
    unittest.main()
