#!/usr/bin/env bash

# ==================================================
#   _____ _ _ _             _
#  |     |_| | |___ ___ ___|_|_ _ _____
#  | | | | | | | -_|   |   | | | |     |
#  |_|_|_|_|_|_|___|_|_|_|_|_|___|_|_|_|
#
# ==================================================

readonly GITHUB_ACCOUNT="SteamClientHomebrew/Millennium"
readonly RELEASES_URI="https://api.github.com/repos/${GITHUB_ACCOUNT}/releases"
readonly DOWNLOAD_URI="https://github.com/${GITHUB_ACCOUNT}/releases/download"
# Audited release pinned by the LuaTools repository. The digest below is the
# trust anchor; it is never read from the network at install time.
readonly PINNED_VERSION="2.35.0"
readonly EXPECTED_SHA256="d9f835b1956530f51eeeed0beaa7f566c6a496d9f3899c2c2c7c10ab125cb87a"
INSTALL_DIR=""
DRY_RUN=0
ALLOW_BETA=0

log() { printf "%b\n" "$1"; }
is_root() { [ "$(id -u)" -eq 0 ]; }
format_size() {
    echo "$1" | awk '{ split("B KB MB GB TB PB", v); s=1; while ($1 > 1024) { $1 /= 1024; s++ } printf "%.2f %s\n", $1, v[s] }'
}

verify_platform() {
    case $(uname -sm) in
        "Linux x86_64") echo "linux-x86_64" ;;
        *) log "Unsupported platform $(uname -sm). x86_64 is the only available platform."; exit 1 ;;
    esac
}

check_dependencies() {
    log "resolving dependencies..."
    for cmd in curl tar jq sudo; do
        command -v "${cmd}" >/dev/null || {
            log "${cmd} isn't installed. Install it from your package manager." >&2
            exit 1
        }
    done
}

# Força a versão 2.35.0
fetch_release_info() {
    echo "2.35.0:35546112"
    return 0
}

confirm_installation() {
    echo -e "\n:: Proceed with installation? [Y/n] \c"
    read -r proceed </dev/tty
    case "${proceed}" in
        [Nn]*) exit 1 ;;
        *) return 0 ;;
    esac
}

# Nova função para remover versões anteriores
remove_old_installation() {
    log ":: Cleaning up previous Millennium installations..."

    sudo rm -rf /usr/lib/millennium /usr/share/millennium || return 1
    rm -rf -- "${XDG_CONFIG_HOME:-$HOME/.config}/millennium" \
                "${XDG_DATA_HOME:-$HOME/.local/share}/millennium"

    # Verifica se o backup existe antes de tentar mover, evitando erros na tela
    if [ -f "/usr/bin/steam.millennium.bak" ]; then
        log "   Restoring original steam executable..."
        sudo mv /usr/bin/steam.millennium.bak /usr/bin/steam
    fi
}

download_package() {
    local url="$1"
    local dest="$2"
    if ! curl --proto "=https" --proto-redir "=https" --fail --location --output "${dest}" "${url}"; then
        log "Download failed for ${url}"
        return 1
    fi
}

extract_package() {
    local tar_file="$1"
    local extract_dir="$2"
    mkdir -p "${extract_dir}"
    tar xzf "${tar_file}" -C "${extract_dir}"
}

install_millennium() {
    local extract_path="$1"

    if [ "${DRY_RUN}" -eq 0 ]; then
        sudo cp -r "${extract_path}"/* / || return 1
    else
        log "[DRY RUN] Would copy files from ${extract_path} to /"
    fi
}

post_install() {
    # Evita erro se o arquivo python não existir (já que fixamos a versão, pode variar)
    [ -f /opt/python-i686-3.11.8/bin/python3.11 ] && sudo chmod +x /opt/python-i686-3.11.8/bin/python3.11

    log "installing for '${USER}'"

    beta_file="${HOME}/.steam/steam/package/beta"
    target="${HOME}/.steam/steam/ubuntu12_32/libXtst.so.6"

    if [ -f "${beta_file}" ]; then
        log "removing beta '$(cat "${beta_file}")' in favor for stable."
        rm "${beta_file}"
    fi

    [ -d "${HOME}/.steam/steam/ubuntu12_32" ] && ln -sf /usr/lib/millennium/libmillennium_bootstrap_86x.so "${target}"
}

cleanup() {
    local dir="$1"
    log "cleaning up temporary files..."
    rm -rf "${dir}"
}

main() {
    local target release_info tag size download_uri install_dir extract_path tar_file

    for arg in "$@"; do
        case ${arg} in
            --dry-run) DRY_RUN=1; shift ;;
            --beta) ALLOW_BETA=1; shift ;;
        esac
    done

    if is_root; then
        log "Do not run this script as root!"
        log "aborting installation..."
        exit
    fi

    target=$(verify_platform)
    check_dependencies

    release_info=$(fetch_release_info)
    tag="${release_info%%:*}"
    size=$(format_size "${release_info##*:}")

    install_size_uri="${DOWNLOAD_URI}/v${tag}/millennium-v${tag}-${target}.installsize"
    download_uri="${DOWNLOAD_URI}/v${tag}/millennium-v${tag}-${target}.tar.gz"

    if [ "${tag}" != "${PINNED_VERSION}" ]; then
        log "Refusing to install untrusted Millennium version '${tag}' (expected ${PINNED_VERSION})."
        exit 1
    fi

    # The digest is the one pinned in this repository, not the remote .sha256 file.
    sha256digest="${EXPECTED_SHA256}  millennium-v${tag}-${target}.tar.gz"
    installed_size=$(format_size "$(curl --proto "=https" --proto-redir "=https" -fsSL "${install_size_uri}")")

    log "\nPackages (1) millennium@${tag}-x86_64\n"
    log "Total Download Size:  $(printf "%10s\n" "${size}")"
    log "Total Installed Size: $(printf "%10s\n" "${installed_size}")"

    confirm_installation


    log "receiving packages..."

    install_dir="$(mktemp -d)" || exit 1
    INSTALL_DIR="$install_dir"
    trap 'rm -rf -- "$INSTALL_DIR"' EXIT
    extract_path="${install_dir}/files"
    tar_file="${install_dir}/millennium-v${tag}-${target}.tar.gz"

    log "(1/4) Downloading millennium-v${tag}-${target}.tar.gz..."
    download_package "${download_uri}" "${tar_file}" || exit 1

    log "(2/4) Verifying checksums..."
    if (cd "${install_dir}" && echo "${sha256digest}" | sha256sum -c --status); then
        echo -ne "\033[1A"
        log "(2/4) Verifying checksums... OK"
    else
        log "(2/4) Verifying checksums... FAILED"
        exit 1
    fi

    log "(3/4) Unpacking millennium-v${tag}-${target}.tar.gz..."
    extract_package "${tar_file}" "${extract_path}" || exit 1

    log "(4/4) Installing millennium..."
    if [ "$DRY_RUN" -eq 0 ]; then
        remove_old_installation || exit 1
    fi
    install_millennium "${extract_path}" || exit 1

    log ":: Running post-install scripts..."
    log "(1/1) Setting up shared object preloader hook..."
    if [ "$DRY_RUN" -eq 0 ]; then
        post_install
    fi

    cleanup "${install_dir}"

    log "done.\n"
    log "You can now start Steam."
}

main "$@"

