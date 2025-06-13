"""
Configuration handling of the integration driver.

:copyright: (c) 2023-2024 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import dataclasses
import json
import logging
import os
from asyncio import Lock
from dataclasses import dataclass
from typing import Iterator
from ucapi import EntityTypes

_LOG = logging.getLogger(__name__)

_CFG_FILENAME = "config.json"


def create_entity_id(device_id: str, entity_type: EntityTypes) -> str:
    """Create a unique entity identifier for the given receiver and entity type."""
    return f"{entity_type.value}.{device_id}"


def device_from_entity_id(entity_id: str) -> str | None:
    """
    Return the id prefix of an entity_id.

    :param entity_id: the entity identifier
    :return: the device prefix, or None if entity_id doesn't contain a dot
    """
    return entity_id.split(".", 1)[1]


@dataclass
class SamsungDevice:
    """Samsung device configuration."""

    identifier: str
    """Unique identifier of the device. (MAC Address)"""
    name: str
    """Friendly name of the device."""
    token: str
    """Token for connection to device."""
    address: str
    """IP Address of device"""
    mac_address: str | None = None
    """MAC Address of device"""
    reports_power_state: bool = False
    """True if the device supports power state reporting."""


class _EnhancedJSONEncoder(json.JSONEncoder):
    """Python dataclass json encoder."""

    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


class Devices:
    """Integration driver configuration class. Manages all configured Apple TV devices."""

    def __init__(self, data_path: str, add_handler, remove_handler):
        """
        Create a configuration instance for the given configuration path.

        :param data_path: configuration path for the configuration file and client certificates.
        """
        self._data_path: str = data_path
        self._cfg_file_path: str = os.path.join(data_path, _CFG_FILENAME)
        self._config: list[SamsungDevice] = []
        self._add_handler = add_handler
        self._remove_handler = remove_handler
        self.load()
        self._config_lock = Lock()

    @property
    def data_path(self) -> str:
        """Return the configuration path."""
        return self._data_path

    def all(self) -> Iterator[SamsungDevice]:
        """Get an iterator for all device configurations."""
        return iter(self._config)

    def contains(self, device_id: str) -> bool:
        """Check if there's a device with the given device identifier."""
        for item in self._config:
            if item.identifier == device_id:
                return True
        return False

    def add_or_update(self, device: SamsungDevice) -> None:
        """
        Add a new configured Apple TV device and persist configuration.

        The device is updated if it already exists in the configuration.
        """
        # duplicate check
        if not self.update(device):
            self._config.append(device)
            self.store()
            if self._add_handler is not None:
                self._add_handler(device)

    def get(self, device_id: str) -> SamsungDevice | None:
        """Get device configuration for given identifier."""
        for item in self._config:
            if item.identifier == device_id:
                # return a copy
                return dataclasses.replace(item)
        return None

    def update(self, device: SamsungDevice) -> bool:
        """Update a configured Samsung TV device and persist configuration."""
        for item in self._config:
            if item.identifier == device.identifier:
                item.address = device.address
                item.name = device.name
                item.token = device.token
                item.mac_address = device.mac_address
                item.reports_power_state = device.reports_power_state
                return self.store()
        return False

    def remove(self, device_id: str) -> bool:
        """Remove the given device configuration."""
        device = self.get(device_id)
        if device is None:
            return False
        try:
            self._config.remove(device)
            if self._remove_handler is not None:
                self._remove_handler(device)
            return True
        except ValueError:
            pass
        return False

    def clear(self) -> None:
        """Remove the configuration file."""
        self._config = []

        if os.path.exists(self._cfg_file_path):
            os.remove(self._cfg_file_path)

        if self._remove_handler is not None:
            self._remove_handler(None)

    def store(self) -> bool:
        """
        Store the configuration file.

        :return: True if the configuration could be saved.
        """
        try:
            with open(self._cfg_file_path, "w+", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, cls=_EnhancedJSONEncoder)
            return True
        except OSError as err:
            _LOG.error("Cannot write the config file: %s", err)

        return False

    def load(self) -> bool:
        """
        Load the config into the config global variable.

        :return: True if the configuration could be loaded.
        """
        try:
            with open(self._cfg_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                # not using SamsungDevice(**item) to be able to migrate
                # old configuration files with missing attributes
                device = SamsungDevice(
                    item.get("identifier"),
                    item.get("name", ""),
                    item.get("token"),
                    item.get("address"),
                    item.get("mac_address"),
                    item.get("reports_power_state"),
                )
                self._config.append(device)
            return True
        except OSError as err:
            _LOG.error("Cannot open the config file: %s", err)
        except (AttributeError, ValueError, TypeError) as err:
            _LOG.error("Empty or invalid config file: %s", err)

        return False

    def migration_required(self) -> bool:
        """Check if configuration migration is required."""
        return False

    async def migrate(self) -> bool:
        """Migrate configuration if required."""
        return True


devices: Devices | None = None
