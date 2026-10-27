"""Diagnostics support for the INWX integration."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_SHARED_SECRET
from .coordinator import InwxConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_SHARED_SECRET, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: InwxConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data.data
    return {
        "entry_data": async_redact_data(entry.data, TO_REDACT),
        "entry_options": dict(entry.options),
        "balance": asdict(data.balance),
        "domains": [asdict(domain) for domain in data.domains.values()],
        "prices": {str(ro_id): asdict(price) for ro_id, price in data.prices.items()},
    }
