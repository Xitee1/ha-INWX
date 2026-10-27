"""Fixtures for the INWX tests."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aioinwx import InwxAccount, InwxBalance, InwxDomain, InwxPrice
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.inwx.const import (
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_VAT,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_INCLUDE_VAT,
    DOMAIN,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
USERNAME = "testuser"
PASSWORD = "test-password"
CUSTOMER_ID = 12345

PRICE_DE = InwxPrice(net=4.0, gross=4.76, currency="EUR")
PRICE_COM = InwxPrice(net=10.0, gross=11.9, currency="EUR")


def make_domain(
    ro_id: int,
    name: str,
    renewal_in_days: int,
    renewal_mode: str = "AUTORENEW",
    period: str = "1Y",
) -> InwxDomain:
    """Return a domain that renews in the given number of days."""
    renewal_date = NOW + timedelta(days=renewal_in_days)
    return InwxDomain(
        ro_id=ro_id,
        name=name,
        name_ace=name,
        status="OK",
        renewal_mode=renewal_mode,
        period=period,
        renewal_date=renewal_date,
        expiration_date=renewal_date + timedelta(days=5),
    )


DOMAINS = [
    make_domain(1, "example.de", 25),
    make_domain(2, "other.de", 29),
    make_domain(3, "later.com", 90),
    make_domain(4, "deleted.de", 10, renewal_mode="AUTODELETE"),
]
PRICES = {1: PRICE_DE, 2: PRICE_DE, 3: PRICE_COM, 4: PRICE_DE}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the setup of the config entry."""
    with patch("custom_components.inwx.async_setup_entry", return_value=True) as mock:
        yield mock


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Return a mocked INWX client."""
    with (
        patch("custom_components.inwx.InwxClient", autospec=True) as mock_class,
        patch("custom_components.inwx.config_flow.InwxClient", new=mock_class),
    ):
        client = mock_class.return_value
        client.login.return_value = InwxAccount(customer_id=CUSTOMER_ID, customer_no=1)
        client.get_balance.return_value = InwxBalance(available=5.0, locked=0.0, credit_limit=0.0)
        client.get_domains.return_value = list(DOMAINS)
        client.get_renewal_price.side_effect = lambda domain: PRICES[domain.ro_id]
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry of the INWX integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=str(CUSTOMER_ID),
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={
            CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
            CONF_INCLUDE_VAT: DEFAULT_INCLUDE_VAT,
        },
    )
