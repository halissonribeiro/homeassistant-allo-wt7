"""Base entity shared by the Allo wT7 platforms."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import AlloWT7Coordinator


class AlloWT7Entity(Entity):
    """Ties every entity of one config entry to the same wT7 device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AlloWT7Coordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._device_key = entry.unique_id or entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._coordinator.device_info
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_key)},
            manufacturer=MANUFACTURER,
            model=(dev.model or MODEL) if dev else MODEL,
            name=(dev.name if dev else "Allo wT7"),
            serial_number=(dev.umid if dev else None),
        )
