from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:access|refresh|id)?token(?:$|[_-])|secret|credential|cookie|password|private[_-]?key|client[_-]?secret",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:ya29\.[A-Za-z0-9._-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._~+/-]+=*)",
    re.IGNORECASE,
)


def redact(value: Any) -> Any:
    """Return a JSON-compatible copy with credential-shaped values removed."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub("[REDACTED]", value)
    return value


def contains_sensitive_material(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _SENSITIVE_KEY.search(str(key)) is not None or contains_sensitive_material(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_sensitive_material(item) for item in value)
    return isinstance(value, str) and _SENSITIVE_VALUE.search(value) is not None
