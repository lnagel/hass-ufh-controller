"""Binary sensor platform for Underfloor Heating Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .const import SUBENTRY_TYPE_ZONE, ControllerStatus, ZoneStatus
from .entity import (
    UFHControllerEntity,
    UFHControllerZoneEntity,
    get_controller_subentry_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import UFHControllerDataUpdateCoordinator
    from .data import UFHControllerConfigEntry


@dataclass(frozen=True, kw_only=True)
class UFHZoneBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes UFH zone binary sensor entity."""

    value_fn: Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, kw_only=True)
class UFHControllerBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes UFH controller binary sensor entity."""

    value_fn: Callable[[UFHControllerDataUpdateCoordinator], bool]
    attrs_fn: Callable[[UFHControllerDataUpdateCoordinator], dict[str, Any]] | None = (
        None
    )
    entity_registry_visible_default: bool = False


ZONE_BINARY_SENSORS: tuple[UFHZoneBinarySensorEntityDescription, ...] = (
    UFHZoneBinarySensorEntityDescription(
        key="blocked",
        translation_key="blocked",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: data.get("blocked", False),
    ),
    UFHZoneBinarySensorEntityDescription(
        key="heat_request",
        translation_key="heat_request",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda data: data.get("heat_request", False),
    ),
    UFHZoneBinarySensorEntityDescription(
        key="flow",
        translation_key="flow",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda data: data.get("flow", False),
    ),
)


def _status_value(coordinator: UFHControllerDataUpdateCoordinator) -> bool:
    """Return True if there is a problem (degraded or fail-safe)."""
    return coordinator.status in (ControllerStatus.DEGRADED, ControllerStatus.FAIL_SAFE)


def _status_attrs(coordinator: UFHControllerDataUpdateCoordinator) -> dict[str, Any]:
    """Return additional status attributes."""
    return {
        "controller_status": coordinator.status.value,
        "zones_degraded": coordinator.data.get("zones_degraded", 0),
        "zones_fail_safe": coordinator.data.get("zones_fail_safe", 0),
    }


def _flush_request_value(coordinator: UFHControllerDataUpdateCoordinator) -> bool:
    """Return True if flush is currently requested."""
    if not coordinator.controller.state.flush_enabled:
        return False
    return coordinator.data.get("flush_request", False)


# Controller-level binary sensor descriptions
STATUS_SENSOR = UFHControllerBinarySensorEntityDescription(
    key="status",
    translation_key="status",
    device_class=BinarySensorDeviceClass.PROBLEM,
    value_fn=_status_value,
    attrs_fn=_status_attrs,
)

FLUSH_REQUEST_SENSOR = UFHControllerBinarySensorEntityDescription(
    key="flush_request",
    translation_key="flush_request",
    device_class=BinarySensorDeviceClass.HEAT,
    value_fn=_flush_request_value,
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: UFHControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data.coordinator

    # Add controller-level sensors
    controller_subentry_id = get_controller_subentry_id(entry)
    if controller_subentry_id is not None:
        controller_descriptions = [STATUS_SENSOR]

        # Only create flush_request sensor if DHW entity is configured
        if entry.data.get("dhw_active_entity"):
            controller_descriptions.append(FLUSH_REQUEST_SENSOR)

        async_add_entities(
            [
                UFHControllerBinarySensor(coordinator, controller_subentry_id, desc)
                for desc in controller_descriptions
            ],
            config_subentry_id=controller_subentry_id,
        )

    # Add zone-level binary sensors for each zone subentry
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_ZONE:
            continue
        zone_id = subentry.data["id"]
        zone_name = subentry.data["name"]
        subentry_id = subentry.subentry_id

        async_add_entities(
            [
                UFHZoneBinarySensor(
                    coordinator=coordinator,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    description=description,
                    subentry_id=subentry_id,
                )
                for description in ZONE_BINARY_SENSORS
            ],
            config_subentry_id=subentry_id,
        )


class UFHZoneBinarySensor(UFHControllerZoneEntity, BinarySensorEntity):
    """Binary sensor entity for zone status."""

    entity_description: UFHZoneBinarySensorEntityDescription
    _attr_entity_registry_visible_default = False

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        description: UFHZoneBinarySensorEntityDescription,
        subentry_id: str,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator, zone_id, zone_name, subentry_id)
        self.entity_description = description

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{zone_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return the sensor state."""
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        return self.entity_description.value_fn(zone_data)

    @property
    def available(self) -> bool:
        """
        Return True if entity is available.

        Binary sensors are unavailable when zone is FAIL_SAFE,
        or when they have no valid value.
        """
        if not super().available:
            return False
        zone_data = self.coordinator.data.get("zones", {}).get(self._zone_id, {})
        zone_status = zone_data.get("zone_status", "initializing")
        return zone_status != ZoneStatus.FAIL_SAFE.value


class UFHControllerBinarySensor(UFHControllerEntity, BinarySensorEntity):
    """Generic binary sensor entity for controller-level status."""

    entity_description: UFHControllerBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: UFHControllerDataUpdateCoordinator,
        subentry_id: str,
        description: UFHControllerBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator, subentry_id)
        self.entity_description = description
        self._attr_entity_registry_visible_default = (
            description.entity_registry_visible_default
        )

        controller_id = coordinator.config_entry.data.get("controller_id", "")
        self._attr_unique_id = f"{controller_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return the sensor state."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes if defined."""
        if self.entity_description.attrs_fn is not None:
            return self.entity_description.attrs_fn(self.coordinator)
        return None
