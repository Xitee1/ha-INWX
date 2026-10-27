"""Tests for the INWX sensors and the renewal forecast."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from aioinwx import InwxBalance, InwxConnectionError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.inwx.const import (
    CONF_BALANCE_ISSUE,
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_VAT,
    DOMAIN,
    SCAN_INTERVAL,
)
from custom_components.inwx.coordinator import (
    InwxData,
    add_period,
    calculate_renewal_costs,
    next_renewal,
)

from .conftest import CUSTOMER_ID, DOMAINS, NOW, PRICE_DE, PRICES, make_domain

BALANCE = "sensor.inwx_testuser_available_balance"
RENEWAL_COSTS = "sensor.inwx_testuser_renewal_costs_in_forecast_period"
NEXT_RENEWAL = "sensor.inwx_testuser_next_renewal"


def balance_issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    """Return the repair issue for an insufficient balance."""
    return ir.async_get(hass).async_get_issue(DOMAIN, f"balance_insufficient_{entry.entry_id}")


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze the time at NOW."""
    freezer.move_to(NOW)
    return freezer


async def test_account_sensors(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the sensors of the account."""
    await setup_entry(hass, mock_config_entry)

    balance = hass.states.get(BALANCE)
    assert balance.state == "5.0"
    assert balance.attributes["unit_of_measurement"] == "EUR"
    assert hass.states.get(RENEWAL_COSTS).state == "9.52"
    assert hass.states.get(NEXT_RENEWAL).state == (NOW + timedelta(days=25)).isoformat()


async def test_balance_issue(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the repair issue when the balance does not cover the renewals."""
    await setup_entry(hass, mock_config_entry)

    issue = balance_issue(hass, mock_config_entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert issue.translation_key == "balance_insufficient"
    assert issue.translation_placeholders == {
        "account": "testuser",
        "balance": "5.00",
        "costs": "9.52",
        "currency": "EUR",
        "days": "30",
    }

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert balance_issue(hass, mock_config_entry) is None


async def test_balance_issue_deleted_after_top_up(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test that the repair issue is deleted when the balance covers the renewals."""
    await setup_entry(hass, mock_config_entry)
    assert balance_issue(hass, mock_config_entry) is not None

    mock_client.get_balance.return_value = InwxBalance(available=9.52, locked=0.0, credit_limit=0.0)
    frozen_time.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert balance_issue(hass, mock_config_entry) is None


async def test_balance_issue_disabled(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the option turns the repair issue off."""
    await setup_entry(hass, mock_config_entry)
    assert balance_issue(hass, mock_config_entry) is not None

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FORECAST_DAYS: 30, CONF_INCLUDE_VAT: True, CONF_BALANCE_ISSUE: False},
    )
    await hass.async_block_till_done()

    assert balance_issue(hass, mock_config_entry) is None


async def test_domain_sensors(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the sensors of a domain."""
    await setup_entry(hass, mock_config_entry)

    renewal_date = NOW + timedelta(days=25)
    assert hass.states.get("sensor.example_de_renewal_date").state == renewal_date.isoformat()
    assert (
        hass.states.get("sensor.example_de_expiration_date").state
        == (renewal_date + timedelta(days=5)).isoformat()
    )
    assert hass.states.get("sensor.example_de_renewal_price").state == "4.76"
    assert hass.states.get("sensor.example_de_renewal_mode").state == "autorenew"
    assert hass.states.get("sensor.deleted_de_renewal_mode").state == "autodelete"
    assert hass.states.get("sensor.example_de_status").state == "OK"
    nameservers = hass.states.get("sensor.example_de_nameservers")
    assert nameservers.state == "2"
    assert nameservers.attributes["nameservers"] == ["ns.example.com", "ns2.example.com"]
    assert hass.states.get("sensor.later_com_nameservers").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.example_de_transfer_lock").state == STATE_OFF
    assert hass.states.get("binary_sensor.later_com_transfer_lock").state == STATE_ON

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{CUSTOMER_ID}_1"), mock_config_entry.entry_id
    )
    assert device.name == "example.de"
    assert device.via_device_id is not None


async def test_options_change_forecast(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the options change the forecast."""
    await setup_entry(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FORECAST_DAYS: 100, CONF_INCLUDE_VAT: False, CONF_BALANCE_ISSUE: True},
    )
    await hass.async_block_till_done()

    assert hass.states.get(RENEWAL_COSTS).state == "18.0"
    assert hass.states.get("sensor.example_de_renewal_price").state == "4.0"
    assert balance_issue(hass, mock_config_entry).translation_placeholders["days"] == "100"


async def test_domains_added_and_removed(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test that new domains get entities and removed domains lose their device."""
    await setup_entry(hass, mock_config_entry)
    device_registry = dr.async_get(hass)
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{CUSTOMER_ID}_2"), mock_config_entry.entry_id
    )

    mock_client.get_domains.return_value = [domain for domain in DOMAINS if domain.ro_id != 2] + [
        make_domain(5, "new.de", 3)
    ]
    mock_client.get_renewal_price.side_effect = lambda domain: {**PRICES, 5: PRICE_DE}[domain.ro_id]
    frozen_time.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.new_de_renewal_date") is not None
    assert hass.states.get("binary_sensor.new_de_transfer_lock") is not None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{CUSTOMER_ID}_2"), mock_config_entry.entry_id
        )
        is None
    )
    assert er.async_get(hass).async_get("sensor.other_de_renewal_date") is None
    assert hass.states.get(RENEWAL_COSTS).state == "9.52"


async def test_entities_unavailable_after_failed_update(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test that the entities become unavailable when the update fails."""
    await setup_entry(hass, mock_config_entry)

    mock_client.login.side_effect = InwxConnectionError("down")
    frozen_time.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(BALANCE).state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.example_de_renewal_date").state == STATE_UNAVAILABLE


def make_data(*domains, available: float = 0.0) -> InwxData:
    """Return coordinator data with the given domains."""
    return InwxData(
        balance=InwxBalance(available=available, locked=0.0, credit_limit=0.0),
        domains={domain.ro_id: domain for domain in domains},
        prices={domain.ro_id: PRICE_DE for domain in domains},
    )


def test_renewal_costs_count_each_period() -> None:
    """Test that monthly renewals are counted once per month in the forecast."""
    data = make_data(make_domain(1, "monthly.de", 5, period="1M"))

    assert calculate_renewal_costs(data, NOW, 30, True) == 4.76
    assert calculate_renewal_costs(data, NOW, 70, True) == 14.28


def test_renewal_costs_include_overdue_renewal() -> None:
    """Test that a renewal date in the past is still counted."""
    data = make_data(make_domain(1, "overdue.de", -2))

    assert calculate_renewal_costs(data, NOW, 30, False) == 4.0


def test_renewal_costs_unknown_period() -> None:
    """Test that a domain with unknown period is counted once."""
    data = make_data(make_domain(1, "odd.de", 1, period="X"))

    assert calculate_renewal_costs(data, NOW, 365, True) == 4.76


def test_next_renewal_without_autorenew() -> None:
    """Test the next renewal when no domain renews automatically."""
    data = make_data(make_domain(1, "gone.de", 1, renewal_mode="AUTOEXPIRE"))

    assert next_renewal(data) is None
    assert calculate_renewal_costs(data, NOW, 30, True) == 0.0


@pytest.mark.parametrize(
    ("value", "period", "expected"),
    [
        (datetime(2027, 1, 31), "1M", datetime(2027, 2, 28)),
        (datetime(2028, 1, 31), "1M", datetime(2028, 2, 29)),
        (datetime(2026, 11, 20), "1Y", datetime(2027, 11, 20)),
        (datetime(2026, 11, 20), "2Y", datetime(2028, 11, 20)),
        (datetime(2026, 11, 20), None, None),
        (datetime(2026, 11, 20), "Y", None),
        (datetime(2026, 11, 20), "1D", None),
    ],
)
def test_add_period(value: datetime, period: str | None, expected: datetime | None) -> None:
    """Test adding a renewal period."""
    assert add_period(value, period) == expected
