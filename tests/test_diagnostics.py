"""Diagnostics must not leak network identifiers."""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cambridge_cxa_home.diagnostics import async_get_config_entry_diagnostics
from tools.mock_amplifier import MockAmplifier

from .conftest import HOST, wait_for

pytestmark = pytest.mark.usefixtures("socket_enabled", "fast_client")


async def test_diagnostics_redacted(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = entry.runtime_data

    await amp.stop()  # produce a last_error that mentions host:port
    await wait_for(lambda: not client.state.available)
    await wait_for(lambda: client.last_error is not None and "cannot connect" in client.last_error)

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag)
    assert HOST not in text
    assert str(amp.port) not in text  # type: ignore[attr-defined]
    assert diag["entry"]["model"] == "CXA81"
    assert diag["state"]["protocol_version"] == "1.0"
    assert diag["connection"]["connected"] is False
    await hass.config_entries.async_unload(entry.entry_id)
