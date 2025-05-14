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
    media_player.Features.VOLUME,
    media_player.Features.VOLUME_UP_DOWN,
    media_player.Features.MUTE_TOGGLE,
    media_player.Features.PLAY_PAUSE,
    media_player.Features.STOP,
    media_player.Features.HOME,
    media_player.Features.CHANNEL_SWITCHER,
    media_player.Features.DPAD,
    media_player.Features.SELECT_SOURCE,
    media_player.Features.MENU,
    media_player.Features.REWIND,
    media_player.Features.FAST_FORWARD,
]


class SamsungMediaPlayer(MediaPlayer):
    def __init__(self, config_device: SamsungDevice, device: tv.SamsungDevice):
        """Initialize the class."""
        self._device: tv.SamsungDevice = device
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

        # If the entity is OFF (device is in standby), we turn it on regardless of the actual command
        # if self._device.is_on is None or self._device.is_on is False:
        #     _LOG.debug("Device not connected, reconnect")
        #     await self._device._samsungtv.shortcuts().power()

        # Only proceed if device connection is established
        # if self._device.is_on is False:
        #     return ucapi.StatusCodes.SERVICE_UNAVAILABLE

        res = ucapi.StatusCodes.BAD_REQUEST

        try:
            match cmd_id:
                case media_player.Commands.ON:
                    await self._device.toggle_power(True)
                case media_player.Commands.OFF:
                    await self._device.toggle_power(False)
                case media_player.Commands.TOGGLE:
                    await self._device.toggle_power()
                # case media_player.Commands.PLAY_PAUSE:
                #     self._device._samsungtv.shortcuts().play_pause()
                # case media_player.Commands.STOP:
                #     await self._device.stop()
                # case media_player.Commands.NEXT:
                #     await self._device.next()
                # case media_player.Commands.PREVIOUS:
                #     await self._device.previous()
                # case media_player.Commands.REWIND:
                #     await self._device.rewind()
                # case media_player.Commands.FAST_FORWARD:
                #     await self._device.fast_forward()
                case media_player.Commands.VOLUME_UP:
                    self._device._samsungtv.shortcuts().volume_up()
                case media_player.Commands.VOLUME_DOWN:
                    self._device._samsungtv.shortcuts().volume_down()
                # case media_player.Commands.VOLUME:
                #     self._device.volume_set(params.get("volume"))
                case media_player.Commands.MUTE_TOGGLE:
                    self._device._samsungtv.shortcuts().mute()
                case media_player.Commands.CHANNEL_DOWN:
                    self._device._samsungtv.shortcuts().channel_down()
                case media_player.Commands.CHANNEL_UP:
                    self._device._samsungtv.shortcuts().channel_up()
                case media_player.Commands.CURSOR_UP:
                    self._device._samsungtv.shortcuts().up()
                case media_player.Commands.CURSOR_DOWN:
                    self._device._samsungtv.shortcuts().down()
                case media_player.Commands.CURSOR_LEFT:
                    self._device._samsungtv.shortcuts().left()
                case media_player.Commands.CURSOR_RIGHT:
                    self._device._samsungtv.shortcuts().right()
                case media_player.Commands.CURSOR_ENTER:
                    self._device._samsungtv.shortcuts().enter()
                case media_player.Commands.DIGIT_0:
                    self._device._samsungtv.shortcuts().digit("0")
                case media_player.Commands.DIGIT_1:
                    self._device._samsungtv.shortcuts().digit("1")
                case media_player.Commands.DIGIT_2:
                    self._device._samsungtv.shortcuts().digit("2")
                case media_player.Commands.DIGIT_3:
                    self._device._samsungtv.shortcuts().digit("3")
                case media_player.Commands.DIGIT_4:
                    self._device._samsungtv.shortcuts().digit("4")
                case media_player.Commands.DIGIT_5:
                    self._device._samsungtv.shortcuts().digit("5")
                case media_player.Commands.DIGIT_6:
                    self._device._samsungtv.shortcuts().digit("6")
                case media_player.Commands.DIGIT_7:
                    self._device._samsungtv.shortcuts().digit("7")
                case media_player.Commands.DIGIT_8:
                    self._device._samsungtv.shortcuts().digit("8")
                case media_player.Commands.DIGIT_9:
                    self._device._samsungtv.shortcuts().digit("9")
                case media_player.Commands.FUNCTION_RED:
                    self._device._samsungtv.shortcuts().red()
                case media_player.Commands.FUNCTION_GREEN:
                    self._device._samsungtv.shortcuts().green()
                case media_player.Commands.FUNCTION_YELLOW:
                    self._device._samsungtv.shortcuts().yellow()
                case media_player.Commands.FUNCTION_BLUE:
                    self._device._samsungtv.shortcuts().blue()
                case media_player.Commands.HOME:
                    self._device._samsungtv.shortcuts().home()
                case media_player.Commands.MENU:
                    self._device._samsungtv.shortcuts().menu()
                case media_player.Commands.INFO:
                    self._device._samsungtv.shortcuts().info()
                case media_player.Commands.GUIDE:
                    self._device._samsungtv.shortcuts().guide()
                case media_player.Commands.BACK:
                    self._device._samsungtv.shortcuts().back()
                case media_player.Commands.SELECT_SOURCE:
                    self._device.launch_app(app_name=params.get("source"))
                # case media_player.Commands.RECORD:
                # self._device._samsungtv.shortcuts().record()
                # case media_player.Commands.SUBTITLE:
                # res = await self._device.subtitle()
                case media_player.Commands.SETTINGS:
                    self._device._samsungtv.shortcuts().tools()
                # --- simple commands ---
                case SimpleCommands.EXIT:
                    self._device._samsungtv.shortcuts().menu()
                case SimpleCommands.CH_LIST:
                    self._device._samsungtv.shortcuts().channel_list()
                # case SimpleCommands.SLEEP:
                # res = await self._device.sleep()
        except Exception as ex:
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            await self._device.disconnect()
            await self._device.connect()
            return ucapi.StatusCodes.TIMEOUT
        return ucapi.StatusCodes.OK


def _get_cmd_param(name: str, params: dict[str, Any] | None) -> str | bool | None:
    if params is None:
        return None
    return params.get(name)
