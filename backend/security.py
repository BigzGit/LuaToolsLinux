"""Validation and filesystem primitives for untrusted backend inputs."""
from contextlib import contextmanager, nullcontext
from functools import wraps
import inspect
import ipaddress
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
from urllib.parse import urlsplit

CONFIG_LOCK = threading.RLock()

# Hostname suffixes that must never be reachable from a downloaded fix URL.
_BLOCKED_HOST_SUFFIXES = ('.localhost', '.local', '.internal', '.home.arpa')


def _is_publicly_routable_host(host):
    if not host:
        return False
    host = host.strip('[]').lower()
    if host in ('localhost', 'localhost.localdomain') or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True  # regular DNS name; resolution itself is not pinned here
    return not (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_reserved or address.is_multicast or address.is_unspecified
    )


def validate_remote_url(url, allowed_hosts=None):
    """Validate an externally supplied download URL.

    Only HTTPS is accepted and URLs targeting loopback/link-local/private
    networks are rejected unless their host appears in ``allowed_hosts``.
    DNS rebinding is not fully mitigated by static validation, so callers
    should still treat downloaded content as untrusted.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError('A download URL is required')
    value = url.strip()
    if any(ord(char) < 33 for char in value):
        raise ValueError('Download URL contains control characters')
    parsed = urlsplit(value)
    if parsed.scheme.lower() != 'https':
        raise ValueError('Only HTTPS downloads are allowed')
    if parsed.username or parsed.password:
        raise ValueError('Credentials are not allowed in download URLs')
    host = parsed.hostname
    if not host:
        raise ValueError('Download URL must include a host')
    parsed.port  # Reject malformed ports before use.
    if allowed_hosts:
        allowed = {entry.strip().lower() for entry in allowed_hosts if entry and entry.strip()}
        if host.lower() not in allowed:
            raise ValueError('Download host is not in the configured allowlist')
    elif not _is_publicly_routable_host(host):
        raise ValueError('Download host is not publicly routable')
    return value


def is_allowed_game_install_path(path, library_roots):
    """Return True when ``path`` is inside a configured Steam library.

    ``library_roots`` are the Steam library directories discovered from
    ``libraryfolders.vdf``. Game installs live under ``steamapps/common``.
    """
    if not path or not isinstance(path, str):
        return False
    try:
        target = os.path.realpath(path)
    except OSError:
        return False
    for root in library_roots or ():
        try:
            common = os.path.realpath(os.path.join(root, 'steamapps', 'common'))
        except OSError:
            continue
        if target == common:
            return True
        try:
            if os.path.commonpath([common, target]) == common:
                return True
        except (ValueError, TypeError):
            continue
    return False


def validate_id(value, maximum=0xFFFFFFFF):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('Invalid numeric ID')
    value = str(value).strip()
    if not re.fullmatch(r'[0-9]{1,20}', value) or not 0 < int(value) <= maximum:
        raise ValueError('Invalid numeric ID')
    return int(value)


def validated_ids(func):
    signature = inspect.signature(func)
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            bound = signature.bind(*args, **kwargs)
            for key in ('appid', 'pubfile_id'):
                if key in bound.arguments:
                    bound.arguments[key] = validate_id(bound.arguments[key], 0xFFFFFFFFFFFFFFFF if key == 'pubfile_id' else 0xFFFFFFFF)
        except (ValueError, TypeError):
            return json.dumps({'success': False, 'error': 'Invalid arguments'})
        mutates_config = func.__name__ in {
            'AddFakeAppId', 'RemoveFakeAppId', 'AddGameToken', 'RemoveGameToken',
            'AddGameDLCs', 'RemoveGameDLCs', 'SetSLSPlayStatus',
            '_remove_from_additional_apps', 'UnFixGame', 'UninstallGameFull',
        }
        with CONFIG_LOCK if mutates_config else nullcontext():
            return func(*bound.args, **bound.kwargs)
    return wrapped


def trusted_ryuu_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        return parsed.scheme == 'https' and (host == 'ryuu.lol' or host.endswith('.ryuu.lol')) and not parsed.username
    except ValueError:
        return False


def relative_parts(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name):
        raise ValueError('Unsafe relative path')
    parts = name.rstrip('/').split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise ValueError('Unsafe relative path')
    return parts


def rooted_path(root, name):
    parts = relative_parts(name)
    path = os.path.realpath(root)
    for part in parts:
        path = os.path.join(path, part)
        if os.path.islink(path):
            raise ValueError('Symlink in destination path')
    return path


def game_install_path(library, install_dir):
    relative_parts(install_dir)
    common = os.path.join(library, 'steamapps', 'common')
    parent = os.path.dirname(install_dir)
    if parent:
        rooted_path(common, parent)
    return os.path.join(common, install_dir)


@contextmanager
def rooted_parent(root, name):
    """Pin each directory with no-follow opens, including during concurrent renames."""
    parts = relative_parts(name)
    fd = os.open(os.path.realpath(root), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            try: os.mkdir(part, dir_fd=fd)
            except FileExistsError: pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


@contextmanager
def atomic_output(path, mode='wb', permissions=0o600):
    parent = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix='.luatools-', dir=parent)
    try:
        os.fchmod(fd, permissions)
        kwargs = {'encoding': 'utf-8'} if 'b' not in mode else {}
        with os.fdopen(fd, mode, **kwargs) as output:
            yield output
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def atomic_write_text(path, text):
    with atomic_output(path, 'w') as output:
        output.write(text)


def normalize_download_zip(path):
    """Convert Windows ZIP separators only after validating every destination.

    Repack atomically so the external launcher and our own reader see identical,
    safe names. General filesystem path validation remains strict.
    """
    import copy
    import zipfile

    with zipfile.ZipFile(path) as source:
        entries = []
        seen = set()
        changed = False
        for member in source.infolist():
            name = member.filename.replace("\\", "/")
            parts = relative_parts(name)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Archive symlinks are not allowed')
            canonical = '/'.join(parts)
            if canonical in seen:
                raise ValueError('Duplicate archive destination')
            seen.add(canonical)
            changed |= name != member.filename
            normalized = copy.copy(member)
            normalized.filename = name
            normalized.orig_filename = name
            entries.append((member, normalized))
        if not changed:
            return
        with atomic_output(path) as output:
            with zipfile.ZipFile(output, 'w') as destination:
                destination.comment = source.comment
                for original, normalized in entries:
                    with source.open(original) as incoming:
                        with destination.open(normalized, 'w') as outgoing:
                            shutil.copyfileobj(incoming, outgoing)


def validate_zip(archive):
    for member in archive.infolist():
        relative_parts(member.filename)
        if stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError('Archive symlinks are not allowed')


def extract_zip(archive, root, prefix='', cancelled=None):
    validate_zip(archive)
    entries = []
    for member in archive.infolist():
        if prefix and member.filename == prefix: continue
        if prefix and not member.filename.startswith(prefix):
            raise ValueError('Unexpected archive prefix')
        name = member.filename[len(prefix):]
        rooted_path(root, name)
        entries.append((member, name))
    extracted = []
    for member, name in entries:
        if cancelled and cancelled(): raise RuntimeError('cancelled')
        with rooted_parent(root, name) as (fd, leaf):
            if member.is_dir():
                try: os.mkdir(leaf, dir_fd=fd)
                except FileExistsError:
                    check = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(check)
                continue
            tmp = '.luatools-' + secrets.token_hex(16)
            mode = 0o644
            try:
                existing = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISREG(existing.st_mode):
                    mode = stat.S_IMODE(existing.st_mode) & 0o777
            except FileNotFoundError:
                pass
            out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=fd)
            try:
                with os.fdopen(out, 'wb') as target, archive.open(member) as source:
                    shutil.copyfileobj(source, target)
                os.replace(tmp, leaf, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try: os.unlink(tmp, dir_fd=fd)
                except FileNotFoundError: pass
            extracted.append(name)
    return extracted


def remove_rooted_file(root, name):
    rooted_path(root, name)
    with rooted_parent(root, name) as (fd, leaf):
        os.unlink(leaf, dir_fd=fd)
