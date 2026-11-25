"""Cambridge Audio CXA amplifiers over a local TCP-to-RS232 bridge."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import CXAClient, CXAConnectError, CXAError, CXARejectedError, CXATimeoutError
from .const import CONF_MODEL, DOMAIN
from .protocol import Model

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]

type CXAConfigEntry = ConfigEntry[CXAClient]


async def async_setup_entry(hass: HomeAssistant, entry: CXAConfigEntry) -> bool:
    """Connect to the amplifier and set up its entity.

    The first connection only reads state. If it fails, Home Assistant retries
    setup later; nothing is left running in between.
    """
    client = CXAClient(
        entry.data[CONF_HOST], entry.data[CONF_PORT], model=Model(entry.data[CONF_MODEL])
    )
    try:
        await client.start()
    except CXAConnectError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from err
    except (CXATimeoutError, CXARejectedError) as err:
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="no_response") from err
    except CXAError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = client

    async def _stop(_: Event) -> None:
        await client.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CXAConfigEntry) -> bool:
    """Unload the entity and close the connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded
