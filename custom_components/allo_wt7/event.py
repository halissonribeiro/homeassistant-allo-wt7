"""Event entity for the Intelbras Allo wT7 doorbell.

The wT7 saves one JPEG snapshot to its internal flash every time someone
presses the door bell.  The coordinator polls for new pictures every 2 s
(adaptive) and fires ``allo_wt7_doorbell_ring`` on the HA bus when a new
picture is detected.  The bus event carries the config entry id, so with
several monitors each entity only reacts to its own device.  This ``EventEntity`` listens to that bus event and
translates it into a proper HA event entity (available since HA 2023.8).

Usage examples:
  - Automation trigger: ``event_type: ring`` on this entity.
  - Logbook: shows "Doorbell ring detected" with timestamp.
  - Notifications via standard HA automations.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVENT_DOORBELL_RING
from .coordinator import AlloWT7Coordinator
from .entity import AlloWT7Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the doorbell event entity."""
    coordinator: AlloWT7Coordinator = entry.runtime_data
    async_add_entities([AlloWT7DoorbellEvent(coordinator, entry)])


class AlloWT7DoorbellEvent(AlloWT7Entity, EventEntity):
    """Fires an event whenever the wT7 doorbell is pressed.

    State is the last event type fired (``ring``).  The entity itself has no
    meaningful on/off state — it's a momentary event.
    """

    _attr_name = "Campainha"
    _attr_icon = "mdi:doorbell"
    _attr_event_types = ["ring"]

    def __init__(
        self,
        coordinator: AlloWT7Coordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._device_key}_doorbell"

    async def async_added_to_hass(self) -> None:
        """Subscribe to doorbell ring events when entity is registered."""
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_DOORBELL_RING,
                self._handle_ring_event,
                event_filter=self._is_own_ring,
            )
        )

    @callback
    def _is_own_ring(self, event_data: Mapping[str, Any]) -> bool:
        """Only react to rings from this entry's monitor."""
        return event_data.get("entry_id") == self._entry.entry_id

    @callback
    def _handle_ring_event(self, event: Event) -> None:
        """Handle the bus event and forward it as an HA event entity update."""
        _LOGGER.debug("Doorbell event entity received ring: %s", event.data)
        self._trigger_event("ring", event.data)
        self.async_write_ha_state()
