"""DataUpdateCoordinator for the INWX integration."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import override

from aioinwx import (
    InwxApiError,
    InwxAuthError,
    InwxBalance,
    InwxClient,
    InwxConnectionError,
    InwxDomain,
    InwxError,
    InwxPrice,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_VAT,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_INCLUDE_VAT,
    DOMAIN,
    LOGGER,
    RENEWAL_MODE_AUTORENEW,
    SCAN_INTERVAL,
)

type InwxConfigEntry = ConfigEntry[InwxCoordinator]


@dataclass(frozen=True, slots=True)
class InwxData:
    """Data of an INWX account."""

    balance: InwxBalance
    domains: dict[int, InwxDomain]
    prices: dict[int, InwxPrice]

    @property
    def currency(self) -> str:
        """Return the currency of the account."""
        return next((price.currency for price in self.prices.values()), "EUR")


def add_period(value: datetime, period: str | None) -> datetime | None:
    """Return the date one renewal period later, or None for an unknown period."""
    if not period or len(period) < 2 or not period[:-1].isdigit():
        return None
    amount = int(period[:-1])
    match period[-1]:
        case "Y":
            months = amount * 12
        case "M":
            months = amount
        case _:
            return None
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = value.day
    while True:
        try:
            return value.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def renewal_price(price: InwxPrice, include_vat: bool) -> float:
    """Return the renewal price with or without VAT."""
    return price.gross if include_vat else price.net


def calculate_renewal_costs(
    data: InwxData, now: datetime, forecast_days: int, include_vat: bool
) -> float:
    """Return the costs of all automatic renewals until the end of the forecast."""
    end = now + timedelta(days=forecast_days)
    costs = 0.0
    for ro_id, domain in data.domains.items():
        if domain.renewal_mode != RENEWAL_MODE_AUTORENEW or domain.renewal_date is None:
            continue
        price = renewal_price(data.prices[ro_id], include_vat)
        renewal: datetime | None = domain.renewal_date
        while renewal is not None and renewal <= end:
            costs += price
            renewal = add_period(renewal, domain.period)
    return round(costs, 2)


def next_renewal(data: InwxData) -> datetime | None:
    """Return the date of the next automatic renewal."""
    return min(
        (
            domain.renewal_date
            for domain in data.domains.values()
            if domain.renewal_mode == RENEWAL_MODE_AUTORENEW and domain.renewal_date
        ),
        default=None,
    )


class InwxCoordinator(DataUpdateCoordinator[InwxData]):
    """Class to manage fetching INWX data."""

    config_entry: InwxConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: InwxConfigEntry, client: InwxClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    @property
    def forecast_days(self) -> int:
        """Return the forecast period in days."""
        return int(self.config_entry.options.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS))

    @property
    def include_vat(self) -> bool:
        """Return whether prices include VAT."""
        return bool(self.config_entry.options.get(CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT))

    @override
    async def _async_update_data(self) -> InwxData:
        """Fetch balance, domains and renewal prices."""
        try:
            await self.client.login()
            try:
                balance = await self.client.get_balance()
                domains = {domain.ro_id: domain for domain in await self.client.get_domains()}
                prices = {
                    ro_id: await self.client.get_renewal_price(domain)
                    for ro_id, domain in domains.items()
                }
            finally:
                with suppress(InwxError):
                    await self.client.logout()
        except InwxAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except InwxConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
            ) from err
        except InwxApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(err)},
            ) from err

        self._remove_stale_devices(domains)

        return InwxData(balance=balance, domains=domains, prices=prices)

    def _remove_stale_devices(self, domains: dict[int, InwxDomain]) -> None:
        """Remove the devices of domains that left the account."""
        valid_identifiers = {(DOMAIN, str(self.config_entry.unique_id))} | {
            (DOMAIN, domain_device_identifier(self.config_entry, ro_id)) for ro_id in domains
        }
        device_registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, self.config_entry.entry_id
        ):
            if not device.identifiers & valid_identifiers:
                device_registry.async_remove_device(device.id)


def domain_device_identifier(config_entry: ConfigEntry, ro_id: int) -> str:
    """Return the device identifier of a domain."""
    return f"{config_entry.unique_id}_{ro_id}"
