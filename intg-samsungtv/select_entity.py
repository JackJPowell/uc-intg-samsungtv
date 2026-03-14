"""
Select entity for the Samsung TV integration — exposes the installed app list.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

import tv as samsung_tv
from const import SamsungConfig
from ucapi import EntityTypes, StatusCodes
from ucapi.select import Attributes, Commands, States
from ucapi_framework import create_entity_id
from ucapi_framework.entities import SelectEntity

_LOG = logging.getLogger(__name__)


class SamsungAppSelect(SelectEntity):
    """Select entity that exposes the TV's installed app list."""

    def __init__(self, config_device: SamsungConfig, device: samsung_tv.SamsungTv):
        """Initialize a Samsung App Select entity.

        Args:
            config_device: Device configuration.
            device: SamsungTv device instance.
        """
        self._device = device

        entity_id = create_entity_id(
            EntityTypes.SELECT, config_device.identifier, "app_list"
        )

        super().__init__(
            entity_id,
            "App List",
            attributes={
                Attributes.STATE: States.UNAVAILABLE,
                Attributes.CURRENT_OPTION: "",
                Attributes.OPTIONS: [],
            },
            cmd_handler=self.select_cmd_handler,
        )
        self.subscribe_to_device(device)

        _LOG.debug("Created App List select entity: %s", entity_id)

    async def select_cmd_handler(
        self,
        _entity: SelectEntity,
        cmd_id: str,
        params: dict[str, Any] | None,
        _websocket: Any = None,
    ) -> StatusCodes:
        """Handle select entity commands.

        Args:
            _entity: Select entity.
            cmd_id: Command identifier.
            params: Optional command parameters.
            _websocket: Optional websocket connection.

        Returns:
            StatusCodes: Result of command execution.
        """
        _LOG.debug("App List select command: %s, params: %s", cmd_id, params)

        if self._device is None:
            return StatusCodes.SERVICE_UNAVAILABLE

        match cmd_id:
            case Commands.SELECT_OPTION:
                if params and "option" in params:
                    success = await self._device.select_option(params["option"])
                    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                return StatusCodes.BAD_REQUEST

            case Commands.SELECT_FIRST:
                options = self.attributes.get(Attributes.OPTIONS, [])
                if options:
                    success = await self._device.select_option(options[0])
                    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                return StatusCodes.BAD_REQUEST

            case Commands.SELECT_LAST:
                options = self.attributes.get(Attributes.OPTIONS, [])
                if options:
                    success = await self._device.select_option(options[-1])
                    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                return StatusCodes.BAD_REQUEST

            case Commands.SELECT_NEXT:
                options = self.attributes.get(Attributes.OPTIONS, [])
                current = self.attributes.get(Attributes.CURRENT_OPTION, "")
                if options and current in options:
                    cycle = params.get("cycle", False) if params else False
                    current_idx = options.index(current)
                    if current_idx < len(options) - 1:
                        success = await self._device.select_option(
                            options[current_idx + 1]
                        )
                        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                    elif cycle:
                        success = await self._device.select_option(options[0])
                        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                return StatusCodes.BAD_REQUEST

            case Commands.SELECT_PREVIOUS:
                options = self.attributes.get(Attributes.OPTIONS, [])
                current = self.attributes.get(Attributes.CURRENT_OPTION, "")
                if options and current in options:
                    cycle = params.get("cycle", False) if params else False
                    current_idx = options.index(current)
                    if current_idx > 0:
                        success = await self._device.select_option(
                            options[current_idx - 1]
                        )
                        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                    elif cycle:
                        success = await self._device.select_option(options[-1])
                        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
                return StatusCodes.BAD_REQUEST

            case _:
                _LOG.warning("Unknown App List select command: %s", cmd_id)
                return StatusCodes.NOT_IMPLEMENTED

    async def sync_state(self) -> None:
        """Sync entity state from device attributes."""
        if self._device is None:
            self.set_unavailable()
            return
        attrs = self._device.get_select_attributes()
        if attrs is not None:
            self.update(attrs)
        else:
            self.set_unavailable()
