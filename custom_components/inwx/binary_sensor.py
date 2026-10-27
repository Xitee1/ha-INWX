"""Binary sensor platform for the INWX integration."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import InwxConfigEntry, calculate_renewal_costs
from .entity import InwxAccountEntity

PARALLEL_UPDATES = 0

BALANCE_INSUFFICIENT = BinarySensorEntityDescription(
    key="balance_insufficient",
    translation_key="balance_insufficient",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InwxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up INWX binary sensors."""
    async_add_entities(
        [InwxBalanceInsufficientBinarySensor(entry.runtime_data, BALANCE_INSUFFICIENT)]
    )


class InwxBalanceInsufficientBinarySensor(InwxAccountEntity, BinarySensorEntity):
    """Binary sensor that is on when the balance does not cover upcoming renewals."""

    @property
    @override
    def is_on(self) -> bool:
        """Return true if the renewal costs exceed the available balance."""
        costs = calculate_renewal_costs(
            self.coordinator.data,
            dt_util.utcnow(),
            self.coordinator.forecast_days,
            self.coordinator.include_vat,
        )
        return costs > self.coordinator.data.balance.available
