"""Shared fixtures."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator, Callable

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cambridge_cxa_home.client import CXAClient
from custom_components.cambridge_cxa_home.const import CONF_MODEL, DOMAIN
from tools.mock_amplifier import MockAmplifier

HOST = "127.0.0.1"  # the HA test plugin only allows sockets to this address
ENTITY_ID = "media_player.cambridge_audio_cxa81"
UNIQUE_ID = "0123456789abcdef0123456789abcdef"
# Request prefixes that change amplifier state (unpadded, the default format).
WRITE_PREFIXES = (b"#1,02", b"#1,04", b"#3,02", b"#3,03", b"#3,04")

FAST_CLIENT = functools.partial(
    CXAClient,
    connect_timeout=1.0,
    request_timeout=0.3,
    power_timeout=0.5,
    backoff_initial=0.02,
    backoff_max=0.1,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load integrations from custom_components/."""


@pytest.fixture
async def amp() -> AsyncIterator[MockAmplifier]:
    """A running mock amplifier on an ephemeral loopback port."""
    mock = MockAmplifier()
    mock.port = await mock.start(HOST, 0)  # type: ignore[attr-defined]
    yield mock
    await mock.stop()


@pytest.fixture
def fast_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the integration build clients with short timeouts and backoff."""
    monkeypatch.setattr("custom_components.cambridge_cxa_home.CXAClient", FAST_CLIENT)


@pytest.fixture
def entry(amp: MockAmplifier) -> MockConfigEntry:
    """A config entry pointing at the mock amplifier."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Cambridge Audio CXA81",
        unique_id=UNIQUE_ID,
        data={"host": HOST, "port": amp.port, CONF_MODEL: "CXA81"},  # type: ignore[attr-defined]
    )


async def wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until predicate() is true, failing the test on timeout."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)
