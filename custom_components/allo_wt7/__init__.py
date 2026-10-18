"""The Intelbras Allo wT7 integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_LOCK_NUMBER, DOMAIN, PLATFORMS, SERVICE_OPEN_DOOR
from .coordinator import AlloWT7Coordinator

_LOGGER = logging.getLogger(__name__)

type AlloWT7ConfigEntry = ConfigEntry[AlloWT7Coordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_OPEN_DOOR_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional(ATTR_LOCK_NUMBER, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=4)
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the open_door service once for the whole integration."""

    async def _handle_open_door(call: ServiceCall) -> None:
        entries = {
            e.entry_id: e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        }
        target_entry_id = call.data.get("entry_id")
        if target_entry_id:
            entry = entries.get(target_entry_id)
            if entry is None:
                raise HomeAssistantError(
                    f"Allo wT7: entry_id {target_entry_id!r} not found or not loaded"
                )
        else:
            if len(entries) != 1:
                raise HomeAssistantError(
                    "Allo wT7: multiple wT7 configured — pass entry_id"
                    if entries
                    else "Allo wT7: no wT7 loaded"
                )
            entry = next(iter(entries.values()))
        await entry.runtime_data.async_open_door(call.data[ATTR_LOCK_NUMBER])

    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_DOOR, _handle_open_door, schema=SERVICE_OPEN_DOOR_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AlloWT7ConfigEntry) -> bool:
    """Set up Allo wT7 from a config entry."""
    coordinator = AlloWT7Coordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.async_stop_doorbell_polling)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlloWT7ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
