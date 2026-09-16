import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from security import (
    atomic_write_text,
    validate_id,
    rooted_path,
    extract_zip,
    normalize_download_zip,
    trusted_ryuu_url,
    validate_remote_url,
    is_allowed_game_install_path,
)


class SecurityTests(unittest.TestCase):
    def test_ids(self):
        for value in (480, '480', ' 480 '):
            self.assertEqual(validate_id(value), 480)
        for value in ('../480', '/tmp/x', '1\nFakeAppIds:', True, 1.5, -1, 0, '١'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_id(value)

    def test_cookie_scope(self):
        self.assertTrue(trusted_ryuu_url('https://generator.ryuu.lol/path'))
        for url in ('http://generator.ryuu.lol/', 'https://ryuu.lol.evil.test/', 'https://evil.test/ryuu.lol', 'https://ryuu.lol@evil.test/'):
            self.assertFalse(trusted_ryuu_url(url))

    def test_remote_url_validation(self):
        self.assertEqual(
            validate_remote_url('https://files.luatools.work/fix.zip'),
            'https://files.luatools.work/fix.zip',
        )
        for url in (
            'http://files.luatools.work/fix.zip',
            'file:///etc/passwd',
            'ftp://example.test/fix.zip',
            'https://127.0.0.1/fix.zip',
            'https://localhost/fix.zip',
            'https://169.254.1.1/fix.zip',
            'https://10.0.0.1/fix.zip',
            'https://user:pass@example.test/fix.zip',
            'https:///nohost',
            '',
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_remote_url(url)
        self.assertTrue(validate_remote_url(
            'https://cdn.example.test/fix.zip', allowed_hosts=['cdn.example.test']))
        with self.assertRaises(ValueError):
            validate_remote_url('https://other.test/fix.zip', allowed_hosts=['cdn.example.test'])

    def test_allowed_game_install_path(self):
        with tempfile.TemporaryDirectory() as d:
            library = Path(d, 'library')
            game = library / 'steamapps/common/Game'
            game.mkdir(parents=True)
            outside = Path(d, 'outside'); outside.mkdir()
            self.assertTrue(is_allowed_game_install_path(str(game), [str(library)]))
            self.assertFalse(is_allowed_game_install_path(str(outside), [str(library)]))
            self.assertFalse(is_allowed_game_install_path(str(library), [str(library)]))
            self.assertFalse(is_allowed_game_install_path(str(library / 'steamapps/common/../evil'), [str(library)]))
            self.assertFalse(is_allowed_game_install_path(None, [str(library)]))

    def test_legacy_key_is_not_shipped(self):
        import json
        backend = Path(__file__).resolve().parents[1] / 'backend'
        for name in ('keys.json', 'keys.example.json'):
            path = backend / name
            if path.exists():
                self.assertEqual(json.loads(path.read_text()).get('morrenus_key', ''), '')

    def test_atomic_write_does_not_follow_leaf_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            outside = Path(d, 'outside'); outside.write_text('safe')
            target = Path(d, 'config'); target.symlink_to(outside)
            atomic_write_text(str(target), 'new')
            self.assertEqual(outside.read_text(), 'safe')
            self.assertEqual(target.read_text(), 'new')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_archive_paths_and_prevalidation(self):
        for name in ('../outside', '/outside', '480/../../outside', 'C:/outside', 'a\\..\\outside'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as z:
                    z.writestr('good.txt', 'ok'); z.writestr(name, 'bad')
                buf.seek(0)
                with zipfile.ZipFile(buf) as z, self.assertRaises(ValueError):
                    extract_zip(z, d)
                self.assertFalse(Path(d, 'good.txt').exists())

    def test_windows_zip_names_are_normalized_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, 'input.zip')
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('480\\480.lua', 'fixture')
                z.writestr('480\\123.manifest', b'manifest')
            normalize_download_zip(path)
            with zipfile.ZipFile(path) as z:
                self.assertEqual(z.namelist(), ['480/480.lua', '480/123.manifest'])
                self.assertEqual(z.read('480/480.lua'), b'fixture')
            normalized = path.read_bytes()
            normalize_download_zip(path)
            self.assertEqual(path.read_bytes(), normalized)

    def test_windows_zip_rejects_traversal_and_collisions_before_rewrite(self):
        for name in ('480\\..\\outside', '\\outside', 'C:\\outside',
                     '480/../../outside', '480/ok.lua'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                path = Path(d, 'input.zip')
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('480\\ok.lua', 'fixture')
                    z.writestr(name, 'bad')
                original = path.read_bytes()
                with self.assertRaises(ValueError):
                    normalize_download_zip(path)
                self.assertEqual(path.read_bytes(), original)

    def test_archive_regular_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d, 'root'); root.mkdir()
            outside = Path(d, 'outside'); outside.mkdir()
            (root / 'link').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): rooted_path(root, 'link/file')
            with self.assertRaises(ValueError): rooted_path(root, '../outside')
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z: z.writestr('480/sub/file.txt', 'ok')
            buf.seek(0)
            with zipfile.ZipFile(buf) as z: extract_zip(z, root, prefix='480/')
            self.assertEqual((root / 'sub/file.txt').read_text(), 'ok')


if __name__ == '__main__': unittest.main()
