#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${LUATOOLS_REPO_OWNER:-BigzGit}"
REPO_NAME="${LUATOOLS_REPO_NAME:-LuaToolsLinux}"
BRANCH="${LUATOOLS_REPO_BRANCH:-main}"

INSTALL_ROOT="$HOME/.local/share/LuaToolsLinux"
VENV_DIR="$INSTALL_ROOT/.venv"
BIN_DIR="$HOME/.local/bin"
WRAPPER_PATH="$BIN_DIR/luatools"
BRIDGE_STARTER="$BIN_DIR/luatools-bridge"
UI_HEALER="$BIN_DIR/luatools-heal-ui"
TMP_DIR=""

info() { echo "[LuaTools] $*"; }
warn() { echo "[LuaTools][WARN] $*"; }
fail() { echo "[LuaTools][FAIL] $*"; exit 1; }

cleanup() {
    if [ -n "${TMP_DIR:-}" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

extract_zip() {
    python3 - "$1" "$2" <<'PYZIP'
import os
import stat
import sys
import zipfile

root = os.path.realpath(sys.argv[2])
with zipfile.ZipFile(sys.argv[1]) as archive:
    for member in archive.infolist():
        name = member.filename
        parts = name.rstrip('/').split('/')
        if (any(p in ('', '.', '..') for p in parts) or '\\' in name or ':' in name
                or any(ord(c) < 32 for c in name) or stat.S_ISLNK(member.external_attr >> 16)):
            raise ValueError('Unsafe archive member')
        target = root
        for part in parts:
            target = os.path.join(target, part)
            if os.path.islink(target):
                raise ValueError('Symlink in extraction destination')
    archive.extractall(root)
PYZIP
}

install_session_startup() {
    local autostart_dir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    local startup="$BIN_DIR/luatools-session"
    local quoted_healer quoted_starter
    printf -v quoted_healer '%q' "$UI_HEALER"
    printf -v quoted_starter '%q' "$BRIDGE_STARTER"
    cat > "$startup" <<EOF
#!/usr/bin/env bash
set -euo pipefail
$quoted_healer
exec $quoted_starter
EOF
    chmod +x "$startup"
    mkdir -p "$autostart_dir"
    python3 - "$autostart_dir/luatools.desktop" "$startup" <<'PYAUTO'
import sys
from pathlib import Path
# Desktop Exec quoting is different from shell quoting.
command = sys.argv[2].replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
Path(sys.argv[1]).write_text('[Desktop Entry]\nType=Application\nName=LuaTools bridge\nExec="' + command + '"\nTerminal=false\n')
PYAUTO
}

main() {
    if [[ "${EUID}" -eq 0 && "${LUATOOLS_ALLOW_ROOT:-}" != "1" ]]; then
        fail "Do not run this installer as root. Run it as your normal user."
    fi
    require_cmd curl
    require_cmd python3

    TMP_DIR="$(mktemp -d)"
    trap cleanup EXIT

    local archive="$TMP_DIR/luatools.zip"
    local src="$TMP_DIR/src"
    local zip_url="https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/zip/refs/heads/${BRANCH}"

    info "Downloading LuaTools bundle from ${REPO_OWNER}/${REPO_NAME}@${BRANCH}"
    curl --proto '=https' --proto-redir '=https' -fsSL "$zip_url" -o "$archive"

    mkdir -p "$src"
    if ! extract_zip "$archive" "$src"; then
        fail "Could not extract LuaTools archive"
    fi

    local extracted
    extracted="$(find "$src" -maxdepth 1 -type d -name "${REPO_NAME}-*" | head -n 1)"
    [[ -n "$extracted" ]] || fail "Extracted content not found"

    mkdir -p "$INSTALL_ROOT"
    rm -rf "$INSTALL_ROOT/backend" "$INSTALL_ROOT/public"

    cp -r "$extracted/backend" "$INSTALL_ROOT/backend"
    cp -r "$extracted/public" "$INSTALL_ROOT/public"
    cp "$extracted/requirements.txt" "$INSTALL_ROOT/requirements.txt"
    if [[ -f "$extracted/requirements.lock" ]]; then
        cp "$extracted/requirements.lock" "$INSTALL_ROOT/requirements.lock"
    fi
    cp "$extracted/README.md" "$INSTALL_ROOT/README.md"

    info "Installing Python dependencies"
    local python_bin="python3"
    if python3 -m venv "$VENV_DIR" >/dev/null 2>&1; then
        python_bin="$VENV_DIR/bin/python"
    else
        warn "Could not create a local virtualenv; falling back to user-site pip install."
    fi

    # Prefer the hash-pinned lockfile; fall back to pinned requirements only if
    # hash verification is unavailable.
    local requirements_arg="$INSTALL_ROOT/requirements.txt"
    local hash_args=()
    if [[ -f "$INSTALL_ROOT/requirements.lock" ]]; then
        requirements_arg="$INSTALL_ROOT/requirements.lock"
        hash_args=(--require-hashes)
    fi

    if ! "$python_bin" -m pip install "${hash_args[@]}" -r "$requirements_arg" >/dev/null 2>&1; then
        if [[ "$python_bin" != "python3" ]]; then
            warn "Virtualenv pip install failed; retrying with user-site pip."
            if ! python3 -m pip install --user "${hash_args[@]}" -r "$requirements_arg" >/dev/null 2>&1; then
                if [[ ${#hash_args[@]} -gt 0 ]]; then
                    warn "Hash-verified install failed; retrying pinned requirements without hashes."
                    requirements_arg="$INSTALL_ROOT/requirements.txt"
                    if ! python3 -m pip install --user -r "$requirements_arg" >/dev/null 2>&1; then
                        fail "Python dependency install failed"
                    fi
                else
                    fail "Python dependency install failed"
                fi
            fi
            python_bin="python3"
        else
            fail "Python dependency install failed"
        fi
    fi

    mkdir -p "$BIN_DIR"
    local quoted_python quoted_cli quoted_bridge quoted_injector quoted_root
    printf -v quoted_python '%q' "${python_bin:-$VENV_DIR/bin/python}"
    printf -v quoted_cli '%q' "$INSTALL_ROOT/backend/standalone_cli.py"
    printf -v quoted_bridge '%q' "$INSTALL_ROOT/backend/web_bridge_server.py"
    printf -v quoted_injector '%q' "$INSTALL_ROOT/backend/ui_injector.py"
    printf -v quoted_root '%q' "$INSTALL_ROOT"
    cat > "$WRAPPER_PATH" <<EOF
#!/usr/bin/env bash
PYTHON_BIN=$quoted_python
if [[ ! -x "\$PYTHON_BIN" ]]; then
    PYTHON_BIN=python3
fi
exec "\$PYTHON_BIN" $quoted_cli "\$@"
EOF
    chmod +x "$WRAPPER_PATH"

    cat > "$BRIDGE_STARTER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN=$quoted_python
if [[ ! -x "\$PYTHON_BIN" ]]; then
    PYTHON_BIN=python3
fi
BRIDGE_HOST="127.0.0.1"
BRIDGE_PORT="38495"
LOG_FILE="\${XDG_STATE_HOME:-\$HOME/.local/state}/luatools/bridge.log"
umask 077
PID_DIR="\${XDG_STATE_HOME:-\$HOME/.local/state}/luatools"
mkdir -p "\$PID_DIR"
PID_FILE="\$PID_DIR/bridge.pid"
mkdir -p "\$(dirname "\$LOG_FILE")"

if [[ -f "\$PID_FILE" ]]; then
    if kill -0 "\$(cat "\$PID_FILE")" >/dev/null 2>&1; then
        exit 0
    fi
    rm -f "\$PID_FILE"
fi

nohup "\$PYTHON_BIN" $quoted_bridge --host "\$BRIDGE_HOST" --port "\$BRIDGE_PORT" >>"\$LOG_FILE" 2>&1 &
echo "\$!" > "\$PID_FILE"

health_url="http://\$BRIDGE_HOST:\$BRIDGE_PORT/health"
for _ in 1 2 3 4 5; do
    if "\$PYTHON_BIN" - "\$health_url" <<'PY' >/dev/null 2>&1; then
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=1) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
        echo "LuaTools bridge ready at \$health_url"
        exit 0
    fi
    sleep 1
done

echo "LuaTools bridge started but is not reachable at \$health_url" >&2
echo "Check \$LOG_FILE for details." >&2
exit 1
EOF
    chmod +x "$BRIDGE_STARTER"

    cat > "$UI_HEALER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN=$quoted_python
if [[ ! -x "\$PYTHON_BIN" ]]; then
    PYTHON_BIN=python3
fi
export LUATOOLS_INSTALL_ROOT=$quoted_root
exec "\$PYTHON_BIN" $quoted_injector
EOF
    chmod +x "$UI_HEALER"

    local ui_output=""
    if ! ui_output="$("$UI_HEALER" 2>&1)"; then
        warn "UI self-heal step failed"
        if [ -n "$ui_output" ]; then
            warn "$ui_output"
        fi
    elif [ -n "$ui_output" ]; then
        info "$ui_output"
    fi

    if command -v systemctl >/dev/null && [[ -f "$INSTALL_ROOT/backend/millennium_bridge.py" ]]; then
        "$python_bin" "$INSTALL_ROOT/backend/millennium_bridge.py"
    else
        install_session_startup
        "$BRIDGE_STARTER" || fail "LuaTools bridge failed to start"
    fi

    info "LuaTools standalone installed"
    info "CLI wrapper: $WRAPPER_PATH"
    info "Bridge starter: $BRIDGE_STARTER"
    info "UI healer: $UI_HEALER"
    info "Example: luatools init-apis"
}

main "$@"
