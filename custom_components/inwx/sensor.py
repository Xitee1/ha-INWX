"""Sensor platform for the INWX integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import RENEWAL_MODES
from .coordinator import (
    InwxConfigEntry,
    InwxCoordinator,
    calculate_renewal_costs,
    next_renewal,
    renewal_price,
)
from .entity import InwxAccountEntity, InwxDomainEntity

PARALLEL_UPDATES = 0

type SensorValue = str | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class InwxAccountSensorEntityDescription(SensorEntityDescription):
    """Describes an INWX account sensor."""

    value_fn: Callable[[InwxCoordinator], SensorValue]


@dataclass(frozen=True, kw_only=True)
class InwxDomainSensorEntityDescription(SensorEntityDescription):
    """Describes an INWX domain sensor."""

    value_fn: Callable[[InwxCoordinator, int], SensorValue]


ACCOUNT_SENSORS: tuple[InwxAccountSensorEntityDescription, ...] = (
    InwxAccountSensorEntityDescription(
        key="balance",
        translation_key="balance",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda coordinator: coordinator.data.balance.available,
    ),
    InwxAccountSensorEntityDescription(
        key="renewal_costs",
        translation_key="renewal_costs",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda coordinator: calculate_renewal_costs(
            coordinator.data,
            dt_util.utcnow(),
            coordinator.forecast_days,
            coordinator.include_vat,
        ),
    ),
    InwxAccountSensorEntityDescription(
        key="next_renewal",
        translation_key="next_renewal",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: next_renewal(coordinator.data),
    ),
)

DOMAIN_SENSORS: tuple[InwxDomainSensorEntityDescription, ...] = (
    InwxDomainSensorEntityDescription(
        key="renewal_date",
        translation_key="renewal_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator, ro_id: coordinator.data.domains[ro_id].renewal_date,
    ),
    InwxDomainSensorEntityDescription(
        key="expiration_date",
        translation_key="expiration_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator, ro_id: coordinator.data.domains[ro_id].expiration_date,
    ),
    InwxDomainSensorEntityDescription(
        key="renewal_price",
        translation_key="renewal_price",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda coordinator, ro_id: renewal_price(
            coordinator.data.prices[ro_id], coordinator.include_vat
        ),
    ),
    InwxDomainSensorEntityDescription(
        key="renewal_mode",
        translation_key="renewal_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[mode.lower() for mode in RENEWAL_MODES],
        value_fn=lambda coordinator, ro_id: (
            mode.lower()
            if (mode := coordinator.data.domains[ro_id].renewal_mode) in RENEWAL_MODES
            else None
        ),
    ),
    InwxDomainSensorEntityDescription(
        key="status",
        translation_key="status",
        value_fn=lambda coordinator, ro_id: coordinator.data.domains[ro_id].status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InwxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up INWX sensors."""
    coordinator = entry.runtime_data

    async_add_entities(
        InwxAccountSensor(coordinator, description) for description in ACCOUNT_SENSORS
    )

    known_domains: set[int] = set()

    @callback
    def _async_add_new_domains() -> None:
        """Add sensors for domains that joined the account."""
        current_domains = set(coordinator.data.domains)
        known_domains.intersection_update(current_domains)
        if not (new_domains := current_domains - known_domains):
            return
        known_domains.update(new_domains)
        async_add_entities(
            InwxDomainSensor(coordinator, description, ro_id)
            for ro_id in new_domains
            for description in DOMAIN_SENSORS
        )

    _async_add_new_domains()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_domains))


class InwxAccountSensor(InwxAccountEntity, SensorEntity):
    """Sensor of the INWX account."""

    entity_description: InwxAccountSensorEntityDescription

    @property
    @override
    def native_value(self) -> SensorValue:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    @override
    def native_unit_of_measurement(self) -> str | None:
        """Return the currency for monetary sensors."""
        if self.entity_description.device_class == SensorDeviceClass.MONETARY:
            return self.coordinator.data.currency
        return None


class InwxDomainSensor(InwxDomainEntity, SensorEntity):
    """Sensor of a domain in the INWX account."""

    entity_description: InwxDomainSensorEntityDescription

    @property
    @override
    def native_value(self) -> SensorValue:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator, self.ro_id)

    @property
    @override
    def native_unit_of_measurement(self) -> str | None:
        """Return the currency for monetary sensors."""
        if self.entity_description.device_class == SensorDeviceClass.MONETARY and (
            price := self.coordinator.data.prices.get(self.ro_id)
        ):
            return price.currency
        return None
