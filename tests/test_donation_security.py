import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import donate_keys
import auto_update
from settings import manager
from settings.options import get_default_settings_values


class DonationSecurityTests(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertIs(get_default_settings_values()['general']['donateKeys'], False)

    def test_legacy_true_requires_new_consent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, 'settings.json')
            path.write_text(json.dumps({'version': 1, 'values': {'general': {'donateKeys': True, 'theme': 'dark'}}}))
            with patch.object(manager, 'SETTINGS_FILE', str(path)), patch.object(manager, '_SETTINGS_CACHE', None):
                values = manager._load_settings_cache()
                self.assertIs(values['general']['donateKeys'], False)
                self.assertEqual(values['general']['theme'], 'dark')
                self.assertEqual(json.loads(path.read_text())['version'], 2)
                path.write_text(json.dumps({'version': 2, 'values': {'general': {'donateKeys': True}}}))
                manager._SETTINGS_CACHE = None
                self.assertIs(manager._load_settings_cache()['general']['donateKeys'], True)

    def test_opt_in_requires_a_configured_recipient(self):
        option = manager._OPTION_LOOKUP[('general', 'donateKeys')]
        with patch.dict(os.environ, {'LUATOOLS_DONATION_URL': ''}):
            self.assertFalse(manager._validate_option_value(option, True)[0])
        with patch.dict(os.environ, {'LUATOOLS_DONATION_URL': 'https://example.test/donate'}):
            self.assertEqual(manager._validate_option_value(option, True), (True, True, None))

    def test_no_extraction_without_consent_and_https(self):
        for enabled, url in [(False, 'https://example.test/donate'), (True, ''), (True, 'http://example.test/donate'), ('false', 'https://example.test/donate')]:
            with self.subTest(enabled=enabled,url=url), patch.dict(os.environ, {'LUATOOLS_DONATION_URL': url}), patch.object(manager, 'get_settings_state', return_value={'values': {'general': {'donateKeys': enabled}}}), patch.object(auto_update, 'detect_steam_install_path', return_value='/unused/steam'), patch.object(donate_keys, 'extract_valid_decryption_keys') as extract:
                auto_update._check_and_donate_keys()
                extract.assert_not_called()

    def test_sender_enforces_policy_even_when_called_directly(self):
        pairs = [('480', 'a' * 64)]
        for enabled,url in [(False,'https://example.test/donate'),(True,''),(True,'http://example.test/donate'),(True,'https://user:password@example.test/donate')]:
            with self.subTest(enabled=enabled,url=url), patch.dict(os.environ, {'LUATOOLS_DONATION_URL':url}), patch.object(manager,'get_settings_state',return_value={'values':{'general':{'donateKeys':enabled}}}), patch.object(donate_keys,'get_http_client') as client:
                self.assertFalse(donate_keys.send_donation_keys(pairs))
                client.assert_not_called()

    def test_explicit_https_donation_keeps_payload_and_disallows_redirects(self):
        pairs=[('480','a'*64)]
        client=Mock();client.post.return_value.status_code=200
        with patch.dict(os.environ,{'LUATOOLS_DONATION_URL':'https://example.test/donate'}), patch.object(manager,'get_settings_state',return_value={'values':{'general':{'donateKeys':True}}}), patch.object(donate_keys,'get_http_client',return_value=client):
            self.assertTrue(donate_keys.send_donation_keys(pairs))
            self.assertEqual(client.post.call_args.kwargs['content'],'480:'+ 'a'*64)
            self.assertIs(client.post.call_args.kwargs['follow_redirects'],False)
            client.post.return_value.status_code=302
            self.assertFalse(donate_keys.send_donation_keys(pairs))
            client.post.side_effect=RuntimeError('sensitive server error')
            self.assertFalse(donate_keys.send_donation_keys(pairs))


if __name__=='__main__':unittest.main()
