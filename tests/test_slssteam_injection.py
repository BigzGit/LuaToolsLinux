"""SLSsteam installation/injection detection and launcher patching."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import linux_platform


class SLSsteamInjectionTests(unittest.TestCase):
    def _setup(self, directory):
        home = Path(directory)
        sls_dir = home / '.local/share/SLSsteam'
        sls_dir.mkdir(parents=True)
        (sls_dir / 'SLSsteam.so').touch()
        (sls_dir / 'library-inject.so').touch()
        launcher = home / '.steam/steam.sh'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/usr/bin/env bash\nexec client\n# and launch steam\n')
        return sls_dir, launcher

    def test_not_installed(self):
        with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES', []), \
             patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES', []):
            status = linux_platform.slssteam_injection_status()
        self.assertFalse(status['installed'])
        self.assertFalse(status['injected'])
        self.assertEqual(status['error'], 'SLSsteam not installed')

    def test_installed_but_launcher_missing(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir, _ = self._setup(d)
            with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES', [str(sls_dir)]), \
                 patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES', [str(Path(d) / 'nope.sh')]):
                status = linux_platform.slssteam_injection_status()
        self.assertTrue(status['installed'])
        self.assertFalse(status['injected'])
        self.assertEqual(status['error'], 'steam.sh not found')

    def test_detects_existing_injection(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir, launcher = self._setup(d)
            launcher.write_text('#!/usr/bin/env bash\nexport LD_AUDIT="/x/library-inject.so:/x/SLSsteam.so"\n')
            with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES', [str(sls_dir)]), \
                 patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES', [str(launcher)]):
                status = linux_platform.slssteam_injection_status()
        self.assertTrue(status['injected'])

    def test_repair_injects_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir, launcher = self._setup(d)
            with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES', [str(sls_dir)]), \
                 patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES', [str(launcher)]):
                first = linux_platform.verify_slssteam_injected()
                patched_content = launcher.read_text()
                second = linux_platform.verify_slssteam_injected()
                status = linux_platform.slssteam_injection_status()
        self.assertTrue(first['patched'])
        self.assertFalse(first['already_ok'])
        self.assertIn('LD_AUDIT', patched_content)
        self.assertIn(str(sls_dir), patched_content)
        self.assertEqual(patched_content.count('LD_AUDIT'), 1)
        # The export is inserted before the launch line, not at the top.
        self.assertLess(patched_content.index('SLSsteam injection'),
                        patched_content.index('# and launch steam'))
        self.assertFalse(second['patched'])
        self.assertTrue(second['already_ok'])
        self.assertTrue(status['injected'])

    def test_repair_does_not_duplicate_existing_export(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir, launcher = self._setup(d)
            launcher.write_text('#!/usr/bin/env bash\nexport LD_AUDIT="/old/library.so:/old/SLSsteam.so"\n# and launch steam\n')
            with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES', [str(sls_dir)]), \
                 patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES', [str(launcher)]):
                result = linux_platform.verify_slssteam_injected()
                content = launcher.read_text()
        self.assertTrue(result['already_ok'])
        self.assertFalse(result['patched'])
        self.assertEqual(content.count('LD_AUDIT'), 1)

    def test_unsupported_launcher_reports_error(self):
        with tempfile.TemporaryDirectory() as d:
            sls_dir = Path(d) / '.local/share/SLSsteam'
            sls_dir.mkdir(parents=True)
            (sls_dir / 'SLSsteam.so').touch()
            launcher = Path(d) / 'steam.sh'
            launcher.write_text('#!/bin/sh\necho no anchors here\n')
            with patch.object(linux_platform, '_SLSSTEAM_CANDIDATES', [str(sls_dir)]), \
                 patch.object(linux_platform, '_STEAM_LAUNCHER_CANDIDATES', [str(launcher)]):
                result = linux_platform.verify_slssteam_injected()
        self.assertFalse(result['patched'])
        self.assertIn('unsupported launcher layout', result['error'])


if __name__ == '__main__':
    unittest.main()
