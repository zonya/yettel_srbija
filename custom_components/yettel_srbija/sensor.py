"""Senzori za Yettel Srbija (uređaj po nalogu/usluzi)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_MSISDN, CONF_TARIFF, CONF_NICKNAME


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


# Zajednički za sve naloge (mobilni i fiksni)
COMMON: tuple[YettelSensorDescription, ...] = (
    YettelSensorDescription(
        key="balance", name="Trenutno stanje",
        native_unit_of_measurement="RSD", device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL, icon="mdi:cash",
        value_fn=lambda d: d.get("balance"),
    ),
    YettelSensorDescription(
        key="bill_amount", name="Iznos računa",
        native_unit_of_measurement="RSD", device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL, icon="mdi:file-document-outline",
        value_fn=lambda d: d.get("bill_amount"),
    ),
    YettelSensorDescription(
        key="bill_status", name="Status računa", icon="mdi:receipt-text-check",
        value_fn=lambda d: d.get("bill_status"),
    ),
    YettelSensorDescription(
        key="bill_deadline", name="Rok plaćanja", icon="mdi:calendar-clock",
        value_fn=lambda d: d.get("bill_deadline"),
    ),
)

# Samo mobilni nalozi
MOBILE: tuple[YettelSensorDescription, ...] = (
    YettelSensorDescription(key="internet", name="Internet", icon="mdi:web", value_fn=_internet_value),
    YettelSensorDescription(
        key="roaming_gb", name="Roming internet", native_unit_of_measurement="GB",
        icon="mdi:earth", value_fn=lambda d: d.get("roaming_gb"),
    ),
    YettelSensorDescription(
        key="wb_gb", name="Zapadni Balkan internet", native_unit_of_measurement="GB",
        icon="mdi:map-marker-radius", value_fn=lambda d: d.get("wb_gb"),
    ),
    YettelSensorDescription(key="minutes", name="Minuti", icon="mdi:phone", value_fn=_minutes_value),
    YettelSensorDescription(key="sms", name="SMS poruke", icon="mdi:message-text", value_fn=_sms_value),
)

# Samo fiksni nalozi (TV/optika)
FIXED: tuple[YettelSensorDescription, ...] = (
    YettelSensorDescription(
        key="optical_speed", name="Optički internet", icon="mdi:speedometer",
        value_fn=lambda d: d.get("optical_speed"),
    ),
    YettelSensorDescription(
        key="tv", name="Televizija", icon="mdi:television-classic",
        value_fn=lambda d: d.get("tv"),
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
    nadimak = (entry.options.get(CONF_NICKNAME, entry.data.get(CONF_NICKNAME, "")) or "").strip()

    data = coordinator.data or {}
    primary_val = data.get("primary", msisdn)
    accounts = data.get("accounts") or [{"value": msisdn, "label": tariff, "kind": "mobile"}]

    entities: list[YettelSensor] = []
    for acc in accounts:
        val = acc["value"]
        kind = acc.get("kind", "mobile")
        label = acc.get("label", tariff)
        is_primary = val == primary_val

        if is_primary:
            dev_name = f"Yettel {nadimak}".strip() if nadimak else f"Yettel {msisdn}"
            naziv = f"{nadimak} {tariff}".strip() if nadimak else tariff
            model = tariff
        else:
            suffix = "TV i internet" if kind == "fixed" else label
            dev_name = f"Yettel {nadimak} – {suffix}".strip() if nadimak else f"Yettel {suffix}"
            naziv = f"{nadimak} {suffix}".strip() if nadimak else suffix
            model = label

        descs = COMMON + (FIXED if kind == "fixed" else MOBILE)
        for desc in descs:
            entities.append(
                YettelSensor(coordinator, val, desc, dev_name, naziv, model)
            )

    async_add_entities(entities)


class YettelSensor(CoordinatorEntity, SensorEntity):
    entity_description: YettelSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, value, description, dev_name, naziv, model) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value = value
        self._naziv = naziv
        self._attr_unique_id = f"{value}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, value)},
            name=dev_name,
            manufacturer="Yettel Srbija",
            model=model,
        )

    def _acc(self) -> dict:
        return (self.coordinator.data or {}).get("by", {}).get(self._value, {})

    @property
    def native_value(self):
        return self.entity_description.value_fn(self._acc())

    @property
    def extra_state_attributes(self):
        data = self._acc()
        key = self.entity_description.key
        if key == "bill_amount":
            return {
                "mesec": data.get("bill_month"),
                "status": data.get("bill_status"),
                "rok": data.get("bill_deadline"),
            }
        if key == "balance":
            return {
                "tarifa": data.get("tariff") or data.get("label"),
                "naziv": self._naziv,
            }
        return None
