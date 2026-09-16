# LuaTools (Linux)

> A Linux version of LuaTools for Steam, built for [Millennium](https://steambrew.app) with support for SLSsteam + ACCELA integration.

## One-Command Install

Install **Millennium + LuaTools + ACCELA + SLSsteam** automatically with a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/BigzGit/LuaToolsLinux/main/install.sh | bash
```

⚠️ **IMPORTANT:** Watch the video tutorial pinned in the Discord channel before configuring everything.

If ACCELA is installed as an **AppImage**, you may need to manually locate the AppImage file by clicking the folder icon in the LuaTools settings menu and selecting the path yourself.

---

# What the Installer Does

The installer now fully automates setup and troubleshooting.

## Automatic Detection & Setup

- Detects **Steam Flatpak/Snap** installs and explains how to switch to native Steam
- Detects **Decky Loader** and offers to uninstall it
- Detects whether ACCELA is:
  - `AppImage`
  - `run.sh`
- Warns when manual AppImage path selection is required
- Displays the currently installed Millennium version
- Installs required Python dependencies automatically:
  - `httpx`
  - `beautifulsoup4`
  - `ruamel.yaml`

## Expanded Fixes Menu

Built-in repair options for common issues:

- Purchase error fix
- Missing Keys fix
- No licenses info fix
- `fix-deps` runner

## Full Uninstall Support

Completely removes:

- Millennium
- LuaTools plugin
- ACCELA
- SLSsteam

## Ubuntu / Debian Improvements

Automatically checks for missing:

```bash
libssl-dev:i386
```

and offers to install it when needed.

---

# Features

- **One-click installs** through ACCELA
- **Workshop Downloader** support
- **Game Fix System**
- **Linux execute permission fixer** (`chmod +x`)
- **FakeAppId & token management**
- **Ryuu Cookie & Morrenus Key support**
- **Games database integration**
- **Theme support**
- **Automatic updates**
- **Custom launcher path configuration**

---

# Requirements

- Linux `x86_64`
- Native Steam installation
- Python `3.10+`
- Pip
- jq

## Supported Components

- [Millennium](https://steambrew.app)
- [SLSsteam](https://github.com/AceSLS/SLSsteam)
- [ACCELA / Enter The Wired](https://github.com/ciscosweater/enter-the-wired)

---

# Paths Used

| Component | Path |
|---|---|
| Steam root | `~/.steam/steam` or `~/.local/share/Steam` |
| Lua scripts | `{steam_root}/config/stplug-in/*.lua` |
| Depot manifests | `{steam_root}/depotcache/*.manifest` |
| SLSsteam binary | `~/.local/share/SLSsteam/SLSsteam.so` |
| SLSsteam config | `~/.config/SLSsteam/config.yaml` |
| ACCELA | `~/.local/share/ACCELA/` or `~/accela/` |

---

# Credits

- **LuaTools Linux** — StarWarsK & geovanygrdt
- **Contributors** — PeeblyWeeb, GooseLander07
- **Original LuaTools** — madoiscool
- **SLSsteam** — AceSLS
- **ACCELA / Enter The Wired** — ciscosweater
- **Millennium** — SteamClientHomebrew

---

## Star History

<a href="https://www.star-history.com/?repos=Star123451%2FLuaToolsLinux&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=Star123451/LuaToolsLinux&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=Star123451/LuaToolsLinux&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=Star123451/LuaToolsLinux&type=date&legend=top-left" />
 </picture>
</a>

---

# License

See the original LuaTools repository for license information.

## Standalone installation on Linux

`bash install_with_slssteam.sh` installs the standalone bridge and enables it
at desktop login. It uses the same repository defaults as `install.sh`; override
`LUATOOLS_REPO_OWNER`, `LUATOOLS_REPO_NAME`, or `LUATOOLS_REPO_BRANCH` if needed.
The UI repair recognizes Debian installations directly under `~/.steam` as well
as `~/.steam/root`, `~/.steam/steam`, and `~/.local/share/Steam`.

On Millennium 3, the installer registers LuaTools as a frontend plugin backed
by the local Python bridge. On systemd desktops, `luatools-bridge.service` starts
at login and restarts automatically after failure. Check it with
`systemctl --user status luatools-bridge.service` and inspect its logs with
`journalctl --user -u luatools-bridge.service`. Bridge health is available at
`http://127.0.0.1:38495/health`. Reopen a Store page after updating the interface.

Sushi archives containing Windows path separators are validated and converted
to Linux paths before they are passed to ACCELA.
