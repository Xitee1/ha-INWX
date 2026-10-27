"""Base entities for the INWX integration."""

from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InwxDomain
from .const import DOMAIN
from .coordinator import InwxCoordinator, domain_device_identifier


def account_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    """Return the device info of the INWX account."""
    return DeviceInfo(
        identifiers={(DOMAIN, str(config_entry.unique_id))},
        name=f"INWX {config_entry.title}",
        manufacturer="INWX",
        model="Account",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://www.inwx.de/",
    )


class InwxEntity(CoordinatorEntity[InwxCoordinator]):
    """Base entity for INWX."""

    _attr_has_entity_name = True


class InwxAccountEntity(InwxEntity):
    """Entity of the INWX account."""

    def __init__(self, coordinator: InwxCoordinator, description: EntityDescription) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{description.key}"
        self._attr_device_info = account_device_info(coordinator.config_entry)


class InwxDomainEntity(InwxEntity):
    """Entity of a domain in the INWX account."""

    def __init__(
        self, coordinator: InwxCoordinator, description: EntityDescription, ro_id: int
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.ro_id = ro_id
        config_entry = coordinator.config_entry
        device_id = domain_device_identifier(config_entry, ro_id)
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=coordinator.data.domains[ro_id].name,
            manufacturer="INWX",
            model="Domain",
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=dr.async_get_device_id_by_identifier(
                coordinator.hass,
                (DOMAIN, str(config_entry.unique_id)),
                config_entry_id=config_entry.entry_id,
            ),
        )

    @property
    def domain(self) -> InwxDomain:
        """Return the domain data."""
        return self.coordinator.data.domains[self.ro_id]

    @property
    @override
    def available(self) -> bool:
        """Return if the domain is still in the account."""
        return super().available and self.ro_id in self.coordinator.data.domains
