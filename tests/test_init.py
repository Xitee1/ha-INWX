"""Tests for the setup of the INWX integration."""

from unittest.mock import MagicMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.inwx.api import (
    InwxApiError,
    InwxAuthError,
    InwxConnectionError,
    InwxError,
)
from custom_components.inwx.const import DOMAIN
from custom_components.inwx.diagnostics import async_get_config_entry_diagnostics


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test setup and unload of a config entry."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_client.login.assert_awaited_once()
    mock_client.logout.assert_awaited_once()

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (InwxConnectionError("down"), ConfigEntryState.SETUP_RETRY),
        (InwxApiError(2400, "Command failed"), ConfigEntryState.SETUP_RETRY),
        (InwxAuthError("Authentication error"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    error: Exception,
    state: ConfigEntryState,
) -> None:
    """Test errors during setup."""
    mock_client.login.side_effect = error
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is state


async def test_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that rejected credentials start a reauth flow."""
    mock_client.login.side_effect = InwxAuthError("Authentication error")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["handler"] == DOMAIN
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_logout_after_failed_request(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the session is closed when a request fails."""
    mock_client.get_domains.side_effect = InwxConnectionError("down")
    mock_client.logout.side_effect = InwxError("logout failed")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_client.logout.assert_awaited_once()


async def test_diagnostics(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that diagnostics hide the credentials."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry_data"] == {"username": "**REDACTED**", "password": "**REDACTED**"}
    assert diagnostics["balance"]["available"] == 5.0
    assert len(diagnostics["domains"]) == 4
    assert diagnostics["prices"]["1"]["gross"] == 4.76
