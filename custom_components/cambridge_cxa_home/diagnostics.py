"""Diagnostics download. Host and port are redacted, including inside error text."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from . import CXAConfigEntry

REDACTED = "**REDACTED**"
TO_REDACT = {CONF_HOST, CONF_PORT}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CXAConfigEntry
) -> dict[str, Any]:
    """Return connection and protocol diagnostics without network identifiers."""
    client = entry.runtime_data
    conn = client._conn
    last_error = client.last_error
    if last_error:
        last_error = last_error.replace(client.host, REDACTED).replace(str(client.port), REDACTED)
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "state": asdict(client.state),
        "connection": {
            "connected": conn is not None and not conn.closed,
            "reconnect_count": client.reconnect_count,
            "last_error": last_error,
            "malformed_frames": conn.malformed_count if conn else None,
            "unknown_frames": conn.unknown_count if conn else None,
        },
    }
