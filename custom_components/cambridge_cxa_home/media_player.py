"""Media player entity for a CXA amplifier.

Exposes only what the serial protocol documents: power, mute, source.
No volume and no playback controls, because the protocol defines neither.
"""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CXAConfigEntry
from .client import (
    AmplifierState,
    CXAClient,
    CXAError,
    CXANotConfirmedError,
    CXANotConnectedError,
    CXARejectedError,
    CXATimeoutError,
)
from .const import DOMAIN, MANUFACTURER

# Commands are serialized in the client anyway; don't let HA fan them out.
PARALLEL_UPDATES = 1

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CXAConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the amplifier entity."""
    async_add_entities([CXAMediaPlayer(entry)])


class CXAMediaPlayer(MediaPlayerEntity):
    """The amplifier. All state comes from the amplifier's own replies."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, entry: CXAConfigEntry) -> None:
        self._client: CXAClient = entry.runtime_data
        assert entry.unique_id is not None
        self._attr_unique_id = entry.unique_id
        self._sources = self._client.sources  # code -> name
        self._codes = {name: code for code, name in self._sources.items()}
        self._attr_source_list = list(self._sources.values())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=self._client.model.value,
            sw_version=self._client.state.firmware_version,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to pushed state changes."""
        self.async_on_remove(self._client.add_listener(self._on_state))

    @callback
    def _on_state(self, state: AmplifierState) -> None:
        self._update_firmware(state.firmware_version)
        self.async_write_ha_state()

    def _update_firmware(self, firmware: str | None) -> None:
        if not firmware or self.device_entry is None or self.device_entry.sw_version == firmware:
            return
        dr.async_get(self.hass).async_update_device(self.device_entry.id, sw_version=firmware)

    # -- state --

    @property
    def available(self) -> bool:
        """Unavailable means no synced connection; standby is shown as off."""
        return self._client.state.available

    @property
    def state(self) -> MediaPlayerState | None:
        """On, off (standby), or unknown."""
        power = self._client.state.power
        if power is None:
            return None
        return MediaPlayerState.ON if power else MediaPlayerState.OFF

    @property
    def is_volume_muted(self) -> bool | None:
        """Mute state as last reported, or unknown."""
        return self._client.state.muted

    @property
    def source(self) -> str | None:
        """Current source name. Undocumented codes are reported as unknown."""
        code = self._client.state.source
        return self._sources.get(code) if code is not None else None

    # -- commands --

    async def async_turn_on(self) -> None:
        """Wake from standby."""
        await self._run(self._client.async_set_power(True))

    async def async_turn_off(self) -> None:
        """Go to standby."""
        await self._run(self._client.async_set_power(False))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self._run(self._client.async_set_mute(mute))

    async def async_select_source(self, source: str) -> None:
        """Select a source by its display name."""
        code = self._codes.get(source)
        if code is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_source",
                translation_placeholders={"source": source},
            )
        await self._run(self._client.async_set_source(code))

    async def _run(self, command: Awaitable[None]) -> None:
        """Turn client errors into user-facing HA errors. Never report false success."""
        try:
            await command
        except CXANotConnectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            ) from err
        except CXATimeoutError as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="timeout") from err
        except CXARejectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="rejected",
                translation_placeholders={"reason": err.error.description},
            ) from err
        except CXANotConfirmedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_confirmed"
            ) from err
        except CXAError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
