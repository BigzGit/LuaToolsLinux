"""Local integration regressions. Network, processes and Steam paths are mocked."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from email.message import Message

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import main
import fixes
import steam_utils
import auto_update
import web_bridge_server as bridge
import ui_injector
from bridge_auth import get_bridge_token
from logger import redact_message


class BackendSecurityTests(unittest.TestCase):
    def test_rpc_surface(self):
        for name in ('get_plugin_dir', 'save_workshop_tool_path', 'ensure_temp_download_dir', 'Plugin', '__import__'):
            with self.assertRaises(ValueError): bridge._call_backend(name, {})
        self.assertIn('StartWorkshopDownloadParams', bridge.RPC_METHODS)
        self.assertIn('Logger.log', bridge.RPC_METHODS)
        self.assertIn('GetSLSsteamStatus', bridge.RPC_METHODS)
        self.assertIn('RepairSLSsteamInjection', bridge.RPC_METHODS)
        self.assertEqual(bridge._call_backend('GetPluginDir', {}), main.get_plugin_dir())

    def request(self, body, token='t'*64, origin='https://steamloopback.host', host='127.0.0.1:38495', length=None, content_type='application/json'):
        handler = object.__new__(bridge._BridgeHandler)
        handler.headers = Message()
        for key, val in {'Host':host,'Origin':origin,'X-LuaTools-Token':token,'Content-Type':content_type,'Content-Length':str(len(body) if length is None else length)}.items():
            handler.headers[key] = val
        handler.path='/rpc'; handler.rfile=io.BytesIO(body)
        handler.server=SimpleNamespace(server_address=('127.0.0.1',38495),auth_token='t'*64)
        with patch.object(bridge, '_json_response') as response:
            handler.do_POST()
            return response.call_args.args[1:]

    def test_http_boundary(self):
        body=json.dumps({'method':'GetPluginDir','args':{}}).encode()
        self.assertEqual(self.request(body)[0],200)
        for kwargs in ({'token':''},{'origin':'https://evil.test'},{'host':'evil.test:38495'},{'origin':'https://steamloopback.host.evil.test'}):
            self.assertEqual(self.request(body,**kwargs)[0],403)
        self.assertEqual(self.request(body,length=2**30)[0],413)
        for value in (b'[]',b'null',b'{',b'{"method":"GetPluginDir","args":[]}'):
            self.assertEqual(self.request(value)[0],400)
        self.assertEqual(self.request(body,content_type='text/plain')[0],400)

    def test_health_endpoint_and_origin_policy(self):
        handler=object.__new__(bridge._BridgeHandler)
        handler.headers=Message()
        handler.headers['Host']='127.0.0.1:38495'
        handler.path='/health'
        handler.server=SimpleNamespace(server_address=('127.0.0.1',38495),auth_token='t'*64)
        with patch.object(bridge,'_json_response') as response:
            handler.do_GET()
            self.assertEqual(response.call_args.args[1],200)
        handler.headers['Origin']='https://evil.test'
        with patch.object(bridge,'_json_response') as response:
            handler.do_GET()
            self.assertEqual(response.call_args.args[1],403)

    def test_appid_rejected_before_side_effects(self):
        with patch.object(main.os.path,'expanduser',side_effect=AssertionError('must not access config')):
            for func in (main.AddFakeAppId,main.AddGameToken,main.RemoveGameDLCs,main.UninstallGameFull):
                self.assertFalse(json.loads(func('1\nInjected: yes'))['success'])
        self.assertFalse(json.loads(main.StartWorkshopDownloadParams(480,'../../outside'))['success'])

    def test_fakeappid_atomic_and_dlc_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            config=Path(d,'config.yaml'); config.write_text('# keep comment\nDlcData:\n')
            trap=Path(d,'outside');trap.write_text('safe')
            Path(str(config)+'.tmp').symlink_to(trap)
            with patch.object(main.os.path,'expanduser',return_value=str(config)), \
                 patch.object(main,'check_slssteam_installed',return_value=True), \
                 patch.object(main,'slssteam_injection_status',return_value={'installed':True,'injected':True,'error':None,'launchers':[]}):
                self.assertTrue(json.loads(main.AddFakeAppId('480'))['success'])
                with patch.object(main,'_fetch_dlc_list',return_value=[(123,'A "name"\nInjected: yes\\')]):
                    self.assertTrue(json.loads(main.AddGameDLCs(481))['success'])
            from ruamel.yaml import YAML
            data=YAML(typ='safe').load(config.read_text())
            self.assertEqual(data['DlcData'][481][123],'A "name"\nInjected: yes\\')
            self.assertEqual(data['FakeAppIds'][480],480)
            self.assertEqual(trap.read_text(),'safe')
            self.assertIn('# keep comment',config.read_text())

    def test_unfix_malicious_and_legacy_logs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d,'game');root.mkdir(); outside=Path(d,'outside');outside.write_text('keep')
            log=root/'luatools-fix-log-480.log'
            log.write_text('Files:\n../outside\n')
            fixes._unfix_game_worker(480,str(root))
            self.assertEqual(fixes._get_unfix_state(480)['status'],'failed')
            self.assertEqual(outside.read_text(),'keep')
            (root/'fix.dll').write_text('fix');log.write_text('Files:\nfix.dll\n')
            fixes._unfix_game_worker(480,str(root))
            self.assertEqual(fixes._get_unfix_state(480)['status'],'done')
            self.assertFalse((root/'fix.dll').exists())

    def test_restart_passes_path_as_argument(self):
        hostile='/tmp/user;echo INJECTED/steam.sh'
        with patch.object(auto_update.shutil,'which',return_value=None), patch.object(auto_update.os.path,'expanduser',return_value=hostile), patch.object(auto_update.os.path,'exists',return_value=True), patch.object(auto_update.subprocess,'Popen') as popen:
            self.assertTrue(auto_update.restart_steam_internal())
            args=popen.call_args.args[0]
            self.assertNotIn(hostile,args[2])
            self.assertEqual(args[-1],hostile)

    def test_ui_token_provisioning(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'public').mkdir()
            script=root/'public/luatools.js';script.write_text('const token="__LUATOOLS_BRIDGE_TOKEN__";')
            tag=ui_injector._build_inline_script_tag(str(script))
            token=get_bridge_token(d)
            self.assertIn(token,tag)
            self.assertNotIn('__LUATOOLS_BRIDGE_TOKEN__',tag)
            self.assertEqual(token,get_bridge_token(d))
            index=root/'index.html';index.write_text('<body></body>');index.chmod(0o644)
            self.assertTrue(ui_injector._inject_index(str(index),tag))
            self.assertEqual(index.stat().st_mode & 0o777,0o600)
            self.assertEqual((root/'backend/data/bridge_token').stat().st_mode & 0o777,0o600)

    def test_accela_argument_array_and_lua_manifest_processing(self):
        import downloads
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); launcher=root/'ACCELA $literal; name.AppImage';launcher.write_text('fixture')
            archive=root/'480.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('480\\480.lua','setManifestid(1, 2)\naddappid(480)\n')
                z.writestr('480\\123.manifest',b'manifest')
            process=Mock(returncode=0);process.communicate.return_value=('','')
            with patch.object(downloads,'detect_steam_install_path',return_value=d), patch.object(downloads,'load_launcher_path',return_value=str(launcher)), patch.object(downloads.subprocess,'Popen',return_value=process) as popen:
                downloads._process_and_install_lua(480,str(archive))
            self.assertEqual(popen.call_args.args[0],[str(launcher),str(archive)])
            self.assertNotIn('LD_PRELOAD',popen.call_args.kwargs['env'])
            self.assertEqual((root/'depotcache/123.manifest').read_bytes(),b'manifest')
            self.assertEqual((root/'config/stplug-in/480.lua').read_text(),'--setManifestid(1, 2)\naddappid(480)\n')

    def test_launcher_discovery_and_custom_path(self):
        import downloads
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'HOME':d}):
            root=Path(d);accela=root/'.local/share/ACCELA';accela.mkdir(parents=True)
            launcher=accela/'run.sh';launcher.write_text('fixture');launcher.chmod(0o755)
            config=root/'launcher_path.txt'
            with patch.object(downloads,'_get_launcher_path_file',return_value=str(config)):
                self.assertEqual(downloads.load_launcher_path(),str(launcher))
                custom=root/'custom launcher.AppImage';custom.write_text('fixture')
                self.assertTrue(json.loads(downloads.save_launcher_path_config(str(custom)))['success'])
                self.assertEqual(downloads.load_launcher_path(),str(custom))

    def test_update_integrity_and_atomic_download(self):
        import hashlib
        import zipfile
        import httpx
        payload=io.BytesIO()
        with zipfile.ZipFile(payload,'w') as z:z.writestr('public/test.txt','ok')
        data=payload.getvalue()
        client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=data)))
        with tempfile.TemporaryDirectory() as d, patch.object(auto_update,'ensure_http_client',return_value=client):
            dest=Path(d,'pending.zip')
            self.assertFalse(auto_update._download_and_extract_update('https://example.test/update',str(dest),'0'*64))
            self.assertFalse(dest.exists())
            self.assertTrue(auto_update._download_and_extract_update('https://example.test/update',str(dest),hashlib.sha256(data).hexdigest()))
            self.assertEqual(dest.read_bytes(),data)
        client.close()

    def test_tls_redirect_rejection(self):
        import httpx
        from http_client import _reject_tls_downgrade
        seen=[]
        def respond(request):
            seen.append(request)
            if len(seen)==1:return httpx.Response(302,headers={'Location':'http://example.test/end'})
            return httpx.Response(200)
        with httpx.Client(transport=httpx.MockTransport(respond),event_hooks={'response':[_reject_tls_downgrade]}) as client:
            with self.assertRaises(ValueError):client.get('https://example.test/',follow_redirects=True)
        self.assertEqual(len(seen),1)

    def test_manifest_traversal_and_custom_library(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();(root/'steamapps/common/Game Name').mkdir(parents=True)
            (root/'config/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" "'+d+'" "apps" { "480" "1" } } }')
            manifest=root/'steamapps/appmanifest_480.acf'
            with patch.object(steam_utils,'_find_steam_path',return_value=d):
                manifest.write_text('"AppState" { "installdir" "Game Name" }')
                self.assertTrue(steam_utils.get_game_install_path_response(480)['success'])
                for value in ('../../..',d,'../outside'):
                    manifest.write_text('"AppState" { "installdir" "'+value+'" }')
                    self.assertFalse(steam_utils.get_game_install_path_response(480)['success'])

    def test_redaction(self):
        value=redact_message('GET https://user:password@example.test/path?api_key=SECRET session=COOKIE')
        for secret in ('password','SECRET','COOKIE'):self.assertNotIn(secret,value)
        self.assertIn('example.test/path',value)

    def test_api_manifest_skips_plaintext_providers(self):
        import api_manifest
        with tempfile.TemporaryDirectory() as d:
            path=Path(d,'api.json')
            path.write_text(json.dumps({'api_list':[
                {'name':'plain','url':'http://167.235.229.108/<appid>','enabled':True},
                {'name':'secure','url':'https://files.luatools.work/<appid>.zip','enabled':True},
                {'name':'disabled','url':'https://x.test/<appid>','enabled':False},
            ]}))
            with patch.object(api_manifest,'backend_path',return_value=str(path)):
                names=[api['name'] for api in api_manifest.load_api_manifest()]
        self.assertEqual(names,['secure'])

    def test_morrenus_key_is_separated_from_api_json(self):
        import downloads
        with tempfile.TemporaryDirectory() as d:
            api=Path(d,'api.json')
            api.write_text(json.dumps({'api_list':[{'name':'Morrenus','url':'https://manifest.morrenus.xyz/api/v1/manifest/<appid>?api_key=LEGACYKEY','enabled':True}]}))
            key_path=Path(d,'data/morrenus_key.txt')
            with patch.object(downloads,'_get_api_json_path',return_value=str(api)), \
                 patch.object(downloads,'_get_morrenus_key_path',return_value=str(key_path)):
                self.assertEqual(downloads.load_morrenus_key(),'LEGACYKEY')
                self.assertNotIn('LEGACYKEY',api.read_text())
                self.assertIn(downloads.MORRENUS_KEY_PLACEHOLDER,api.read_text())
                self.assertEqual(key_path.read_text(),'LEGACYKEY')
                self.assertEqual(key_path.stat().st_mode & 0o777,0o600)
                self.assertEqual(key_path.parent.stat().st_mode & 0o777,0o700)
                # Idempotent: a second read keeps working and does not corrupt state.
                self.assertEqual(downloads.load_morrenus_key(),'LEGACYKEY')

    def test_apply_game_fix_rejects_insecure_urls_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            library=Path(d); game=library/'steamapps/common/Game'; game.mkdir(parents=True)
            outside=library/'outside'; outside.mkdir()
            self.assertFalse(json.loads(fixes.apply_game_fix(480,'http://evil.test/x.zip',str(game)))['success'])
            self.assertFalse(json.loads(fixes.apply_game_fix(480,'file:///etc/passwd',str(game)))['success'])
            self.assertFalse(json.loads(fixes.apply_game_fix(480,'https://127.0.0.1/x.zip',str(game)))['success'])
            with patch.object(fixes,'get_steam_library_paths',return_value=[str(library)]):
                self.assertFalse(json.loads(fixes.apply_game_fix(480,'https://evil.test/x.zip',str(outside)))['success'])
                self.assertFalse(json.loads(fixes.apply_game_fix(480,'https://evil.test/x.zip',str(library)))['success'])


if __name__=='__main__': unittest.main()
