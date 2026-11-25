"""Setup, retry, unload and shutdown of config entries."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.mock_amplifier import MockAmplifier

from .conftest import wait_for

pytestmark = pytest.mark.usefixtures("socket_enabled", "fast_client")


def _cxa_tasks() -> list[asyncio.Task[object]]:
    return [
        t for t in asyncio.all_tasks() if t.get_name().startswith("cambridge_cxa") and not t.done()
    ]


async def test_setup_and_unload(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.state.available
    assert amp.client_count == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert _cxa_tasks() == []
    await wait_for(lambda: amp.client_count == 0)


async def test_setup_retries_when_bridge_unreachable(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    await amp.stop()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _cxa_tasks() == []  # nothing left running between retries


async def test_setup_retries_when_amplifier_silent(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    amp.behaviour.unresponsive = True
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason and "not answering" in entry.reason


async def test_reload(hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await wait_for(lambda: amp.client_count == 1)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_home_assistant_stop_closes_connection(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_stop()
    assert _cxa_tasks() == []
    await wait_for(lambda: amp.client_count == 0)
