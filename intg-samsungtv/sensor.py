"""Sensor entities for the Samsung TV integration."""

import logging

from const import SamsungConfig
from tv import SamsungTv
from ucapi import EntityTypes, sensor
from ucapi_framework import SensorEntity, create_entity_id

_LOG = logging.getLogger(__name__)


class SmartThingsConnectionSensor(SensorEntity):
    """Expose the SmartThings connection verification result."""

    def __init__(self, config_device: SamsungConfig, device: SamsungTv):
        """Initialize the SmartThings connection sensor."""
        self._device = device
        entity_id = create_entity_id(
            EntityTypes.SENSOR, config_device.identifier, "smartthings_connection"
        )
        super().__init__(
            entity_id,
            "SmartThings Connection",
            features=[],
            attributes={
                sensor.Attributes.STATE: sensor.States.UNKNOWN,
                sensor.Attributes.VALUE: "unknown",
            },
            device_class=sensor.DeviceClasses.CUSTOM,
            options={sensor.Options.CUSTOM_UNIT: "status"},
        )
        self.subscribe_to_device(device)
        _LOG.debug("Created SmartThings connection sensor: %s", entity_id)

    async def sync_state(self) -> None:
        """Publish the status last determined during SmartThings setup."""
        status = self._device.smartthings_connection_status
        self.update(
            {
                sensor.Attributes.STATE: sensor.States.ON,
                sensor.Attributes.VALUE: status,
            }
        )
