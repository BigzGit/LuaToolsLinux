"""Per-installation credentials shared by the bridge and Steam UI injector."""
import fcntl
import os
from pathlib import Path
import re
import secrets
import stat


def get_bridge_token(install_root=None):
    root = Path(install_root) if install_root else Path(__file__).resolve().parent.parent
    directory = root / 'backend' / 'data'
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    path = directory / 'bridge_token'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise ValueError('Unsafe bridge credential file')
        os.fchmod(fd, 0o600)
        token = os.read(fd, 129).decode('ascii').strip()
        if not token:
            token = secrets.token_hex(32)
            os.write(fd, token.encode('ascii'))
            os.fsync(fd)
        if not re.fullmatch(r'[0-9a-f]{64}', token):
            raise ValueError('Invalid bridge credential file')
        return token
    finally:
        os.close(fd)
