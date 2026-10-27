"""The INWX integration."""

import aiohttp
from aioinwx import InwxClient
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import CONF_SHARED_SECRET, DOMAIN
from .coordinator import InwxConfigEntry, InwxCoordinator, balance_issue_id
from .entity import account_device_info

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: InwxConfigEntry) -> bool:
    """Set up INWX from a config entry."""
    # Own cookie jar per entry, the API session is kept in a cookie.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    client = InwxClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_SHARED_SECRET),
        session=session,
    )
    coordinator = InwxCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # The domain devices link to the account device, so it must exist first.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **account_device_info(entry)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: InwxConfigEntry) -> bool:
    """Unload a config entry."""
    ir.async_delete_issue(hass, DOMAIN, balance_issue_id(entry))
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
