"""
Remote entity functions.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
from typing import Any

import ucapi
from config import SamsungDevice, create_entity_id
from ucapi import EntityTypes, Remote, StatusCodes, media_player
from ucapi.media_player import States as MediaStates
from ucapi.remote import Attributes, Commands, Features
from ucapi.remote import States as RemoteStates
from ucapi.ui import DeviceButtonMapping, Buttons
import tv
from const import (
    SimpleCommands,
    key_update_helper,
)

_LOG = logging.getLogger(__name__)

SAMSUNG_REMOTE_STATE_MAPPING = {
    MediaStates.UNKNOWN: RemoteStates.UNKNOWN,
    MediaStates.UNAVAILABLE: RemoteStates.UNAVAILABLE,
    MediaStates.OFF: RemoteStates.OFF,
    MediaStates.ON: RemoteStates.ON,
}


class SamsungRemote(Remote):
    """Representation of a Samsung Remote entity."""

    def __init__(self, config_device: SamsungDevice, device: tv.SamsungTv):
        """Initialize the class."""
        self._device: tv.SamsungTv = device
        _LOG.debug("Samsung Remote init")
        entity_id = create_entity_id(config_device.identifier, EntityTypes.REMOTE)
        features = [Features.SEND_CMD, Features.ON_OFF, Features.TOGGLE]
        attributes = {
            Attributes.STATE: SAMSUNG_REMOTE_STATE_MAPPING.get(device.state),
        }
        super().__init__(
            entity_id,
            f"{config_device.name} Remote",
            features,
            attributes,
            simple_commands=SAMSUNG_REMOTE_SIMPLE_COMMANDS,
            button_mapping=SAMSUNG_REMOTE_BUTTONS_MAPPING,
            ui_pages=SAMSUNG_REMOTE_UI_PAGES,
            cmd_handler=self.command
        )

    def get_int_param(self, param: str, params: dict[str, Any], default: int):
        """Get parameter in integer format."""
        value = params.get(param, default)
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
        _LOG.info("Got %s command request: %s %s", self.id, cmd_id, params)

        if self._device is None:
            _LOG.warning("No Samsung instance for entity: %s", self.id)
            return StatusCodes.SERVICE_UNAVAILABLE

        repeat = self.get_int_param("repeat", params, 1)

        for _i in range(0, repeat):
            await self.handle_command(cmd_id, params)
        return StatusCodes.OK

    async def handle_command(
        self, cmd_id: str, params: dict[str, Any] | None = None
    ) -> StatusCodes:
        """Handle command."""
        #hold = self.get_int_param("hold", params, 0)
        delay = self.get_int_param("delay", params, 0)
        command = params.get("command", "")

        client = self._device
        res = None
        try:
            if command == 'remote.on':
                await client.toggle_power(True)
            elif command == 'remote.off':
                await client.toggle_power(False)
            elif command == 'remote.toggle':
                await client.toggle_power()
            elif cmd_id == Commands.SEND_CMD:
                match command:
                    case media_player.Commands.ON:
                        await client.toggle_power(True)
                    case media_player.Commands.OFF:
                        await client.toggle_power(False)
                    case media_player.Commands.TOGGLE:
                        await client.toggle_power()
                    case media_player.Commands.VOLUME_UP:
                        await client.send_key("KEY_VOLUP")
                    case media_player.Commands.VOLUME_DOWN:
                        await client.send_key("KEY_VOLDOWN")
                    case media_player.Commands.MUTE_TOGGLE:
                        await client.send_key("KEY_MUTE")
                    case media_player.Commands.CHANNEL_DOWN:
                        await client.send_key("KEY_CHDOWN")
                    case media_player.Commands.CHANNEL_UP:
                        await client.send_key("KEY_CHDOWN")
                    case media_player.Commands.CURSOR_UP:
                        await client.send_key("KEY_UP")
                    case media_player.Commands.CURSOR_DOWN:
                        await client.send_key("KEY_DOWN")
                    case media_player.Commands.CURSOR_LEFT:
                        await client.send_key("KEY_LEFT")
                    case media_player.Commands.CURSOR_RIGHT:
                        await client.send_key("KEY_RIGHT")
                    case media_player.Commands.CURSOR_ENTER:
                        await client.send_key("KEY_ENTER")
                    case media_player.Commands.DIGIT_0:
                        await client.send_key("KEY_0")
                    case media_player.Commands.DIGIT_1:
                        await client.send_key("KEY_1")
                    case media_player.Commands.DIGIT_2:
                        await client.send_key("KEY_2")
                    case media_player.Commands.DIGIT_3:
                        await client.send_key("KEY_3")
                    case media_player.Commands.DIGIT_4:
                        await client.send_key("KEY_4")
                    case media_player.Commands.DIGIT_5:
                        await client.send_key("KEY_5")
                    case media_player.Commands.DIGIT_6:
                        await client.send_key("KEY_6")
                    case media_player.Commands.DIGIT_7:
                        await client.send_key("KEY_7")
                    case media_player.Commands.DIGIT_8:
                        await client.send_key("KEY_8")
                    case media_player.Commands.DIGIT_9:
                        await client.send_key("KEY_9")
                    case media_player.Commands.FUNCTION_RED:
                        await client.send_key("KEY_RED")
                    case media_player.Commands.FUNCTION_GREEN:
                        await client.send_key("KEY_GREEN")
                    case media_player.Commands.FUNCTION_YELLOW:
                        await client.send_key("KEY_YELLOW")
                    case media_player.Commands.FUNCTION_BLUE:
                        await client.send_key("KEY_BLUE")
                    case media_player.Commands.HOME:
                        await client.send_key("KEY_HOME")
                    case media_player.Commands.MENU:
                        await client.send_key("KEY_MENU")
                    case media_player.Commands.INFO:
                        await client.send_key("KEY_INFO")
                    case media_player.Commands.GUIDE:
                        await client.send_key("KEY_GUIDE")
                    case media_player.Commands.BACK:
                        await client.send_key("KEY_RETURN")
                    case media_player.Commands.SELECT_SOURCE:
                        await client.launch_app(app_name=params.get("source"))
                    case media_player.Commands.SETTINGS:
                        await client.send_key("KEY_TOOLS")
                    case SimpleCommands.EXIT:
                        await client.send_key("KEY_MENU")
                    case SimpleCommands.CH_LIST:
                        await client.send_key("KEY_CH_LIST")
                    case SimpleCommands.HDMI_1:
                        await client.send_key("KEY_HDMI1")
                    case SimpleCommands.HDMI_2:
                        await client.send_key("KEY_HDMI2")
                    case SimpleCommands.HDMI_3:
                        await client.send_key("KEY_HDMI3")
                    case SimpleCommands.HDMI_4:
                        await client.send_key("KEY_HDMI4")
                res = StatusCodes.OK
            elif cmd_id == Commands.SEND_CMD_SEQUENCE:
                commands = params.get("sequence", [])
                res = StatusCodes.OK
                for command in commands:
                    res = await self.handle_command(Commands.SEND_CMD, {"command": command, "params": params})
                    if delay > 0:
                        await asyncio.sleep(delay)
            else:
                return StatusCodes.NOT_IMPLEMENTED
            if delay > 0 and cmd_id != Commands.SEND_CMD_SEQUENCE:
                await asyncio.sleep(delay)
            return res
        except Exception as ex:  # pylint: disable=broad-except
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            return ucapi.StatusCodes.OK


    def filter_changed_attributes(self, update: dict[str, Any]) -> dict[str, Any]:
        """
        Filter the given attributes and return only the changed values.

        :param update: dictionary with attributes.
        :return: filtered entity attributes containing changed attributes only.
        """
        attributes = {}

        if Attributes.STATE in update:
            state = SAMSUNG_REMOTE_STATE_MAPPING.get(update[Attributes.STATE])
            attributes = key_update_helper(
                self.attributes, Attributes.STATE, state, attributes
            )

        _LOG.debug("Samsung Remote update attributes %s -> %s", update, attributes)
        return attributes


SAMSUNG_REMOTE_SIMPLE_COMMANDS = [
                    SimpleCommands.EXIT.value,
                    SimpleCommands.CH_LIST.value,
                    SimpleCommands.SLEEP.value,
                    SimpleCommands.HDMI_1.value,
                    SimpleCommands.HDMI_2.value,
                    SimpleCommands.HDMI_3.value,
                    SimpleCommands.HDMI_4.value,
                ]
SAMSUNG_REMOTE_BUTTONS_MAPPING: [DeviceButtonMapping] = [
    {"button": Buttons.BACK, "short_press": {"cmd_id": media_player.Commands.BACK}},
    {"button": Buttons.HOME, "short_press": {"cmd_id": media_player.Commands.HOME}},
    {"button": Buttons.CHANNEL_DOWN, "short_press": {"cmd_id": media_player.Commands.CURSOR_ENTER}},
    {"button": Buttons.CHANNEL_UP, "short_press": {"cmd_id": media_player.Commands.CHANNEL_UP}},
    {"button": Buttons.DPAD_UP, "short_press": {"cmd_id": media_player.Commands.CURSOR_UP}},
    {"button": Buttons.DPAD_DOWN, "short_press": {"cmd_id": media_player.Commands.CURSOR_DOWN}},
    {"button": Buttons.DPAD_LEFT, "short_press": {"cmd_id": media_player.Commands.CURSOR_LEFT}},
    {"button": Buttons.DPAD_RIGHT, "short_press": {"cmd_id": media_player.Commands.CURSOR_RIGHT}},
    {"button": Buttons.DPAD_MIDDLE, "short_press": {"cmd_id": media_player.Commands.CURSOR_ENTER}},
    {"button": Buttons.VOLUME_UP, "short_press": {"cmd_id": media_player.Commands.VOLUME_UP}},
    {"button": Buttons.VOLUME_DOWN, "short_press": {"cmd_id": media_player.Commands.VOLUME_DOWN}},
    {"button": Buttons.MUTE, "short_press": {"cmd_id": media_player.Commands.MUTE_TOGGLE}},
    {"button": Buttons.YELLOW, "short_press": {"cmd_id": media_player.Commands.FUNCTION_YELLOW}},
    {"button": Buttons.GREEN, "short_press": {"cmd_id": media_player.Commands.FUNCTION_GREEN}},
    {"button": Buttons.RED, "short_press": {"cmd_id": media_player.Commands.FUNCTION_RED}},
    {"button": Buttons.BLUE, "short_press": {"cmd_id": media_player.Commands.FUNCTION_BLUE}},
    {"button": Buttons.POWER, "short_press": {"cmd_id": media_player.Commands.TOGGLE}}
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
                    "params": {"command": media_player.Commands.TOGGLE, "repeat": 1}
                },
                "icon": "uc:power-on",
                "location": {
                    "x": 0,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.INFO, "repeat": 1}
                },
                "icon": "uc:info",
                "location": {
                    "x": 1,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.SETTINGS, "repeat": 1}
                },
                "text": "Settings",
                "location": {
                    "x": 2,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.MENU, "repeat": 1}
                },
                "icon": "uc:menu",
                "location": {
                    "x": 0,
                    "y": 1,
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.GUIDE, "repeat": 1}
                },
                "icon": "uc:guide",
                "location": {
                    "x": 1,
                    "y": 1,
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
                        {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": SimpleCommands.CH_LIST, "repeat": 1}
                },
                "text": "CH List",
                "location": {
                    "x": 2,
                    "y": 1,
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.FUNCTION_BLUE, "repeat": 1}
                },
                "text": "YELLOW",
                "location": {
                    "x": 0,
                    "y": 2
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.FUNCTION_GREEN, "repeat": 1}
                },
                "text": "GREEN",
                "location": {
                    "x": 2,
                    "y": 2
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.FUNCTION_RED, "repeat": 1}
                },
                "text": "RED",
                "location": {
                    "x": 0,
                    "y": 3
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.FUNCTION_YELLOW, "repeat": 1}
                },
                "text": "YELLOW",
                "location": {
                    "x": 2,
                    "y": 3
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": SimpleCommands.HDMI_1, "repeat": 1}
                },
                "text": "HDMI 1",
                "location": {
                    "x": 0,
                    "y": 4
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": SimpleCommands.HDMI_2, "repeat": 1}
                },
                "text": "HDMI 2",
                "location": {
                    "x": 1,
                    "y": 4
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": SimpleCommands.HDMI_3, "repeat": 1}
                },
                "text": "HDMI 3",
                "location": {
                    "x": 2,
                    "y": 4
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": SimpleCommands.HDMI_4, "repeat": 1}
                },
                "text": "HDMI 4",
                "location": {
                    "x": 3,
                    "y": 4
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.CHANNEL_UP, "repeat": 1}
                },
                "icon": "uc:up-arrow",
                "location": {
                    "x": 3,
                    "y": 5
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.CHANNEL_DOWN, "repeat": 1}
                },
                "icon": "uc:down-arrow",
                "location": {
                    "x": 3,
                    "y": 6
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.MUTE_TOGGLE, "repeat": 1}
                },
                "icon": "uc:mute",
                "location": {
                    "x": 1,
                    "y": 5
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.VOLUME_DOWN, "repeat": 1}
                },
                "icon": "uc:minus",
                "location": {
                    "x": 0,
                    "y": 6
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": media_player.Commands.VOLUME_UP, "repeat": 1}
                },
                "icon": "uc:plus",
                "location": {
                    "x": 0,
                    "y": 5
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
        ]
    },
    {
        "page_id": "TV numbers",
        "name": "TV numbers",
        "grid": {"height": 4, "width": 3},
        "items": [{
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_1, "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "1",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_2, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "2",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_3, "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "3",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_4, "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "4",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_5, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "5",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_6, "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "6",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_7, "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "7",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_8, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "8",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_9, "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "9",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.DIGIT_0, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 3
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "0",
            "type": "text"
        }
        ]
    },
    {
        "page_id": "TV direction pad",
        "name": "TV direction pad",
        "grid": {"height": 3, "width": 3},
        "items": [{
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.BACK, "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:back",
            "type": "icon"
        },{
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.CURSOR_UP, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:up-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.HOME, "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:home",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.CURSOR_LEFT, "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:left-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.CURSOR_ENTER, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "OK",
            "type": "text"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.CURSOR_RIGHT, "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:right-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.CURSOR_DOWN, "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:down-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": media_player.Commands.BACK, "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "Exit",
            "type": "text"
        },
        ]
    }
]
