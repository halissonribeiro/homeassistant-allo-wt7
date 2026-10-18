"""Diagnostics for the Intelbras Allo wT7 (Settings → Devices → Download diagnostics).

Everything that authenticates against the cloud or the monitor is redacted,
so the file can be attached to a GitHub issue as is.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_PASSWORD, CONF_UNLOCK_PIN

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_UNLOCK_PIN, "umid", "mac", "oac"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for one config entry."""
    coordinator = entry.runtime_data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "cloud_device": (
                asdict(coordinator.device_info) if coordinator.device_info else None
            ),
            "system_info": (
                asdict(coordinator.system_info) if coordinator.system_info else None
            ),
            "lan_reachable": coordinator.lan_reachable,
            "oac_cached": coordinator.has_cached_oac,
            "doorbell_polling": coordinator.doorbell_polling_running,
        },
        TO_REDACT,
    )
