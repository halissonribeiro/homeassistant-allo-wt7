"""Button entities for the Intelbras Allo wT7.

The wT7 controls relays that pulse open (or trigger gate-motor commands).
There is no sensor to report door state, so we expose each output as a
stateless `button` — pressing it fires one pulse. Honest to the hardware.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DOOR1_NAME,
    CONF_DOOR2_ENABLED,
    CONF_DOOR2_NAME,
    DEFAULT_DOOR1_NAME,
    DEFAULT_DOOR2_NAME,
)
from .coordinator import AlloWT7Coordinator
from .entity import AlloWT7Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AlloWT7Coordinator = entry.runtime_data

    door1_name = entry.data.get(CONF_DOOR1_NAME, DEFAULT_DOOR1_NAME)
    entities: list[AlloWT7DoorButton] = [
        AlloWT7DoorButton(coordinator, entry, lock_number=1, name=door1_name)
    ]
    if entry.data.get(CONF_DOOR2_ENABLED, True):
        door2_name = entry.data.get(CONF_DOOR2_NAME, DEFAULT_DOOR2_NAME)
        entities.append(
            AlloWT7DoorButton(coordinator, entry, lock_number=2, name=door2_name)
        )
    async_add_entities(entities)


class AlloWT7DoorButton(AlloWT7Entity, ButtonEntity):
    """A button that fires one open-door pulse on the wT7.

    No state — the wT7 does not report whether the relay/gate is currently
    triggered. The garage gate's motor is typically a toggle (open ↔ close);
    the side door's lock is a momentary unlock (auto-closes by spring).
    Either way, the user perception is "I pressed a button."
    """

    def __init__(
        self,
        coordinator: AlloWT7Coordinator,
        entry: ConfigEntry,
        *,
        lock_number: int,
        name: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._lock_number = lock_number
        self._attr_name = name
        self._attr_unique_id = f"{self._device_key}_button_{lock_number}"
        # Icon hint (purely cosmetic)
        if lock_number == 1:
            self._attr_icon = "mdi:door-open"
        else:
            self._attr_icon = "mdi:garage-open-variant"

    async def async_press(self) -> None:
        """Fire one open-door pulse."""
        _LOGGER.debug("Pressing button for lock_number=%d", self._lock_number)
        await self._coordinator.async_open_door(self._lock_number)
