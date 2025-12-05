"""
Remote entity functions.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
from typing import Any

import ucapi
from const import SamsungConfig, SimpleCommands
from tv import SamsungTv
from ucapi import EntityTypes, Remote, StatusCodes, media_player
from ucapi.media_player import States as MediaStates
from ucapi.remote import Attributes, Commands, Features
from ucapi.remote import States as RemoteStates
from ucapi.ui import Buttons, DeviceButtonMapping
from ucapi_framework import create_entity_id

_LOG = logging.getLogger(__name__)

SAMSUNG_REMOTE_STATE_MAPPING = {
    MediaStates.UNKNOWN: RemoteStates.UNKNOWN,
    MediaStates.UNAVAILABLE: RemoteStates.UNAVAILABLE,
    MediaStates.OFF: RemoteStates.OFF,
    MediaStates.ON: RemoteStates.ON,
}


class SamsungRemote(Remote):
    """Representation of a Samsung Remote entity."""

    def __init__(self, config_device: SamsungConfig, device: SamsungTv):
        """Initialize the class."""
        self._device = device
        _LOG.debug("Samsung Remote init")
        entity_id = create_entity_id(EntityTypes.REMOTE, config_device.identifier)
        features = [Features.SEND_CMD, Features.ON_OFF, Features.TOGGLE]
        super().__init__(
            entity_id,
            f"{config_device.name} Remote",
            features,
            attributes={
                Attributes.STATE: device.state,
            },
            simple_commands=SAMSUNG_REMOTE_SIMPLE_COMMANDS,
            button_mapping=SAMSUNG_REMOTE_BUTTONS_MAPPING,
            ui_pages=SAMSUNG_REMOTE_UI_PAGES,
            cmd_handler=self.command,
        )

    def get_int_param(self, param: str, params: dict[str, Any], default: int):
        """Get parameter in integer format."""
        try:
            value = params.get(param, default)
        except AttributeError:
            return default

        if isinstance(value, str) and len(value) > 0:
            return int(float(value))
        return default

    async def command(
        self, cmd_id: str, params: dict[str, Any] | None = None
    ) -> StatusCodes:
        """
        Remote entity command handler.

        Called by the integration-API if a command is sent to a configured remote entity.

        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command request
        """
        repeat = 1
        _LOG.info("Got %s command request: %s %s", self.id, cmd_id, params)

        if self._device is None:
            _LOG.warning("No Samsung instance for entity: %s", self.id)
            return StatusCodes.SERVICE_UNAVAILABLE

        if params:
            repeat = self.get_int_param("repeat", params, 1)

        for _i in range(0, repeat):
            await self.handle_command(cmd_id, params)
        return StatusCodes.OK

    async def handle_command(
        self, cmd_id: str, params: dict[str, Any] | None = None
    ) -> StatusCodes:
        """Handle command."""
        command: str = ""
        delay = 0
        hold = None
        repeat = 1

        client = self._device
        res = None

        match cmd_id:
            case Commands.ON:
                await client.toggle_power(True)
            case Commands.OFF:
                await client.toggle_power(False)
            case Commands.TOGGLE:
                await client.toggle_power()

        if params is None:
            return StatusCodes.BAD_REQUEST

        command = params.get("command", "")
        delay = params.get("delay", 0)
        hold = params.get("hold", None)
        repeat = self.get_int_param("repeat", params, 1)

        if isinstance(command, str) is True:
            command = command.lower()

        try:
            if cmd_id == Commands.SEND_CMD:
                if command.startswith("app_"):
                    await client.launch_app(app_id=command[4:])
                else:
                    match command:
                        case SimpleCommands.STANDBY | SimpleCommands.STANDBY.value:
                            await client.send_key("KEY_POWER", hold_time=2000)
                        case (
                            media_player.Commands.VOLUME_UP
                            | media_player.Commands.VOLUME_UP.value
                        ):
                            await client.send_key("KEY_VOLUP", hold_time=hold)
                        case (
                            media_player.Commands.VOLUME_DOWN
                            | media_player.Commands.VOLUME_DOWN.value
                        ):
                            await client.send_key("KEY_VOLDOWN", hold_time=hold)
                        case (
                            media_player.Commands.MUTE_TOGGLE
                            | media_player.Commands.MUTE_TOGGLE.value
                        ):
                            await client.send_key("KEY_MUTE", hold_time=hold)
                        case (
                            media_player.Commands.CHANNEL_DOWN
                            | media_player.Commands.CHANNEL_DOWN.value
                        ):
                            await client.send_key("KEY_CHDOWN", hold_time=hold)
                        case (
                            media_player.Commands.CHANNEL_UP
                            | media_player.Commands.CHANNEL_UP.value
                        ):
                            await client.send_key("KEY_CHUP", hold_time=hold)
                        case (
                            media_player.Commands.CURSOR_UP
                            | media_player.Commands.CURSOR_UP.value
                        ):
                            await client.send_key("KEY_UP", hold_time=hold)
                        case (
                            media_player.Commands.CURSOR_DOWN
                            | media_player.Commands.CURSOR_DOWN.value
                        ):
                            await client.send_key("KEY_DOWN", hold_time=hold)
                        case (
                            media_player.Commands.CURSOR_LEFT
                            | media_player.Commands.CURSOR_LEFT.value
                        ):
                            await client.send_key("KEY_LEFT", hold_time=hold)
                        case (
                            media_player.Commands.CURSOR_RIGHT
                            | media_player.Commands.CURSOR_RIGHT.value
                        ):
                            await client.send_key("KEY_RIGHT", hold_time=hold)
                        case (
                            media_player.Commands.CURSOR_ENTER
                            | media_player.Commands.CURSOR_ENTER.value
                            | "enter"
                        ):
                            await client.send_key("KEY_ENTER", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_0
                            | media_player.Commands.DIGIT_0.value
                            | "0"
                        ):
                            await client.send_key("KEY_0", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_1
                            | media_player.Commands.DIGIT_1.value
                            | "1"
                        ):
                            await client.send_key("KEY_1", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_2
                            | media_player.Commands.DIGIT_2.value
                            | "2"
                        ):
                            await client.send_key("KEY_2", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_3
                            | media_player.Commands.DIGIT_3.value
                            | "3"
                        ):
                            await client.send_key("KEY_3", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_4
                            | media_player.Commands.DIGIT_4.value
                            | "4"
                        ):
                            await client.send_key("KEY_4", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_5
                            | media_player.Commands.DIGIT_5.value
                            | "5"
                        ):
                            await client.send_key("KEY_5", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_6
                            | media_player.Commands.DIGIT_6.value
                            | "6"
                        ):
                            await client.send_key("KEY_6", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_7
                            | media_player.Commands.DIGIT_7.value
                            | "7"
                        ):
                            await client.send_key("KEY_7", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_8
                            | media_player.Commands.DIGIT_8.value
                            | "8"
                        ):
                            await client.send_key("KEY_8", hold_time=hold)
                        case (
                            media_player.Commands.DIGIT_9
                            | media_player.Commands.DIGIT_9.value
                            | "9"
                        ):
                            await client.send_key("KEY_9", hold_time=hold)
                        case (
                            media_player.Commands.HOME
                            | media_player.Commands.HOME.value
                        ):
                            await client.send_key("KEY_HOME", hold_time=hold)
                        case (
                            media_player.Commands.MENU
                            | media_player.Commands.MENU.value
                        ):
                            await client.send_key("KEY_MENU", hold_time=hold)
                        case (
                            media_player.Commands.INFO
                            | media_player.Commands.INFO.value
                        ):
                            await client.send_key("KEY_INFO", hold_time=hold)
                        case (
                            media_player.Commands.GUIDE
                            | media_player.Commands.GUIDE.value
                        ):
                            await client.send_key("KEY_GUIDE", hold_time=hold)
                        case (
                            media_player.Commands.BACK
                            | media_player.Commands.BACK.value
                        ):
                            await client.send_key("KEY_RETURN", hold_time=hold)
                        case (
                            media_player.Commands.PLAY_PAUSE
                            | media_player.Commands.PLAY_PAUSE.value
                        ):
                            await client.send_key("KEY_PLAY_BACK", hold_time=hold)
                        case (
                            media_player.Commands.SELECT_SOURCE
                            | media_player.Commands.SELECT_SOURCE.value
                        ):
                            await client.launch_app(app_name=params.get("source"))
                        case (
                            media_player.Commands.SETTINGS
                            | media_player.Commands.SETTINGS.value
                        ):
                            await client.send_key("KEY_TOOLS", hold_time=hold)
                        case (
                            media_player.Commands.FUNCTION_RED
                            | media_player.Commands.FUNCTION_RED.value
                        ):
                            await self._device.send_key("KEY_RED", hold_time=hold)
                        case (
                            media_player.Commands.FUNCTION_GREEN
                            | media_player.Commands.FUNCTION_GREEN.value
                        ):
                            await self._device.send_key("KEY_GREEN", hold_time=hold)
                        case (
                            media_player.Commands.FUNCTION_YELLOW
                            | media_player.Commands.FUNCTION_YELLOW.value
                        ):
                            await self._device.send_key("KEY_YELLOW", hold_time=hold)
                        case (
                            media_player.Commands.FUNCTION_BLUE
                            | media_player.Commands.FUNCTION_BLUE.value
                        ):
                            await self._device.send_key("KEY_BLUE", hold_time=hold)
                        case SimpleCommands.EXIT | SimpleCommands.EXIT.value:
                            await client.send_key("KEY_EXIT", hold_time=hold)
                        case SimpleCommands.CH_LIST | SimpleCommands.CH_LIST.value:
                            await client.send_key("KEY_CH_LIST", hold_time=hold)
                        case (
                            SimpleCommands.DEVICE_INFO
                            | SimpleCommands.DEVICE_INFO.value
                        ):
                            client.get_device_info()
                        case SimpleCommands.ART_INFO | SimpleCommands.ART_INFO.value:
                            client.get_art_info()
                        case (
                            SimpleCommands.ART_MODE_ON
                            | SimpleCommands.ART_MODE_ON.value
                        ):
                            client.toggle_art_mode(True)
                        case (
                            SimpleCommands.ART_MODE_OFF
                            | SimpleCommands.ART_MODE_OFF.value
                        ):
                            client.toggle_art_mode(False)
                        case (
                            SimpleCommands.FORCE_POWER
                            | SimpleCommands.FORCE_POWER.value
                        ):
                            await client.send_key("KEY_POWER", hold_time=hold)
                res = StatusCodes.OK
            elif cmd_id == Commands.SEND_CMD_SEQUENCE:
                res = StatusCodes.OK
                for command in params.get("sequence", []):
                    for _ in range(0, repeat):
                        res = await self.handle_command(
                            Commands.SEND_CMD, {"command": command, "params": params}
                        )
                    if delay > 0:
                        await asyncio.sleep(float(delay) / 1000)
            else:
                return StatusCodes.NOT_IMPLEMENTED
            return res
        except Exception as ex:  # pylint: disable=broad-except
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            return ucapi.StatusCodes.OK


SAMSUNG_REMOTE_SIMPLE_COMMANDS = [
    SimpleCommands.EXIT.value,
    SimpleCommands.CH_LIST.value,
    SimpleCommands.SLEEP.value,
    SimpleCommands.DEVICE_INFO.value,
    SimpleCommands.ART_INFO.value,
    SimpleCommands.ART_MODE_ON.value,
    SimpleCommands.ART_MODE_OFF.value,
    SimpleCommands.STANDBY.value,
    SimpleCommands.FORCE_POWER.value,
]
SAMSUNG_REMOTE_BUTTONS_MAPPING: list[DeviceButtonMapping] = [
    {"button": Buttons.BACK, "short_press": {"cmd_id": media_player.Commands.BACK}},
    {"button": Buttons.HOME, "short_press": {"cmd_id": media_player.Commands.HOME}},
    {
        "button": Buttons.CHANNEL_DOWN,
        "short_press": {"cmd_id": media_player.Commands.CHANNEL_DOWN},
    },
    {
        "button": Buttons.CHANNEL_UP,
        "short_press": {"cmd_id": media_player.Commands.CHANNEL_UP},
    },
    {
        "button": Buttons.DPAD_UP,
        "short_press": {"cmd_id": media_player.Commands.CURSOR_UP},
    },
    {
        "button": Buttons.DPAD_DOWN,
        "short_press": {"cmd_id": media_player.Commands.CURSOR_DOWN},
    },
    {
        "button": Buttons.DPAD_LEFT,
        "short_press": {"cmd_id": media_player.Commands.CURSOR_LEFT},
    },
    {
        "button": Buttons.DPAD_RIGHT,
        "short_press": {"cmd_id": media_player.Commands.CURSOR_RIGHT},
    },
    {
        "button": Buttons.DPAD_MIDDLE,
        "short_press": {"cmd_id": media_player.Commands.CURSOR_ENTER},
    },
    {
        "button": Buttons.VOLUME_UP,
        "short_press": {"cmd_id": media_player.Commands.VOLUME_UP},
    },
    {
        "button": Buttons.VOLUME_DOWN,
        "short_press": {"cmd_id": media_player.Commands.VOLUME_DOWN},
    },
    {
        "button": Buttons.MUTE,
        "short_press": {"cmd_id": media_player.Commands.MUTE_TOGGLE},
    },
    {
        "button": Buttons.YELLOW,
        "short_press": {"cmd_id": media_player.Commands.FUNCTION_YELLOW},
    },
    {
        "button": Buttons.GREEN,
        "short_press": {"cmd_id": media_player.Commands.FUNCTION_GREEN},
    },
    {
        "button": Buttons.RED,
        "short_press": {"cmd_id": media_player.Commands.FUNCTION_RED},
    },
    {
        "button": Buttons.BLUE,
        "short_press": {"cmd_id": media_player.Commands.FUNCTION_BLUE},
    },
    {"button": Buttons.POWER, "short_press": {"cmd_id": media_player.Commands.TOGGLE}},
]

SAMSUNG_REMOTE_UI_PAGES = [
    {
        "page_id": "Samsung commands",
        "name": "TV commands",
        "grid": {"width": 4, "height": 7},
        "items": [
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.TOGGLE, "repeat": 1},
                },
                "icon": "uc:power-on",
                "location": {"x": 0, "y": 0},
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.INFO, "repeat": 1},
                },
                "icon": "uc:info",
                "location": {"x": 1, "y": 0},
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.SETTINGS, "repeat": 1},
                },
                "text": "Settings",
                "location": {"x": 2, "y": 0},
                "size": {"height": 1, "width": 2},
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.MENU, "repeat": 1},
                },
                "icon": "uc:menu",
                "location": {
                    "x": 0,
                    "y": 1,
                },
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.GUIDE, "repeat": 1},
                },
                "icon": "uc:guide",
                "location": {
                    "x": 1,
                    "y": 1,
                },
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": SimpleCommands.CH_LIST, "repeat": 1},
                },
                "text": "CH List",
                "location": {
                    "x": 2,
                    "y": 1,
                },
                "size": {"height": 1, "width": 2},
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.FUNCTION_BLUE,
                        "repeat": 1,
                    },
                },
                "text": "YELLOW",
                "location": {"x": 0, "y": 2},
                "size": {"height": 1, "width": 2},
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.FUNCTION_GREEN,
                        "repeat": 1,
                    },
                },
                "text": "GREEN",
                "location": {"x": 2, "y": 2},
                "size": {"height": 1, "width": 2},
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.FUNCTION_RED,
                        "repeat": 1,
                    },
                },
                "text": "RED",
                "location": {"x": 0, "y": 3},
                "size": {"height": 1, "width": 2},
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.FUNCTION_YELLOW,
                        "repeat": 1,
                    },
                },
                "text": "YELLOW",
                "location": {"x": 2, "y": 3},
                "size": {"height": 1, "width": 2},
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.CHANNEL_UP,
                        "repeat": 1,
                    },
                },
                "icon": "uc:up-arrow",
                "location": {"x": 3, "y": 5},
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.CHANNEL_DOWN,
                        "repeat": 1,
                    },
                },
                "icon": "uc:down-arrow",
                "location": {"x": 3, "y": 6},
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.MUTE_TOGGLE,
                        "repeat": 1,
                    },
                },
                "icon": "uc:mute",
                "location": {"x": 1, "y": 5},
                "size": {"height": 1, "width": 2},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": SimpleCommands.ART_MODE_ON,
                        "repeat": 1,
                    },
                },
                "icon": "uc:frame",
                "location": {"x": 1, "y": 6},
                "size": {"height": 1, "width": 2},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.VOLUME_DOWN,
                        "repeat": 1,
                    },
                },
                "icon": "uc:minus",
                "location": {"x": 0, "y": 6},
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.VOLUME_UP, "repeat": 1},
                },
                "icon": "uc:plus",
                "location": {"x": 0, "y": 5},
                "size": {"height": 1, "width": 1},
                "type": "icon",
            },
        ],
    },
    {
        "page_id": "TV numbers",
        "name": "TV numbers",
        "grid": {"height": 4, "width": 3},
        "items": [
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_1, "repeat": 1},
                },
                "location": {"x": 0, "y": 0},
                "size": {"height": 1, "width": 1},
                "text": "1",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_2, "repeat": 1},
                },
                "location": {"x": 1, "y": 0},
                "size": {"height": 1, "width": 1},
                "text": "2",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_3, "repeat": 1},
                },
                "location": {"x": 2, "y": 0},
                "size": {"height": 1, "width": 1},
                "text": "3",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_4, "repeat": 1},
                },
                "location": {"x": 0, "y": 1},
                "size": {"height": 1, "width": 1},
                "text": "4",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_5, "repeat": 1},
                },
                "location": {"x": 1, "y": 1},
                "size": {"height": 1, "width": 1},
                "text": "5",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_6, "repeat": 1},
                },
                "location": {"x": 2, "y": 1},
                "size": {"height": 1, "width": 1},
                "text": "6",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_7, "repeat": 1},
                },
                "location": {"x": 0, "y": 2},
                "size": {"height": 1, "width": 1},
                "text": "7",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_8, "repeat": 1},
                },
                "location": {"x": 1, "y": 2},
                "size": {"height": 1, "width": 1},
                "text": "8",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_9, "repeat": 1},
                },
                "location": {"x": 2, "y": 2},
                "size": {"height": 1, "width": 1},
                "text": "9",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.DIGIT_0, "repeat": 1},
                },
                "location": {"x": 1, "y": 3},
                "size": {"height": 1, "width": 1},
                "text": "0",
                "type": "text",
            },
        ],
    },
    {
        "page_id": "TV direction pad",
        "name": "TV direction pad",
        "grid": {"height": 3, "width": 3},
        "items": [
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.BACK, "repeat": 1},
                },
                "location": {"x": 0, "y": 0},
                "size": {"height": 1, "width": 1},
                "icon": "uc:back",
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.CURSOR_UP, "repeat": 1},
                },
                "location": {"x": 1, "y": 0},
                "size": {"height": 1, "width": 1},
                "icon": "uc:up-arrow",
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.HOME, "repeat": 1},
                },
                "location": {"x": 2, "y": 0},
                "size": {"height": 1, "width": 1},
                "icon": "uc:home",
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.CURSOR_LEFT,
                        "repeat": 1,
                    },
                },
                "location": {"x": 0, "y": 1},
                "size": {"height": 1, "width": 1},
                "icon": "uc:left-arrow",
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.CURSOR_ENTER,
                        "repeat": 1,
                    },
                },
                "location": {"x": 1, "y": 1},
                "size": {"height": 1, "width": 1},
                "text": "OK",
                "type": "text",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.CURSOR_RIGHT,
                        "repeat": 1,
                    },
                },
                "location": {"x": 2, "y": 1},
                "size": {"height": 1, "width": 1},
                "icon": "uc:right-arrow",
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {
                        "command": media_player.Commands.CURSOR_DOWN,
                        "repeat": 1,
                    },
                },
                "location": {"x": 1, "y": 2},
                "size": {"height": 1, "width": 1},
                "icon": "uc:down-arrow",
                "type": "icon",
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.BACK, "repeat": 1},
                },
                "location": {"x": 2, "y": 2},
                "size": {"height": 1, "width": 1},
                "text": "Exit",
                "type": "text",
            },
        ],
    },
]
