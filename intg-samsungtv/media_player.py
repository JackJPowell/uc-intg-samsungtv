"""
Media-player entity functions.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any
import asyncio
import ucapi
import ucapi.api as uc

import tv
from config import SamsungDevice, create_entity_id
from const import SimpleCommands
from ucapi import MediaPlayer, media_player, EntityTypes
from ucapi.media_player import DeviceClasses

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

_LOG = logging.getLogger(__name__)
api = uc.IntegrationAPI(_LOOP)
_configured_devices: dict[str, tv.SamsungTv] = {}

features = [
    media_player.Features.ON_OFF,
    media_player.Features.VOLUME_UP_DOWN,
    media_player.Features.MUTE_TOGGLE,
    media_player.Features.HOME,
    media_player.Features.DPAD,
    media_player.Features.SELECT_SOURCE,
    media_player.Features.MENU,
    media_player.Features.NUMPAD,
    media_player.Features.CHANNEL_SWITCHER,
]


class SamsungMediaPlayer(MediaPlayer):
    """Representation of a Samsung MediaPlayer entity."""

    def __init__(self, config_device: SamsungDevice, device: tv.SamsungTv):
        """Initialize the class."""
        self._device = device
        _LOG.debug("SamsungMediaPlayer init")
        entity_id = create_entity_id(config_device.identifier, EntityTypes.MEDIA_PLAYER)
        entity_id = config_device.identifier
        self.config = config_device

        super().__init__(
            entity_id,
            config_device.name,
            features,
            {
                media_player.Attributes.STATE: media_player.States.UNKNOWN,
                media_player.Attributes.VOLUME: 0,
            },
            device_class=DeviceClasses.TV,
            options={
                media_player.Options.SIMPLE_COMMANDS: [
                    SimpleCommands.EXIT.value,
                    SimpleCommands.CH_LIST.value,
                    SimpleCommands.SLEEP.value,
                ],
            },
            cmd_handler=self.media_player_cmd_handler,
        )

    # pylint: disable=too-many-statements
    async def media_player_cmd_handler(
        self, entity: MediaPlayer, cmd_id: str, params: dict[str, Any] | None
    ) -> ucapi.StatusCodes:
        """
        Media-player entity command handler.

        Called by the integration-API if a command is sent to a configured media-player entity.

        :param entity: media-player entity
        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command. StatusCodes.OK if the command succeeded.
        """
        _LOG.info(
            "Got %s command request: %s %s", entity.id, cmd_id, params if params else ""
        )

        if cmd_id not in [media_player.Commands.ON, media_player.Commands.TOGGLE]:
            await self._device.check_connection_and_reconnect()

        try:
            match cmd_id:
                case media_player.Commands.ON:
                    await self._device.toggle_power(True)
                case media_player.Commands.OFF:
                    await self._device.toggle_power(False)
                case media_player.Commands.TOGGLE:
                    await self._device.toggle_power()
                case media_player.Commands.VOLUME_UP:
                    await self._device.send_key("KEY_VOLUP")
                case media_player.Commands.VOLUME_DOWN:
                    await self._device.send_key("KEY_VOLDOWN")
                # case media_player.Commands.VOLUME:
                #     self._device.volume_set(params.get("volume"))
                case media_player.Commands.MUTE_TOGGLE:
                    await self._device.send_key("KEY_MUTE")
                case media_player.Commands.CHANNEL_DOWN:
                    await self._device.send_key("KEY_CHDOWN")
                case media_player.Commands.CHANNEL_UP:
                    await self._device.send_key("KEY_CHDOWN")
                case media_player.Commands.CURSOR_UP:
                    await self._device.send_key("KEY_UP")
                case media_player.Commands.CURSOR_DOWN:
                    await self._device.send_key("KEY_DOWN")
                case media_player.Commands.CURSOR_LEFT:
                    await self._device.send_key("KEY_LEFT")
                case media_player.Commands.CURSOR_RIGHT:
                    await self._device.send_key("KEY_RIGHT")
                case media_player.Commands.CURSOR_ENTER:
                    await self._device.send_key("KEY_ENTER")
                case media_player.Commands.DIGIT_0:
                    await self._device.send_key("KEY_0")
                case media_player.Commands.DIGIT_1:
                    await self._device.send_key("KEY_1")
                case media_player.Commands.DIGIT_2:
                    await self._device.send_key("KEY_2")
                case media_player.Commands.DIGIT_3:
                    await self._device.send_key("KEY_3")
                case media_player.Commands.DIGIT_4:
                    await self._device.send_key("KEY_4")
                case media_player.Commands.DIGIT_5:
                    await self._device.send_key("KEY_5")
                case media_player.Commands.DIGIT_6:
                    await self._device.send_key("KEY_6")
                case media_player.Commands.DIGIT_7:
                    await self._device.send_key("KEY_7")
                case media_player.Commands.DIGIT_8:
                    await self._device.send_key("KEY_8")
                case media_player.Commands.DIGIT_9:
                    await self._device.send_key("KEY_9")
                case media_player.Commands.FUNCTION_RED:
                    await self._device.send_key("KEY_RED")
                case media_player.Commands.FUNCTION_GREEN:
                    await self._device.send_key("KEY_GREEN")
                case media_player.Commands.FUNCTION_YELLOW:
                    await self._device.send_key("KEY_YELLOW")
                case media_player.Commands.FUNCTION_BLUE:
                    await self._device.send_key("KEY_BLUE")
                case media_player.Commands.HOME:
                    await self._device.send_key("KEY_HOME")
                case media_player.Commands.MENU:
                    await self._device.send_key("KEY_MENU")
                case media_player.Commands.INFO:
                    await self._device.send_key("KEY_INFO")
                case media_player.Commands.GUIDE:
                    await self._device.send_key("KEY_GUIDE")
                case media_player.Commands.BACK:
                    await self._device.send_key("KEY_RETURN")
                case media_player.Commands.SELECT_SOURCE:
                    await self._device.launch_app(app_name=params.get("source"))
                case media_player.Commands.SETTINGS:
                    await self._device.send_key("KEY_TOOLS")
                # --- simple commands ---
                case SimpleCommands.EXIT:
                    await self._device.send_key("KEY_MENU")
                case SimpleCommands.CH_LIST:
                    await self._device.send_key("KEY_CH_LIST")
        except Exception as ex:  # pylint: disable=broad-except
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            return ucapi.StatusCodes.TIMEOUT
        return ucapi.StatusCodes.OK


def _get_cmd_param(name: str, params: dict[str, Any] | None) -> str | bool | None:
    if params is None:
        return None
    return params.get(name)
