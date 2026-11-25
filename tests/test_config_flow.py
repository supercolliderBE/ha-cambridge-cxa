"""Config flow tests: add, validate read-only, prevent duplicates, reconfigure."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cambridge_cxa_home.client import (
    CXAConnectError,
    CXARejectedError,
    CXATimeoutError,
)
from custom_components.cambridge_cxa_home.const import DOMAIN
from custom_components.cambridge_cxa_home.protocol import DeviceError, ErrorCode
from tools.mock_amplifier import MockAmplifier, MockState

from .conftest import HOST, WRITE_PREFIXES

pytestmark = pytest.mark.usefixtures("socket_enabled")

FLOW_INFO = "custom_components.cambridge_cxa_home.config_flow.fetch_device_info"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result["flow_id"]


async def test_user_flow_success_is_read_only(
    hass: HomeAssistant, amp: MockAmplifier, fast_client: None
) -> None:
    amp.state = MockState(power=False, muted=True, source="03")
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {"model": "CXA81", "host": f" {HOST} ", "port": amp.port},  # type: ignore[attr-defined]
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cambridge Audio CXA81"
    assert result["data"] == {"host": HOST, "port": amp.port, "model": "CXA81"}  # type: ignore[attr-defined]
    entry = result["result"]
    assert entry.unique_id and len(entry.unique_id) == 32
    await hass.async_block_till_done()
    # Neither validation nor setup may change the amplifier.
    assert not [line for line in amp.received if line.startswith(WRITE_PREFIXES)]
    assert amp.state == MockState(power=False, muted=True, source="03")
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (CXAConnectError("x"), "cannot_connect"),
        (CXATimeoutError("x"), "no_response"),
        (CXARejectedError(DeviceError(ErrorCode.GROUP_UNKNOWN)), "rejected"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recover(
    hass: HomeAssistant, amp: MockAmplifier, fast_client: None, error: Exception, key: str
) -> None:
    flow_id = await _start(hass)
    user_input = {"model": "CXA81", "host": HOST, "port": amp.port}  # type: ignore[attr-defined]
    with patch(FLOW_INFO, side_effect=error):
        result = await hass.config_entries.flow.async_configure(flow_id, user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}
    # The form keeps what the user typed, and a retry can succeed.
    result = await hass.config_entries.flow.async_configure(flow_id, user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_flow_unreachable_bridge(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"model": "CXA81", "host": HOST, "port": _free_port()}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_host_port_aborts(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {"model": "CXA81", "host": HOST, "port": amp.port},  # type: ignore[attr-defined]
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert amp.received == []  # aborted before touching the bridge


async def test_reconfigure_keeps_identity(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry, fast_client: None
) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    second = MockAmplifier()
    port = await second.start(HOST, 0)
    try:
        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"
        with patch(FLOW_INFO, side_effect=CXAConnectError("x")):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"host": HOST, "port": port}
            )
        assert result["errors"] == {"base": "cannot_connect"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": HOST, "port": port}
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        assert entry.data["port"] == port
        assert entry.unique_id == "0123456789abcdef0123456789abcdef"
        assert second.client_count == 1  # reloaded onto the new bridge
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await second.stop()


async def test_reconfigure_to_other_entrys_address_aborts(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN, unique_id="other", data={"host": "10.0.0.9", "port": 8899, "model": "CXA81"}
    )
    other.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "10.0.0.9", "port": 8899}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
