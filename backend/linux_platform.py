"""
Platform detection and path resolution for LuaTools (Linux).

Centralises all platform-specific logic so that the rest of the codebase
can remain clean.  This build targets Linux desktop only.
"""

from __future__ import annotations

import os
import subprocess
import shlex
from typing import Optional


# ---------------------------------------------------------------------------
# Steam path resolution
# ---------------------------------------------------------------------------

_STEAM_PATHS = [
    os.path.expanduser("~/.steam/steam"),
    os.path.expanduser("~/.local/share/Steam"),
    "/opt/steam/steam",
    "/usr/local/steam",
]


def find_steam_root() -> Optional[str]:
    """Search well-known locations for the Steam installation."""
    # Prefer paths containing steam.sh (strongest indicator)
    for path in _STEAM_PATHS:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "steam.sh")):
            return path
    # Fallback: directory just exists
    for path in _STEAM_PATHS:
        if os.path.isdir(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def get_stplugin_dir(steam_root: Optional[str] = None) -> Optional[str]:
    """Return ``config/stplug-in/`` under the Steam root."""
    root = steam_root or find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "config", "stplug-in")


def get_depotcache_dir(steam_root: Optional[str] = None) -> Optional[str]:
    """Return ``depotcache/`` under the Steam root."""
    root = steam_root or find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "depotcache")


# ---------------------------------------------------------------------------
# SLSsteam paths
# ---------------------------------------------------------------------------

_SLSSTEAM_CANDIDATES = [
    os.path.expanduser("~/.local/share/SLSsteam"),
    os.path.expanduser("~/SLSsteam"),
    "/opt/SLSsteam",
]


def get_slssteam_install_dir() -> str:
    """Return the SLSsteam installation directory if found, else the default path."""
    for path in _SLSSTEAM_CANDIDATES:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "SLSsteam.so")):
            return path
    # Default path when no valid installation is found
    return os.path.expanduser("~/.local/share/SLSsteam")


def get_slssteam_config_dir() -> str:
    return os.path.expanduser("~/.config/SLSsteam")


def get_slssteam_config_path() -> str:
    return os.path.join(get_slssteam_config_dir(), "config.yaml")


def check_slssteam_installed() -> bool:
    """Return *True* if ``SLSsteam.so`` exists in any known install dir."""
    for path in _SLSSTEAM_CANDIDATES:
        so_path = os.path.join(path, "SLSsteam.so")
        if os.path.isfile(so_path):
            return True
    return False


# ---------------------------------------------------------------------------
# ACCELA paths
# ---------------------------------------------------------------------------

_ACCELA_CANDIDATES = [
    os.path.expanduser("~/.local/share/ACCELA"),
    os.path.expanduser("~/accela"),
]


def get_accela_dir() -> Optional[str]:
    """Return the ACCELA installation directory if found."""
    for path in _ACCELA_CANDIDATES:
        if os.path.isdir(path):
            return path
    return None


def check_accela_installed() -> bool:
    return get_accela_dir() is not None


def get_accela_run_script() -> Optional[str]:
    """Return the path to ACCELA's launcher script if it exists.

    Prefers launch_debug.sh (logs errors) over run.sh.
    """
    accela_dir = get_accela_dir()
    if not accela_dir:
        return None
    # Prefer the debug wrapper (handles venv + logging for non-terminal launches)
    for name in ("launch_debug.sh", "run.sh"):
        script = os.path.join(accela_dir, name)
        if os.path.isfile(script):
            return script
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def open_directory(path: str) -> None:
    """Open a directory in the file manager via ``xdg-open``."""
    subprocess.Popen(
        ["xdg-open", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# SLSsteam injection verification
# ---------------------------------------------------------------------------

SLSSTEAM_INJECTION_MARKER = "# LuaToolsLinux SLSsteam injection"

# Installed Steam launchers source the client. They are separate from the
# Steam data directory returned by find_steam_root() (which holds stplug-in,
# depotcache, ...). On Debian the launcher lives at ~/.steam/steam.sh.
_STEAM_LAUNCHER_CANDIDATES = [
    os.path.expanduser("~/.steam/steam.sh"),
    os.path.expanduser("~/.steam/root/steam.sh"),
    os.path.expanduser("~/.steam/steam/steam.sh"),
    os.path.expanduser("~/.local/share/Steam/steam.sh"),
    os.path.expanduser("~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steam.sh"),
]


def find_steam_launchers() -> list[str]:
    """Return existing Steam launcher scripts (deduplicated by real path)."""
    launchers: list[str] = []
    seen: set[str] = set()
    for candidate in _STEAM_LAUNCHER_CANDIDATES:
        if not os.path.isfile(candidate):
            continue
        resolved = os.path.realpath(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        launchers.append(candidate)
    return launchers


def _get_ld_audit_line() -> str:
    """Build the LD_AUDIT export line using the detected SLSsteam install dir."""
    sls_dir = get_slssteam_install_dir()
    return 'export LD_AUDIT=' + shlex.quote(f'{sls_dir}/library-inject.so:{sls_dir}/SLSsteam.so')


def _inject_ld_audit(content: str) -> str | None:
    """Return *content* with the LD_AUDIT export inserted, or None if no anchor."""
    line = _get_ld_audit_line()
    block = f"{SLSSTEAM_INJECTION_MARKER}\n{line}\n\n"
    # Insert right before Steam actually launches the client so only the client
    # process tree (not the shell helpers) inherits the audit library.
    for anchor in ("# and launch steam", '"$STEAMROOT/$STEAMEXEPATH"'):
        index = content.find(anchor)
        if index != -1:
            return content[:index] + block + content[index:]
    return None


def _is_slssteam_injected(content: str) -> bool:
    return "LD_AUDIT" in content and "SLSsteam" in content


def _get_ld_audit_env() -> str:
    """LD_AUDIT assignment usable inside a .desktop Exec line."""
    sls_dir = get_slssteam_install_dir()
    return f'LD_AUDIT="{sls_dir}/library-inject.so:{sls_dir}/SLSsteam.so"'


# Desktop entries used to launch Steam. Patching the user copy survives the
# Debian launcher rewriting ~/.steam/steam.sh on client updates.
_STEAM_DESKTOP_SOURCES = [
    os.path.expanduser("~/.steam/deb-installer/steam.desktop"),
    "/usr/share/applications/steam.desktop",
    "/usr/local/share/applications/steam.desktop",
]


def get_user_desktop_path() -> str:
    """Path of the user override for the Steam application menu entry."""
    return os.path.expanduser("~/.local/share/applications/steam.desktop")


def _inject_desktop_ld_audit(content: str) -> str | None:
    """Prefix Steam Exec= lines with the LD_AUDIT env, or None if unchanged."""
    prefix = "env " + _get_ld_audit_env() + " "
    changed = False
    out: list[str] = []
    for line in content.splitlines(keepends=True):
        body = line.rstrip("\n")
        stripped = body.lstrip()
        indent = body[: len(body) - len(stripped)]
        if stripped.startswith("Exec="):
            value = stripped[len("Exec="):].strip()
            if "steam" in value and "LD_AUDIT" not in value:
                out.append(f"{indent}Exec={prefix}{value}\n")
                changed = True
                continue
        out.append(line)
    return "".join(out) if changed else None


def desktop_override_status() -> bool:
    """Return True when the user Steam desktop entry sets the LD_AUDIT env."""
    try:
        with open(get_user_desktop_path(), "r", encoding="utf-8") as f:
            return _is_slssteam_injected(f.read())
    except Exception:
        return False


def _install_desktop_override() -> bool:
    """Write a user desktop entry that launches Steam with SLSsteam loaded."""
    injected = None
    for source in _STEAM_DESKTOP_SOURCES:
        if not os.path.isfile(source):
            continue
        try:
            with open(source, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        if _is_slssteam_injected(content):
            injected = content
            break
        candidate = _inject_desktop_ld_audit(content)
        if candidate is not None:
            injected = candidate
            break
    if injected is None:
        return False

    target = get_user_desktop_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.islink(target) or os.path.exists(target):
            os.remove(target)
        with open(target, "w", encoding="utf-8") as f:
            f.write(injected)
        os.chmod(target, 0o755)
        return True
    except Exception:
        return False


def slssteam_injection_status() -> dict:
    """Read-only check of the SLSsteam LD_AUDIT injection.

    Returns a dict::

        {"installed": bool, "injected": bool, "launcher": bool,
         "desktop": bool, "error": str|None, "launchers": [str, ...]}
    """
    if not check_slssteam_installed():
        return {"installed": False, "injected": False, "launcher": False,
                "desktop": False, "error": "SLSsteam not installed",
                "launchers": []}

    launchers = find_steam_launchers()
    launcher_injected = False
    errors: list[str] = []
    for steam_sh in launchers:
        try:
            with open(steam_sh, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            errors.append(f"{steam_sh}: read failed: {exc}")
            continue
        if _is_slssteam_injected(content):
            launcher_injected = True

    desktop = desktop_override_status()
    error = "; ".join(errors) if errors else None
    if not launchers and not desktop and error is None:
        error = "steam.sh not found"

    return {"installed": True, "injected": launcher_injected or desktop,
            "launcher": launcher_injected, "desktop": desktop,
            "error": error, "launchers": launchers}


def verify_slssteam_injected() -> dict:
    """Patch the Steam launchers and desktop entry so SLSsteam is loaded.

    Write action used by the repair flow. Returns a dict::

        {"patched": bool, "already_ok": bool, "error": str|None,
         "desktop": bool, "launchers": [str, ...]}
    """
    status = slssteam_injection_status()
    if not status["installed"]:
        return {"patched": False, "already_ok": False,
                "error": "SLSsteam not installed", "desktop": False,
                "launchers": []}

    already_ok = bool(status["injected"])
    patched = False
    errors: list[str] = []
    for steam_sh in status["launchers"]:
        try:
            with open(steam_sh, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            errors.append(f"{steam_sh}: read failed: {exc}")
            continue

        if _is_slssteam_injected(content):
            continue

        injected = _inject_ld_audit(content)
        if injected is None:
            errors.append(f"{steam_sh}: unsupported launcher layout")
            continue

        try:
            with open(steam_sh, "w", encoding="utf-8") as f:
                f.write(injected)
            patched = True
        except Exception as exc:
            errors.append(f"{steam_sh}: write failed: {exc}")

    desktop = status["desktop"]
    if not desktop:
        if _install_desktop_override():
            desktop = True
            patched = True
        else:
            errors.append("steam.desktop override unavailable")

    return {"patched": patched, "already_ok": already_ok,
            "error": "; ".join(errors) if errors else None,
            "desktop": desktop, "launchers": status["launchers"]}



def get_platform_summary() -> dict:
    """Return a dict of platform diagnostics for logging."""
    summary = {
        "steam_root": find_steam_root(),
        "slssteam_installed": check_slssteam_installed(),
        "accela_installed": check_accela_installed(),
        "accela_dir": get_accela_dir(),
    }
    if summary["slssteam_installed"]:
        status = slssteam_injection_status()
        summary["slssteam_injection"] = status
    return summary

