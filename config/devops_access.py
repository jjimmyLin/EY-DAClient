"""
Local DevOps access guard.

This is a convenience gate for the desktop client. It is not a security
boundary against someone who can modify or rebuild the app.
"""

from __future__ import annotations

import hashlib
import os


DEVOPS_DENIED_MESSAGE = (
    "You have no right/access to modify DevOps settings on this machine."
)

_ALLOWED_MACHINE_GUID_HASHES = {
    "efb1cb23d0d095363bd453375ef5a25c9a0a1a783dba09c598bb5e4e12fd5c4f",
}


def current_machine_guid() -> str:
    """Return the Windows MachineGuid, or an empty string when unavailable."""
    if os.name != "nt":
        return ""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value)
    except OSError:
        return ""


def is_devops_machine(machine_guid: str | None = None) -> bool:
    """Return True only for hard-coded approved MachineGuid values."""
    value = machine_guid if machine_guid is not None else current_machine_guid()
    normalized = value.strip().lower()
    if not normalized:
        return False

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest in _ALLOWED_MACHINE_GUID_HASHES
