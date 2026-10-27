"""Binary sensor platform for the INWX integration."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import InwxConfigEntry
from .entity import InwxDomainEntity, async_setup_domain_entities

PARALLEL_UPDATES = 0

TRANSFER_LOCK = BinarySensorEntityDescription(
    key="transfer_lock",
    translation_key="transfer_lock",
    device_class=BinarySensorDeviceClass.LOCK,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InwxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up INWX binary sensors."""
    async_setup_domain_entities(
        entry,
        async_add_entities,
        lambda coordinator, ro_id: [
            InwxTransferLockBinarySensor(coordinator, TRANSFER_LOCK, ro_id)
        ],
    )


class InwxTransferLockBinarySensor(InwxDomainEntity, BinarySensorEntity):
    """Binary sensor of the transfer lock of a domain.

    With the lock device class, on means unlocked.
    """

    @property
    @override
    def is_on(self) -> bool | None:
        """Return true if the transfer lock is off."""
        if (transfer_lock := self.domain.transfer_lock) is None:
            return None
        return not transfer_lock
