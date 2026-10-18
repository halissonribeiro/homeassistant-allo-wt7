"""Connectivity sensor for the Intelbras Allo wT7.

Reports whether the monitor answers on the LAN, as seen by the integration's
own traffic (doorbell polls, door presses, system-info reads). No extra
requests are made for it. With doorbell detection disabled the state only
changes when one of those other calls runs.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlloWT7Coordinator
from .entity import AlloWT7Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    async_add_entities([AlloWT7ConnectivitySensor(entry.runtime_data, entry)])


class AlloWT7ConnectivitySensor(AlloWT7Entity, BinarySensorEntity):
    """On while the monitor answers on the LAN."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "lan_connectivity"

    def __init__(self, coordinator: AlloWT7Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._device_key}_lan_connectivity"

    @property
    def is_on(self) -> bool | None:
        return self._coordinator.lan_reachable

    @property
    def extra_state_attributes(self) -> dict[str, str | None] | None:
        info = self._coordinator.system_info
        if info is None:
            return None
        return {"firmware_version": info.version, "release_date": info.release_date}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._coordinator.signal_update, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
