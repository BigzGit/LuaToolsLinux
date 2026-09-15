#!/usr/bin/env python3
"""HTTP bridge that emulates Millennium.callServerMethod for LuaTools UI."""

from __future__ import annotations

import argparse
import json
import hmac
import inspect
from bridge_auth import get_bridge_token
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

import main as luatools_main


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    origin = handler.headers.get('Origin')
    if origin in TRUSTED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS, GET")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-LuaTools-Token")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


TRUSTED_ORIGINS = frozenset({
    'https://steamloopback.host', 'https://store.steampowered.com',
    'https://steamcommunity.com', 'null',
})
MAX_REQUEST_BYTES = 1024 * 1024

# Explicit allowlist of the methods the LuaTools frontend is known to call.
# Adding a new public function to main.py does NOT expose it automatically.
RPC_ALLOWED_METHODS = frozenset({
    'ApplyGameFix', 'ApplyLinuxNativeFix', 'ApplySettingsChanges',
    'BrowseForLauncher', 'CancelAddViaLuaTools', 'CancelApplyFix',
    'CancelWorkshopDownload', 'CheckFakeAppIdStatus', 'CheckForFixes',
    'CheckForUpdatesNow', 'CheckGameDLCsStatus', 'CheckGameTokenStatus',
    'CheckGameUpdate', 'DeleteLuaToolsForApp', 'DismissLoadedApps',
    'FetchFreeApisNow', 'GetAddViaLuaToolsStatus', 'GetApplyFixStatus',
    'GetGameInstallPath', 'GetGamesDatabase', 'GetIconDataUrl',
    'GetInitApisMessage', 'GetInstalledFixes', 'GetInstalledLuaScripts',
    'GetLauncherPath', 'GetPluginDir', 'GetProtonDBStatus', 'GetSettingsConfig',
    'GetSLSPlayStatus', 'GetThemes', 'GetTranslations', 'GetUnfixStatus',
    'GetWorkshopDownloadStatus', 'GetWorkshopToolPath', 'HasLuaToolsForApp',
    'InstallDependencies', 'Logger.error', 'Logger.log', 'Logger.warn',
    'OpenExternalUrl', 'OpenGameFolder', 'ReadLoadedApps', 'RestartSteam',
    'SaveLauncherPath', 'SaveRyuuCookie', 'SaveWorkshopToolPath',
    'SetSLSPlayStatus', 'StartAddViaLuaTools', 'StartWorkshopDownloadParams',
    'UnFixGame', 'UninstallGameFull', 'UpdateMorrenusKey',
})


def _resolve_rpc_method(name: str):
    if name.startswith('Logger.'):
        attr = name.split('.', 1)[1]
        logger_cls = getattr(luatools_main, 'Logger', None)
        if logger_cls is None or attr not in ('log', 'warn', 'error'):
            return None
        return getattr(logger_cls, attr)
    value = getattr(luatools_main, name, None)
    if value is None or not inspect.isfunction(value) or value.__module__ != luatools_main.__name__:
        return None
    return value


RPC_METHODS = {}
for _name in RPC_ALLOWED_METHODS:
    _resolved = _resolve_rpc_method(_name)
    if _resolved is not None:
        RPC_METHODS[_name] = _resolved
del _name, _resolved



def _call_backend(method_name: str, args: Dict[str, Any]) -> Any:
    if not isinstance(method_name, str) or method_name not in RPC_METHODS:
        raise ValueError('Unknown method')
    if not isinstance(args, dict):
        raise ValueError('args must be a JSON object')
    return RPC_METHODS[method_name](**args)


class _BridgeHandler(BaseHTTPRequestHandler):
    server_version = "LuaToolsBridge/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def _check_request(self, authenticate=True):
        port = self.server.server_address[1]
        if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}:
            _json_response(self, 403, {'success': False, 'error': 'Invalid Host'})
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin not in TRUSTED_ORIGINS:
            _json_response(self, 403, {'success': False, 'error': 'Invalid Origin'})
            return False
        if authenticate and not hmac.compare_digest(
            self.headers.get('X-LuaTools-Token', '').encode('utf-8'), self.server.auth_token.encode('ascii')
        ):
            _json_response(self, 403, {'success': False, 'error': 'Authentication required'})
            return False
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        if self._check_request(authenticate=False):
            _json_response(self, 200, {"success": True})

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_request(authenticate=False):
            return
        if self.path == "/health":
            _json_response(self, 200, {"success": True, "service": "luatools-bridge"})
            return
        _json_response(self, 404, {"success": False, "error": "Not Found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_request():
            return
        if self.path != "/rpc":
            _json_response(self, 404, {"success": False, "error": "Not Found"})
            return

        try:
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise ValueError('Expected JSON with Content-Length')
            if len(self.headers.get_all('Content-Length', [])) != 1:
                raise ValueError('Expected one Content-Length')
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                _json_response(self, 413, {'success': False, 'error': 'Invalid request size'})
                return
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError('Expected JSON object')
            method = body.get("method", "")
            args = body.get("args", {})

            if not method:
                _json_response(self, 400, {"success": False, "error": "Missing method"})
                return

            result = _call_backend(method, args)
            _json_response(self, 200, {"success": True, "result": result})
        except (ValueError, TypeError, UnicodeError):
            _json_response(self, 400, {"success": False, "error": "Invalid RPC request"})
        except Exception:
            _json_response(self, 500, {"success": False, "error": "Backend request failed"})

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="LuaTools web bridge server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=38495)
    args = parser.parse_args()
    if args.host == 'localhost':
        args.host = '127.0.0.1'
    if args.host != '127.0.0.1':
        parser.error('The bridge must bind to 127.0.0.1')

    # Best-effort startup parity with plugin mode.
    try:
        luatools_main.detect_steam_install_path()
    except Exception:
        pass
    try:
        luatools_main.ensure_http_client("BridgeInit")
    except Exception:
        pass
    try:
        luatools_main.ensure_temp_download_dir()
    except Exception:
        pass
    try:
        luatools_main.init_applist()
    except Exception:
        pass
    try:
        luatools_main.init_games_db()
    except Exception:
        pass
    try:
        luatools_main.InitApis("bridge-init")
    except Exception:
        pass

    httpd = ThreadingHTTPServer((args.host, args.port), _BridgeHandler)
    httpd.auth_token = get_bridge_token()
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
