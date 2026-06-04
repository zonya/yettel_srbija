"""Senzori za Yettel Srbija."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_MSISDN, CONF_TARIFF


@dataclass(frozen=True, kw_only=True)
class YettelSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object] = lambda d: None


def _internet_value(d: dict):
    if d.get("internet_unlimited"):
        return "Neograničeno"
    return d.get("internet_gb")


def _minutes_value(d: dict):
    return "Neograničeno" if d.get("minutes_unlimited") else d.get("minutes")


def _sms_value(d: dict):
    return "Neograničeno" if d.get("sms_unlimited") else d.get("sms")


SENSORS: tuple[YettelSensorDescription, ...] = (
    YettelSensorDescription(
        key="balance",
        name="Trenutno stanje",
        native_unit_of_measurement="RSD",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",
        value_fn=lambda d: d.get("balance"),
    ),
    YettelSensorDescription(
        key="bill_amount",
        name="Iznos računa",
        native_unit_of_measurement="RSD",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:file-document-outline",
        value_fn=lambda d: d.get("bill_amount"),
    ),
    YettelSensorDescription(
        key="bill_status",
        name="Status računa",
        icon="mdi:receipt-text-check",
        value_fn=lambda d: d.get("bill_status"),
    ),
    YettelSensorDescription(
        key="bill_deadline",
        name="Rok plaćanja",
        icon="mdi:calendar-clock",
        value_fn=lambda d: d.get("bill_deadline"),
    ),
    YettelSensorDescription(
        key="internet",
        name="Internet",
        icon="mdi:web",
        value_fn=_internet_value,
    ),
    YettelSensorDescription(
        key="roaming_gb",
        name="Roming internet",
        native_unit_of_measurement="GB",
        icon="mdi:earth",
        value_fn=lambda d: d.get("roaming_gb"),
    ),
    YettelSensorDescription(
        key="wb_gb",
        name="Zapadni Balkan internet",
        native_unit_of_measurement="GB",
        icon="mdi:map-marker-radius",
        value_fn=lambda d: d.get("wb_gb"),
    ),
    YettelSensorDescription(
        key="minutes",
        name="Minuti",
        icon="mdi:phone",
        value_fn=_minutes_value,
    ),
    YettelSensorDescription(
        key="sms",
        name="SMS poruke",
        icon="mdi:message-text",
        value_fn=_sms_value,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    msisdn = entry.data.get(CONF_MSISDN, "")
    tariff = entry.data.get(CONF_TARIFF, "Yettel")

    entities = [
        YettelSensor(coordinator, entry, desc, msisdn, tariff) for desc in SENSORS
    ]
    async_add_entities(entities)


class YettelSensor(CoordinatorEntity, SensorEntity):
    entity_description: YettelSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description, msisdn, tariff) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._msisdn = msisdn
        self._attr_unique_id = f"{msisdn}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, msisdn)},
            name=f"Yettel {msisdn}",
            manufacturer="Yettel Srbija",
            model=tariff,
        )

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        if self.entity_description.key == "bill_amount":
            return {
                "mesec": data.get("bill_month"),
                "status": data.get("bill_status"),
                "rok": data.get("bill_deadline"),
            }
        if self.entity_description.key == "balance":
            return {"tarifa": data.get("tariff")}
        return None
