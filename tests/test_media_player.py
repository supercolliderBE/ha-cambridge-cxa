"""Media player entity: state mapping, push updates, commands, availability."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_INPUT_SOURCE_LIST,
    ATTR_MEDIA_VOLUME_MUTED,
    SERVICE_SELECT_SOURCE,
    MediaPlayerDeviceClass,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player import (
    DOMAIN as MP_DOMAIN,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_MUTE,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cambridge_cxa_home.const import DOMAIN
from tools.mock_amplifier import MockAmplifier

from .conftest import ENTITY_ID, UNIQUE_ID, wait_for

pytestmark = pytest.mark.usefixtures("socket_enabled", "fast_client")

CXA81_SOURCES = [
    "A1",
    "A2",
    "A3",
    "A4",
    "D1",
    "D2",
    "D3",
    "Bluetooth",
    "USB Audio",
    "A1 Balanced",
]


@pytest.fixture
async def loaded(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> AsyncIterator[MockConfigEntry]:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)


def _state(hass: HomeAssistant):
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    return state


async def _call(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(
        MP_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID, **data}, blocking=True
    )


async def test_initial_state_and_attributes(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    state = _state(hass)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_INPUT_SOURCE] == "A1 Balanced"
    assert state.attributes[ATTR_INPUT_SOURCE_LIST] == CXA81_SOURCES
    assert state.attributes[ATTR_MEDIA_VOLUME_MUTED] is False
    assert state.attributes[ATTR_DEVICE_CLASS] == MediaPlayerDeviceClass.RECEIVER
    features = MediaPlayerEntityFeature(state.attributes[ATTR_SUPPORTED_FEATURES])
    assert features == (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    # Explicitly: no volume or playback features exist.
    for absent in (
        MediaPlayerEntityFeature.VOLUME_SET,
        MediaPlayerEntityFeature.VOLUME_STEP,
        MediaPlayerEntityFeature.PLAY,
        MediaPlayerEntityFeature.PAUSE,
    ):
        assert not features & absent
    assert "volume_level" not in state.attributes


async def test_registry_entries(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity is not None
    assert entity.unique_id == UNIQUE_ID
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, UNIQUE_ID), loaded.entry_id)
    assert device is not None
    assert device.manufacturer == "Cambridge Audio"
    assert device.model == "CXA81"
    assert device.name == "Cambridge Audio CXA81"
    assert device.sw_version == "SYNTHETIC-0.0"


async def test_turn_off_and_on(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    await _call(hass, SERVICE_TURN_OFF)
    assert _state(hass).state == STATE_OFF
    assert amp.state.power is False
    await _call(hass, SERVICE_TURN_ON)
    assert _state(hass).state == STATE_ON
    assert amp.state.power is True


async def test_mute(hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry) -> None:
    await _call(hass, SERVICE_VOLUME_MUTE, is_volume_muted=True)
    assert _state(hass).attributes[ATTR_MEDIA_VOLUME_MUTED] is True
    assert amp.state.muted is True
    await _call(hass, SERVICE_VOLUME_MUTE, is_volume_muted=False)
    assert amp.state.muted is False


@pytest.mark.parametrize(
    ("name", "code"), [("A1", "00"), ("A1 Balanced", "20"), ("USB Audio", "16")]
)
async def test_select_source(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry, name: str, code: str
) -> None:
    await amp.front_panel(source="03")
    await wait_for(lambda: _state(hass).attributes[ATTR_INPUT_SOURCE] == "A4")
    await _call(hass, SERVICE_SELECT_SOURCE, source=name)
    assert amp.state.source == code
    assert _state(hass).attributes[ATTR_INPUT_SOURCE] == name


async def test_select_unknown_source(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, SERVICE_SELECT_SOURCE, source="MP3")  # CXA61 only
    assert not any(line.startswith(b"#3,04") for line in amp.received)


async def test_push_updates_from_remote(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    await amp.front_panel(source="04", muted=True)
    await wait_for(lambda: _state(hass).attributes.get(ATTR_INPUT_SOURCE) == "D1")
    assert _state(hass).attributes[ATTR_MEDIA_VOLUME_MUTED] is True
    await amp.front_panel(power=False)
    await wait_for(lambda: _state(hass).state == STATE_OFF)


async def test_undocumented_source_code_is_unknown(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    await amp.send_raw(b"#04,01,77\r")
    await wait_for(lambda: ATTR_INPUT_SOURCE not in _state(hass).attributes)
    assert _state(hass).state == STATE_ON


async def test_rejected_command_raises(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    await _call(hass, SERVICE_TURN_OFF)
    with pytest.raises(HomeAssistantError, match="rejected"):
        await _call(hass, SERVICE_VOLUME_MUTE, is_volume_muted=True)  # mock rejects in standby
    assert _state(hass).attributes.get(ATTR_MEDIA_VOLUME_MUTED) is not True


async def test_timeout_raises_without_false_success(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    amp.behaviour.unresponsive = True
    with pytest.raises(HomeAssistantError, match="confirm"):
        await _call(hass, SERVICE_VOLUME_MUTE, is_volume_muted=True)
    assert _state(hass).attributes[ATTR_MEDIA_VOLUME_MUTED] is False


async def test_standby_with_unknown_source_and_mute(
    hass: HomeAssistant, amp: MockAmplifier, entry: MockConfigEntry
) -> None:
    amp.state.power = False
    amp.behaviour.standby_mode = "silent"
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = _state(hass)
    assert state.state == STATE_OFF
    assert ATTR_INPUT_SOURCE not in state.attributes  # unknown, not invented
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unknown_power_shows_unknown(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    client = loaded.runtime_data
    client._set_state(power=None)
    await hass.async_block_till_done()
    assert _state(hass).state == STATE_UNKNOWN


async def test_outage_unavailable_then_recovers(
    hass: HomeAssistant, amp: MockAmplifier, loaded: MockConfigEntry
) -> None:
    port = amp.port  # type: ignore[attr-defined]
    await amp.stop()  # bridge gone: connection refused until it returns
    await wait_for(lambda: _state(hass).state == STATE_UNAVAILABLE)
    # HA itself skips unavailable entities in service calls (helpers/service.py),
    # so this is a silent no-op. The client also refuses (see test_client.py).
    await _call(hass, SERVICE_TURN_OFF)
    amp.state.source = "05"  # changed during the outage
    await amp.start("127.0.0.1", port)
    await wait_for(lambda: _state(hass).state == STATE_ON, timeout=3)
    assert _state(hass).attributes[ATTR_INPUT_SOURCE] == "D2"
    assert amp.state.power is True
    assert not any(line.startswith(b"#1,02") for line in amp.received)  # never sent or replayed
