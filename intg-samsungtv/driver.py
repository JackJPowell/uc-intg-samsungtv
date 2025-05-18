#!/usr/bin/env python3
"""
This module implements a Remote Two integration driver for Apple TV devices.

:copyright: (c) 2023-2024 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
import sys
from typing import Any

import config
import setup
import ucapi
import ucapi.api as uc
from ucapi import media_player
from media_player import SamsungMediaPlayer
from config import SamsungDevice
import tv

_LOG = logging.getLogger("driver")  # avoid having __main__ in log messages
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

# Global variables
api = uc.IntegrationAPI(_LOOP)
_configured_devices: dict[str, tv.SamsungTv] = {}


@api.listens_to(ucapi.Events.CONNECT)
async def on_r2_connect_cmd() -> None:
    """Connect all configured devices when the Remote Two sends the connect command."""
    _LOG.debug("Client connect command: connecting device(s)")
    await api.set_device_state(
        ucapi.DeviceStates.CONNECTED
    )  # just to make sure the device state is set
    for device in _configured_devices.values():
        # start background task
        await device.connect()


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_r2_disconnect_cmd():
    """Disconnect all configured devices when the Remote Two sends the disconnect command."""
    _LOG.debug("Client disconnect command: disconnecting device(s)")
    for device in _configured_devices.values():
        await device.disconnect()


@api.listens_to(ucapi.Events.ENTER_STANDBY)
async def on_r2_enter_standby() -> None:
    """
    Enter standby notification from Remote Two.

    Disconnect every ATV instances.
    """
    _LOG.debug("Enter standby event: disconnecting device(s)")
    for device in _configured_devices.values():
        await device.disconnect()


@api.listens_to(ucapi.Events.EXIT_STANDBY)
async def on_r2_exit_standby() -> None:
    """
    Exit standby notification from Remote Two.

    Connect all ATV instances.
    """
    _LOG.debug("Exit standby event: connecting device(s)")
    for device in _configured_devices.values():
        await device.connect()


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """
    Subscribe to given entities.

    :param entity_ids: entity identifiers.
    """
    _LOG.debug("Subscribe entities event: %s", entity_ids)
    for entity_id in entity_ids:
        if entity_id in _configured_devices:
            device = _configured_devices[entity_id]
            _LOG.info("Add '%s' to configured devices and connect", device.name)
            device.check_power_status()
            if device.is_on is None:
                state = media_player.States.UNAVAILABLE
            else:
                state = (
                    media_player.States.ON if device.is_on else media_player.States.OFF
                )
            api.configured_entities.update_attributes(
                entity_id, {media_player.Attributes.STATE: state}
            )
            await device.connect()
            continue

        device = config.devices.get(entity_id)
        if device:
            _add_configured_device(device)
        else:
            _LOG.error(
                "Failed to subscribe entity %s: no Device instance found", entity_id
            )


@api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """On unsubscribe, we disconnect the objects and remove listeners for events."""
    _LOG.debug("Unsubscribe entities event: %s", entity_ids)
    for entity_id in entity_ids:
        if entity_id in _configured_devices:
            device = _configured_devices.pop(entity_id)
            _LOG.info(
                "Removed '%s' from configured devices and disconnect", device.name
            )
            await device.disconnect()
            device.events.remove_all_listeners()


async def on_device_connected(identifier: str) -> None:
    """Handle device connection."""
    _LOG.debug("Device connected: %s", identifier)
    state = media_player.States.UNKNOWN
    if identifier in _configured_devices:
        device = _configured_devices[identifier]
        if device_state := device.state:
            state = _device_state_to_media_player_state(device_state)

    api.configured_entities.update_attributes(
        identifier, {media_player.Attributes.STATE: state}
    )
    await api.set_device_state(
        ucapi.DeviceStates.CONNECTED
    )  # just to make sure the device state is set


async def on_device_disconnected(identifier: str) -> None:
    """Handle device disconnection."""
    _LOG.debug("Device disconnected: %s", identifier)
    api.configured_entities.update_attributes(
        identifier, {media_player.Attributes.STATE: media_player.States.UNAVAILABLE}
    )


async def on_device_connection_error(identifier: str) -> None:
    """Set entities of device to state UNAVAILABLE if device connection error occurred."""
    # _LOG.error(message)
    api.configured_entities.update_attributes(
        identifier, {media_player.Attributes.STATE: media_player.States.UNAVAILABLE}
    )
    await api.set_device_state(ucapi.DeviceStates.ERROR)


def _device_state_to_media_player_state(
    device_state: tv.PowerState,
) -> media_player.States:
    match device_state:
        case tv.PowerState.ON:
            state = media_player.States.ON
        case tv.PowerState.OFF:
            state = media_player.States.OFF
        case _:
            state = media_player.States.UNKNOWN
    return state


# pylint: disable=too-many-branches,too-many-statements
async def on_device_update(entity_id: str, update: dict[str, Any] | None) -> None:
    """
    Update attributes of configured media-player entity if Device properties changed.

    :param entity_id: Device media-player entity identifier
    :param update: dictionary containing the updated properties or None
    """
    attributes = {}

    if api.configured_entities.contains(entity_id):
        target_entity = api.configured_entities.get(entity_id)
    else:
        target_entity = api.available_entities.get(entity_id)
    if target_entity is None:
        return

    if "state" in update:
        state = _device_state_to_media_player_state(update["state"])
        if state == media_player.States.UNKNOWN:
            logging.warning("Device state is UNKNOWN")
        attributes[ucapi.media_player.Attributes.STATE] = state

    if (
        "source" in update
        and target_entity.attributes.get(media_player.Attributes.SOURCE, "")
        != update["source"]
    ):
        attributes[media_player.Attributes.SOURCE] = update["source"]

    if "sourceList" in update:
        if media_player.Attributes.SOURCE_LIST in target_entity.attributes:
            if len(
                target_entity.attributes[media_player.Attributes.SOURCE_LIST]
            ) != len(update["sourceList"]):
                attributes[media_player.Attributes.SOURCE_LIST] = update["sourceList"]
        else:
            attributes[media_player.Attributes.SOURCE_LIST] = update["sourceList"]

    if "volume" in update:
        attributes[media_player.Attributes.VOLUME] = update["volume"]

    if media_player.Attributes.STATE in attributes:
        if attributes[media_player.Attributes.STATE] == media_player.States.OFF:
            attributes[media_player.Attributes.SOURCE] = ""

    if attributes:
        if api.configured_entities.contains(entity_id):
            api.configured_entities.update_attributes(entity_id, attributes)
        else:
            api.available_entities.update_attributes(entity_id, attributes)


def _add_configured_device(device_config: SamsungDevice, connect: bool = True) -> None:
    # the device should not yet be configured, but better be safe
    if device_config.identifier in _configured_devices:
        device = _configured_devices[device_config.identifier]
        _LOOP.create_task(device.disconnect())
    else:
        _LOG.debug(
            "Adding new device: %s (%s) %s",
            device_config.identifier,
            device_config.name,
            device_config.address,
        )
        device = tv.SamsungTv(device_config, loop=_LOOP)
        device.events.on(tv.EVENTS.CONNECTED, on_device_connected)
        device.events.on(tv.EVENTS.DISCONNECTED, on_device_disconnected)
        device.events.on(tv.EVENTS.ERROR, on_device_connection_error)
        device.events.on(tv.EVENTS.UPDATE, on_device_update)

        _configured_devices[device.identifier] = device
        # device.check_power_status()

    async def start_connection():
        await device.connect()

    if connect:
        # start background task
        _LOOP.create_task(start_connection())

    _register_available_entities(device_config, device)


def _register_available_entities(
    device_config: SamsungDevice, device: tv.SamsungTv
) -> bool:
    """
    Add a new device to the available entities.

    :param identifier: identifier
    :param name: Friendly name
    :return: True if added, False if the device was already in storage.
    """
    _LOG.info("_register_available_entities for %s", device_config.name)
    entities = [SamsungMediaPlayer(device_config, device)]
    for entity in entities:
        if api.available_entities.contains(entity.id):
            api.available_entities.remove(entity.id)
        api.available_entities.add(entity)
    return True


def on_device_added(device: SamsungDevice) -> None:
    """Handle a newly added device in the configuration."""
    _LOG.debug("New device added: %s", device)
    _add_configured_device(device, connect=False)


def on_device_removed(device: SamsungDevice | None) -> None:
    """Handle a removed device in the configuration."""
    if device is None:
        _LOG.debug(
            "Configuration cleared, disconnecting & removing all configured device instances"
        )
        for device in _configured_devices.values():
            _LOOP.create_task(device.disconnect())
            device.events.remove_all_listeners()
        _configured_devices.clear()
        api.configured_entities.clear()
        api.available_entities.clear()
    else:
        if device.identifier in _configured_devices:
            _LOG.debug("Disconnecting from removed device %s", device.identifier)
            device = _configured_devices.pop(device.identifier)
            _LOOP.create_task(device.disconnect())
            device.events.remove_all_listeners()
            entity_id = device.identifier
            api.configured_entities.remove(entity_id)
            api.available_entities.remove(entity_id)


async def main():
    """Start the Remote Two integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("tv").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("setup").setLevel(level)

    # load paired devices
    config.devices = config.Devices(
        api.config_dir_path, on_device_added, on_device_removed
    )
    # best effort migration (if required): network might not be available during startup
    # await config.devices.migrate()

    for device_config in config.devices.all():
        _add_configured_device(device_config)

    await api.init("driver.json", setup.driver_setup_handler)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
