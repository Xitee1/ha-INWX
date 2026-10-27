"""Base entities for the INWX integration."""

from collections.abc import Callable, Iterable
from typing import override

from aioinwx import InwxDomain
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InwxConfigEntry, InwxCoordinator, domain_device_identifier


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


@callback
def async_setup_domain_entities(
    entry: InwxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    entity_factory: Callable[[InwxCoordinator, int], Iterable[Entity]],
) -> None:
    """Add the entities of each domain, also of domains that join the account later."""
    coordinator = entry.runtime_data
    known_domains: set[int] = set()

    @callback
    def _async_add_new_domains() -> None:
        """Add entities for domains that joined the account."""
        current_domains = set(coordinator.data.domains)
        known_domains.intersection_update(current_domains)
        if not (new_domains := current_domains - known_domains):
            return
        known_domains.update(new_domains)
        async_add_entities(
            entity for ro_id in new_domains for entity in entity_factory(coordinator, ro_id)
        )

    _async_add_new_domains()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_domains))


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
