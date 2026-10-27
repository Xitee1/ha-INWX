"""Tests for the INWX config flow."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.inwx.api import (
    InwxAccount,
    InwxApiError,
    InwxAuthError,
    InwxConnectionError,
    InwxInvalidSharedSecretError,
    InwxTwoFactorError,
    InwxTwoFactorRequiredError,
)
from custom_components.inwx.const import (
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_VAT,
    CONF_SHARED_SECRET,
    DOMAIN,
)

from .conftest import CUSTOMER_ID, PASSWORD, USERNAME

USER_INPUT = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """Test the full user flow."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_SHARED_SECRET: "jbsw y3dp ehpk 3pxp"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == USERNAME
    assert result["data"] == {**USER_INPUT, CONF_SHARED_SECRET: "JBSWY3DPEHPK3PXP"}
    assert result["options"] == {CONF_FORECAST_DAYS: 30, CONF_INCLUDE_VAT: True}
    assert result["result"].unique_id == str(CUSTOMER_ID)
    mock_client.logout.assert_awaited_once()


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("error", "errors"),
    [
        (InwxTwoFactorRequiredError("2FA"), {"base": "tfa_required"}),
        (InwxTwoFactorError("2FA"), {"base": "invalid_tfa"}),
        (InwxInvalidSharedSecretError("Base32"), {CONF_SHARED_SECRET: "invalid_shared_secret"}),
        (InwxAuthError("Auth"), {"base": "invalid_auth"}),
        (InwxConnectionError("down"), {"base": "cannot_connect"}),
        (InwxApiError(2400, "Command failed"), {"base": "unknown"}),
        (RuntimeError("boom"), {"base": "unknown"}),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    error: Exception,
    errors: dict[str, str],
) -> None:
    """Test errors in the user flow and the recovery."""
    mock_client.login.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors

    mock_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that an account can only be added once."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_flow(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the reauth flow."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password", CONF_SHARED_SECRET: "JBSWY3DPEHPK3PXP"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: "new-password",
        CONF_SHARED_SECRET: "JBSWY3DPEHPK3PXP",
    }


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_flow_error_and_mismatch(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the reauth flow with wrong credentials and another account."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_client.login.side_effect = InwxAuthError("Auth")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.login.side_effect = None
    mock_client.login.return_value = InwxAccount(customer_id=999, customer_no=2)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "other"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert mock_config_entry.data[CONF_PASSWORD] == PASSWORD


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_flow(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the reconfigure flow."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "renamed", CONF_PASSWORD: "new-password"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.title == "renamed"
    assert mock_config_entry.data == {CONF_USERNAME: "renamed", CONF_PASSWORD: "new-password"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_flow_other_account(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the reconfigure flow rejects another account."""
    mock_config_entry.add_to_hass(hass)
    mock_client.login.return_value = InwxAccount(customer_id=999, customer_no=2)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


async def test_options_flow(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test the options flow."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FORECAST_DAYS: 60.0, CONF_INCLUDE_VAT: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_FORECAST_DAYS: 60, CONF_INCLUDE_VAT: False}
