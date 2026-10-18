"""Setup, service and doorbell tests against a real Home Assistant core."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.allo_wt7.client import (
    AlloWT7ConnectionError,
    AlloWT7RateLimitError,
    DeviceInfo,
)
from custom_components.allo_wt7.const import (
    CONF_DOORBELL_ENABLED,
    DOMAIN,
    EVENT_DOORBELL_RING,
)

DATA = {
    "email": "me@example.com",
    "password": "secret",
    "monitor_ip": "10.0.0.2",
    "require_pin": True,
    "unlock_pin": "1234",
    "door1_name": "Porta social",
    "door2_enabled": True,
    "door2_name": "Portão",
}


def _entry(hass: HomeAssistant, umid: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=DATA,
        unique_id=umid,
        options={CONF_DOORBELL_ENABLED: False},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_fetch_oac():
    with patch(
        "custom_components.allo_wt7.client.AlloWT7Client.fetch_oac",
        AsyncMock(return_value=("o" * 64, DeviceInfo("umid1", "IDS9478AW", "Casa"))),
    ) as mock:
        yield mock


async def test_setup_creates_entities(hass: HomeAssistant, mock_fetch_oac) -> None:
    entry = _entry(hass, "umid1")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "open_door")
    assert len(hass.states.async_entity_ids("button")) == 2
    assert len(hass.states.async_entity_ids("event")) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_service_opens_door(hass: HomeAssistant, mock_fetch_oac) -> None:
    entry = _entry(hass, "umid1")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with patch(
        "custom_components.allo_wt7.client.AlloWT7Client.open_door", AsyncMock()
    ) as open_door:
        await hass.services.async_call(
            DOMAIN, "open_door", {"lock_number": 2}, blocking=True
        )
    assert open_door.call_args.kwargs["lock_number"] == 2
    assert open_door.call_args.kwargs["unlock_pin"] == "1234"


async def test_rate_limit_is_a_clean_error(hass: HomeAssistant, mock_fetch_oac) -> None:
    entry = _entry(hass, "umid1")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with patch(
        "custom_components.allo_wt7.client.AlloWT7Client.open_door",
        AsyncMock(side_effect=AlloWT7RateLimitError("too fast")),
    ):
        with pytest.raises(HomeAssistantError, match="rate limit"):
            await entry.runtime_data.async_open_door(1)


async def test_stale_oac_used_when_cloud_down(
    hass: HomeAssistant, mock_fetch_oac
) -> None:
    entry = _entry(hass, "umid1")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator._ensure_oac()  # first fetch caches the OAC
    coordinator._oac_expires_at = 0  # expire it

    mock_fetch_oac.side_effect = AlloWT7ConnectionError("offline")
    mock_fetch_oac.reset_mock()
    assert await coordinator._ensure_oac() == "o" * 64
    # The fallback backs off: the next call does not hit the cloud again.
    assert await coordinator._ensure_oac() == "o" * 64
    assert mock_fetch_oac.call_count == 1


async def test_ring_only_hits_own_event_entity(
    hass: HomeAssistant, mock_fetch_oac
) -> None:
    e1 = _entry(hass, "umid1")
    e2 = _entry(hass, "umid2")
    # Setting up the integration loads every entry of the domain.
    await hass.config_entries.async_setup(e1.entry_id)
    await hass.async_block_till_done()
    assert e2.state is ConfigEntryState.LOADED

    events = sorted(hass.states.async_entity_ids("event"))
    assert len(events) == 2
    before = {eid: hass.states.get(eid).state for eid in events}

    hass.bus.async_fire(
        EVENT_DOORBELL_RING,
        {"entry_id": e1.entry_id, "filename": "x.jpg", "starttime": "t"},
    )
    await hass.async_block_till_done()

    changed = [eid for eid in events if hass.states.get(eid).state != before[eid]]
    assert len(changed) == 1


async def test_device_trigger_filters_by_device(
    hass: HomeAssistant, mock_fetch_oac
) -> None:
    from homeassistant.helpers import device_registry as dr

    from custom_components.allo_wt7.device_trigger import async_attach_trigger

    e1 = _entry(hass, "umid1")
    e2 = _entry(hass, "umid2")
    await hass.config_entries.async_setup(e1.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "umid1")})
    calls = []

    async def _action(run_variables, context=None):
        calls.append(run_variables)

    unsub = await async_attach_trigger(
        hass,
        {"platform": "device", "domain": DOMAIN, "device_id": device.id,
         "type": "doorbell_ring"},
        _action,
        {"trigger_data": {}, "variables": {}, "name": "t", "home_assistant_start": False},
    )
    hass.bus.async_fire(EVENT_DOORBELL_RING, {"entry_id": e2.entry_id})
    await hass.async_block_till_done()
    assert calls == []
    hass.bus.async_fire(EVENT_DOORBELL_RING, {"entry_id": e1.entry_id})
    await hass.async_block_till_done()
    assert len(calls) == 1
    unsub()
