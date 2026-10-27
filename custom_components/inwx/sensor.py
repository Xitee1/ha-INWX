"""Sensor platform for the INWX integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
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
from .entity import InwxAccountEntity, InwxDomainEntity, async_setup_domain_entities

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
    attributes_fn: Callable[[InwxCoordinator, int], dict[str, Any]] | None = None


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
    InwxDomainSensorEntityDescription(
        key="nameservers",
        translation_key="nameservers",
        value_fn=lambda coordinator, ro_id: (
            len(nameservers)
            if (nameservers := coordinator.data.domains[ro_id].nameservers) is not None
            else None
        ),
        attributes_fn=lambda coordinator, ro_id: {
            "nameservers": list(coordinator.data.domains[ro_id].nameservers or ())
        },
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

    async_setup_domain_entities(
        entry,
        async_add_entities,
        lambda coordinator, ro_id: (
            InwxDomainSensor(coordinator, description, ro_id) for description in DOMAIN_SENSORS
        ),
    )


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
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes of the sensor."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator, self.ro_id)

    @property
    @override
    def native_unit_of_measurement(self) -> str | None:
        """Return the currency for monetary sensors."""
        if self.entity_description.device_class == SensorDeviceClass.MONETARY and (
            price := self.coordinator.data.prices.get(self.ro_id)
        ):
            return price.currency
        return None
