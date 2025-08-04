from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def _find_next_package(deliveries):
    if not deliveries or not isinstance(deliveries, list):
        return None
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    valid = [
        d
        for d in deliveries
        if d.get("dropoff_eta") and int(d["dropoff_eta"]) >= now_ts
    ]
    if not valid:
        return None
    return min(valid, key=lambda d: int(d["dropoff_eta"]))


class NextPackageSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._attr_name = "Airmee Next Package"
        self._attr_unique_id = f"{entry.entry_id}_next_package"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        deliveries = self.coordinator.data
        next_pkg = _find_next_package(deliveries)
        if not next_pkg:
            return None
        eta = int(next_pkg.get("dropoff_eta"))
        return datetime.fromtimestamp(eta, tz=timezone.utc)

    @property
    def extra_state_attributes(self):
        deliveries = self.coordinator.data
        next_pkg = _find_next_package(deliveries)
        if not next_pkg:
            return {}
        return {
            "package_name": next_pkg.get("product_name"),
            "sender": next_pkg.get("sender_name"),
            "tracking_url": next_pkg.get("tracking_url"),
            "pin": next_pkg.get("pin"),
            "status": next_pkg.get("courier_status_formatted"),
            "dropoff_earliest_time": next_pkg.get("dropoff_earliest_time"),
            "dropoff_latest_time": next_pkg.get("dropoff_latest_time"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Airmee Account",
            manufacturer="Airmee",
        )


class PackageCountSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._attr_name = "Airmee Package Count"
        self._attr_unique_id = f"{entry.entry_id}_package_count"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data or not isinstance(data, list):
            return 0
        return len(data)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Airmee Account",
        )


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    next_sensor = NextPackageSensor(coordinator, config_entry)
    count_sensor = PackageCountSensor(coordinator, config_entry)
    async_add_entities([next_sensor, count_sensor], True)
