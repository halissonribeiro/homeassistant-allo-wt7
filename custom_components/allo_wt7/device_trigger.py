"""Device triggers for the Intelbras Allo wT7.

Registers a "Doorbell pressed" trigger so automations can be created
via the HA UI (Settings → Automations → Add Trigger → Device → Allo wT7).
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo

from .const import DOMAIN, EVENT_DOORBELL_RING

TRIGGER_TYPE_DOORBELL = "doorbell_ring"

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required("type"): TRIGGER_TYPE_DOORBELL,
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict]:
    """Return the list of triggers available for the wT7 device."""
    return [
        {
            "platform": "device",
            "domain": DOMAIN,
            "device_id": device_id,
            "type": TRIGGER_TYPE_DOORBELL,
            "metadata": {"secondary": False},
        }
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: dict,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach the device trigger to the HA event bus.

    Matches only rings from the config entry that owns this device, so with
    several wT7 monitors each device trigger fires for its own doorbell only.
    """
    event = {"platform": "event", "event_type": EVENT_DOORBELL_RING}
    device = dr.async_get(hass).async_get(config["device_id"])
    if device is not None:
        entry_ids = [
            entry_id
            for entry_id in device.config_entries
            if (entry := hass.config_entries.async_get_entry(entry_id))
            and entry.domain == DOMAIN
        ]
        if entry_ids:
            event["event_data"] = {"entry_id": entry_ids[0]}
    event_config = event_trigger.TRIGGER_SCHEMA(event)
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: dict
) -> dict:
    """Return extra capabilities (none needed for a simple trigger)."""
    return {}
