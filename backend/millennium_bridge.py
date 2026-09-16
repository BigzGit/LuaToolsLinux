#!/usr/bin/env python3
"""Register the Python bridge UI as a frontend-only Millennium 3 plugin."""
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess

from bridge_auth import get_bridge_token


def repair_millennium_loader(home=None, library="/usr/lib/millennium/libmillennium_bootstrap_x86.so"):
    """Support split Debian client/data directories without moving user data."""
    home = Path(home) if home is not None else Path.home()
    if not Path(library).is_file():
        return False
    candidates = [home / ".steam/root", home / ".steam", home / ".steam/steam",
                  home / ".local/share/Steam"]
    client = next((p.resolve() for p in candidates
                   if (p / "ubuntu12_32/steam").is_file() and (p / "steam.sh").is_file()), None)
    if client is None:
        raise RuntimeError("Steam client executable not found; start Steam once before installing")
    expected = home / ".steam/steam/ubuntu12_32/steam"
    actual = client / "ubuntu12_32/steam"
    if expected.exists():
        if not expected.samefile(actual):
            raise RuntimeError("Multiple Steam executables found; refusing to overwrite either installation")
    else:
        if expected.is_symlink():
            raise RuntimeError("Broken Steam executable link; refusing to overwrite it")
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.symlink_to(actual)
    hook = client / "ubuntu12_32/libXtst.so.6"
    if hook.is_symlink() and hook.resolve() == Path(library).resolve():
        return True
    if hook.exists() or hook.is_symlink():
        raise RuntimeError("Existing libXtst hook differs; refusing to overwrite it")
    hook.symlink_to(library)
    return True


def configure_service(runtime_root, python_bin=sys.executable):
    """Keep the bridge alive independently of installer terminals and Steam."""
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    units = config / "systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    def quote(value):
        return json.dumps(str(value)).replace("%", "%%").replace("$", "$$")
    command = " ".join(quote(value) for value in (
        python_bin, "-u", Path(runtime_root).resolve() / "backend/web_bridge_server.py"))
    (units / "luatools-bridge.service").write_text(
        "[Unit]\nDescription=LuaTools local Python bridge\n"
        "[Service]\nType=simple\nExecStart=" + command + "\n"
        "Restart=always\nRestartSec=2\nUMask=0077\n"
        "[Install]\nWantedBy=default.target\n")
    autostart = config / "autostart/luatools.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text("[Desktop Entry]\nType=Application\nName=LuaTools bridge\n"
                         "Exec=systemctl --user start luatools-bridge.service\nTerminal=false\n")


def configure(runtime_root, python_bin=sys.executable):
    root = Path(runtime_root).resolve()
    repair_millennium_loader()
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    plugin = data / "millennium/plugins/luatools"
    dist = plugin / ".millennium/Dist"
    dist.mkdir(parents=True, exist_ok=True)
    script = (root / "public/luatools.js").read_text().replace(
        "__LUATOOLS_BRIDGE_TOKEN__", get_bridge_token(root))
    # Millennium loads webkit.js in Store/Community views, not steamui/index.html.
    webkit = dist / "webkit.js"
    webkit.write_text(script)
    webkit.chmod(0o600)
    (dist / "index.js").write_text("export default function() {}\n")
    manifest = plugin / "plugin.json"
    metadata = json.loads(manifest.read_text()) if manifest.exists() else {
        "name": "luatools", "common_name": "LuaToolsLinux", "version": "1.0",
        "description": "LuaTools interface with a local Python bridge"}
    metadata["useBackend"] = False
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    settings = config / "millennium/config.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    values = json.loads(settings.read_text()) if settings.exists() else {}
    enabled = values.setdefault("plugins", {}).setdefault("enabledPlugins", [])
    if "luatools" not in enabled:
        enabled.append("luatools")
    settings.write_text(json.dumps(values, indent=2) + "\n")
    autostart = config / "autostart/luatools.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    def quote(arg):
        value = str(arg)
        for char in ("\\", '"', "`", "$"):
            value = value.replace(char, "\\" + char)
        return '"' + value.replace("%", "%%") + '"'
    command = " ".join(quote(arg) for arg in (
        python_bin, root / "backend/web_bridge_server.py"))
    autostart.write_text("[Desktop Entry]\nType=Application\nName=LuaTools bridge\nExec=" + command + "\nTerminal=false\n")
    if shutil.which("systemctl"):
        configure_service(root, python_bin)
    return plugin


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    print("Millennium LuaTools integration configured:", configure(root))

    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "luatools-bridge.service"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "luatools-bridge.service"], check=True)
