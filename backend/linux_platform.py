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


def slssteam_injection_status() -> dict:
    """Read-only check of the SLSsteam LD_AUDIT injection in the Steam launchers.

    Returns a dict::

        {"installed": bool, "injected": bool, "error": str|None,
         "launchers": [str, ...]}
    """
    if not check_slssteam_installed():
        return {"installed": False, "injected": False,
                "error": "SLSsteam not installed", "launchers": []}

    launchers = find_steam_launchers()
    if not launchers:
        return {"installed": True, "injected": False,
                "error": "steam.sh not found", "launchers": []}

    injected = False
    errors: list[str] = []
    for steam_sh in launchers:
        try:
            with open(steam_sh, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            errors.append(f"{steam_sh}: read failed: {exc}")
            continue
        if _is_slssteam_injected(content):
            injected = True

    return {"installed": True, "injected": injected,
            "error": "; ".join(errors) if errors else None,
            "launchers": launchers}


def verify_slssteam_injected() -> dict:
    """Patch every Steam launcher so SLSsteam is loaded via LD_AUDIT.

    Write action used by the repair flow. Returns a dict::

        {"patched": bool, "already_ok": bool, "error": str|None,
         "launchers": [str, ...]}
    """
    status = slssteam_injection_status()
    if not status["installed"]:
        return {"patched": False, "already_ok": False,
                "error": "SLSsteam not installed", "launchers": []}
    if not status["launchers"]:
        return {"patched": False, "already_ok": False,
                "error": "steam.sh not found", "launchers": []}

    patched = False
    already_ok = False
    errors: list[str] = []
    for steam_sh in status["launchers"]:
        try:
            with open(steam_sh, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            errors.append(f"{steam_sh}: read failed: {exc}")
            continue

        if _is_slssteam_injected(content):
            already_ok = True
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

    return {"patched": patched, "already_ok": already_ok,
            "error": "; ".join(errors) if errors else None,
            "launchers": status["launchers"]}


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

