"""Shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from tools.mock_amplifier import MockAmplifier

HOST = "127.0.0.1"  # the HA test plugin only allows sockets to this address


@pytest.fixture
async def amp() -> AsyncIterator[MockAmplifier]:
    """A running mock amplifier on an ephemeral loopback port."""
    mock = MockAmplifier()
    mock.port = await mock.start(HOST, 0)  # type: ignore[attr-defined]
    yield mock
    await mock.stop()


async def wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until predicate() is true, failing the test on timeout."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)
