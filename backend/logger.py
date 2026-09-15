"""Shared logger instance for the LuaTools backend."""

from __future__ import annotations

import sys
import re
from urllib.parse import urlsplit, urlunsplit


class _StandaloneLogger:
    """Fallback logger used when Millennium PluginUtils is unavailable."""

    def log(self, message: str) -> None:
        print(message)

    def warn(self, message: str) -> None:
        print(message, file=sys.stderr)

    def error(self, message: str) -> None:
        print(message, file=sys.stderr)

    def info(self, message: str) -> None:
        self.log(message)

    def debug(self, message: str) -> None:
        self.log(message)


def redact_message(message):
    def redact_url(match):
        try:
            parts = urlsplit(match.group(0))
            host = parts.netloc.rsplit('@', 1)[-1]
            return urlunsplit((parts.scheme, host, parts.path, '[redacted]' if parts.query else '', ''))
        except ValueError:
            return '[redacted URL]'
    text = re.sub(r"https?://[^\s<>\"']+", redact_url, str(message))
    return re.sub(r'(?i)(api_key|access_token|authorization|session|cookie)([=:]\s*)[^\s,;]+',
                  r'\1\2[redacted]', text)


class _RedactingLogger:
    def __init__(self, target):
        self.target = target

    def __getattr__(self, name):
        method = getattr(self.target, name)
        if name in {'log', 'warn', 'error', 'info', 'debug'}:
            return lambda message: method(redact_message(message))
        return method


_LOGGER_INSTANCE = None


def get_logger():
    """Return a singleton logger instance."""
    global _LOGGER_INSTANCE
    if _LOGGER_INSTANCE is not None:
        return _LOGGER_INSTANCE

    try:
        import PluginUtils  # type: ignore

        _LOGGER_INSTANCE = PluginUtils.Logger()
    except ModuleNotFoundError:
        _LOGGER_INSTANCE = _StandaloneLogger()

    _LOGGER_INSTANCE = _RedactingLogger(_LOGGER_INSTANCE)
    return _LOGGER_INSTANCE


# Convenience alias so other modules can `from logger import logger`
logger = get_logger()


