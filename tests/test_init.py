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
    CONF_NO_CLOUD_REFRESH,
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


@pytest.fixture(autouse=True)
def no_lan_system_info():
    """Keep the startup system-info read off the network in every test."""
    with patch(
        "custom_components.allo_wt7.client.AlloWT7Client.get_system_info",
        AsyncMock(side_effect=AlloWT7ConnectionError("no LAN in tests")),
    ):
        yield


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
    assert len(hass.states.async_entity_ids("binary_sensor")) == 1

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


async def test_no_cloud_refresh_keeps_cached_oac(
    hass: HomeAssistant, mock_fetch_oac
) -> None:
    """With local-only mode on, an expired cache never re-hits the cloud."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=DATA,
        unique_id="umid1",
        options={CONF_DOORBELL_ENABLED: False, CONF_NO_CLOUD_REFRESH: True},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator._ensure_oac()  # first fetch caches the OAC
    coordinator._oac_expires_at = 0  # TTL expired: normally would refresh

    mock_fetch_oac.reset_mock()
    assert await coordinator._ensure_oac() == "o" * 64
    assert await coordinator._ensure_oac() == "o" * 64
    assert mock_fetch_oac.call_count == 0


async def test_no_cloud_refresh_still_refreshes_on_reject(
    hass: HomeAssistant, mock_fetch_oac
) -> None:
    """A forced refresh (monitor rejected the OAC) still uses the cloud."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=DATA,
        unique_id="umid1",
        options={CONF_DOORBELL_ENABLED: False, CONF_NO_CLOUD_REFRESH: True},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator._ensure_oac()

    mock_fetch_oac.reset_mock()
    mock_fetch_oac.return_value = ("n" * 64, DeviceInfo("umid1", "IDS9478AW", "Casa"))
    assert await coordinator._ensure_oac(force_refresh=True) == "n" * 64
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


async def test_system_info_updates_device_registry(
    hass: HomeAssistant, mock_fetch_oac
) -> None:
    from homeassistant.helpers import device_registry as dr

    from custom_components.allo_wt7.client import SystemInfo

    info = SystemInfo("IDS9478AW", "V9.9.9", "aa:bb", "2025-01-01")
    with patch(
        "custom_components.allo_wt7.client.AlloWT7Client.get_system_info",
        AsyncMock(return_value=info),
    ):
        entry = _entry(hass, "umid1")
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "umid1")})
    assert device.sw_version == "V9.9.9"
    assert device.model == "IDS9478AW"
    assert entry.runtime_data.system_info == info


async def test_connectivity_sensor_debounces(hass: HomeAssistant, mock_fetch_oac) -> None:
    entry = _entry(hass, "umid1")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    (entity_id,) = hass.states.async_entity_ids("binary_sensor")

    coordinator._on_lan_result(True)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"

    coordinator._on_lan_result(False)
    coordinator._on_lan_result(False)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"  # two misses are tolerated

    coordinator._on_lan_result(False)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"

    coordinator._on_lan_result(True)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, mock_fetch_oac) -> None:
    from custom_components.allo_wt7.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _entry(hass, "umid1")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data._ensure_oac()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = repr(diag)
    for secret in ("secret", "1234", "me@example.com", "o" * 64, "umid1"):
        assert secret not in text
    assert diag["oac_cached"] is True
    assert diag["entry"]["data"]["monitor_ip"] == "10.0.0.2"
