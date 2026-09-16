import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from millennium_bridge import repair_millennium_loader, configure_service


class MillenniumBridgeTests(unittest.TestCase):
    def test_split_steam_layout_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            client = home / '.steam'
            (client / 'ubuntu12_32').mkdir(parents=True)
            (client / 'steam.sh').touch()
            (client / 'ubuntu12_32/steam').touch()
            library = home / 'bootstrap.so'
            library.touch()
            for _ in range(2):
                self.assertTrue(repair_millennium_loader(home, str(library)))
            self.assertTrue((client / 'steam/ubuntu12_32/steam').samefile(client / 'ubuntu12_32/steam'))
            self.assertTrue((client / 'ubuntu12_32/libXtst.so.6').samefile(library))

    def test_existing_hook_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            client = home / '.steam'
            (client / 'ubuntu12_32').mkdir(parents=True)
            (client / 'steam.sh').touch()
            (client / 'ubuntu12_32/steam').touch()
            hook = client / 'ubuntu12_32/libXtst.so.6'
            hook.write_text('existing library')
            library = home / 'bootstrap.so'
            library.touch()
            with self.assertRaises(RuntimeError):
                repair_millennium_loader(home, str(library))
            self.assertEqual(hook.read_text(), 'existing library')

    def test_service_uses_selected_python_and_supervised_autostart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            with patch.dict(os.environ, XDG_CONFIG_HOME=directory):
                configure_service(config / 'runtime', '/custom/python')
            unit = (config / 'systemd/user/luatools-bridge.service').read_text()
            self.assertIn('ExecStart="/custom/python" "-u"', unit)
            self.assertIn('Restart=always', unit)
            self.assertIn('systemctl --user start luatools-bridge.service',
                          (config / 'autostart/luatools.desktop').read_text())
