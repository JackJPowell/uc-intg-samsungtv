"""
This module implements the Samsung TV communication of the Remote Two integration driver.

"""

import asyncio
import contextlib
import logging
from asyncio import AbstractEventLoop
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, cast

import aiohttp
import wakeonlan
from const import SamsungConfig
from samsungtvws import SamsungTVWS
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.event import ED_INSTALLED_APP_EVENT, parse_installed_app
from samsungtvws.exceptions import HttpApiError
from samsungtvws.remote import ChannelEmitCommand, SendRemoteKey
from ucapi import EntityTypes
from ucapi.media_player import Attributes as MediaAttr
from ucapi_framework import ExternalClientDevice, create_entity_id
from ucapi_framework.device import DeviceEvents

_LOG = logging.getLogger(__name__)


class PowerState(StrEnum):
    """Playback state for companion protocol."""

    OFF = "OFF"
    ON = "ON"
    STANDBY = "STANDBY"


class SamsungTv(ExternalClientDevice):
    """Representing an Samsung TV Device."""

    def __init__(
        self,
        device_config: SamsungConfig,
        loop: AbstractEventLoop | None = None,
        config_manager=None,
    ) -> None:
        """Create instance."""
        # Initialize ExternalClientDevice with 10 second watchdog interval
        super().__init__(
            device_config,
            loop,
            enable_watchdog=True,
            watchdog_interval=10,
            reconnect_delay=5,
            max_reconnect_attempts=0,  # Infinite retries
            config_manager=config_manager,
        )
        self._mac_address: str = device_config.mac_address
        self._app_list: dict[str, str] = {}
        self._end_of_power_off: datetime | None = None
        self._end_of_power_on: datetime | None = None
        self._active_source: str = ""
        self._power_on_task: asyncio.Task | None = None
        self._power_state: PowerState | None = None

    @property
    def identifier(self) -> str:
        """Return the device identifier."""
        if not self._device_config.identifier:
            raise ValueError("Instance not initialized, no identifier available")
        return self._device_config.identifier

    @property
    def log_id(self) -> str:
        """Return a log identifier."""
        return (
            self._device_config.name
            if self._device_config.name
            else self._device_config.identifier
        )

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._device_config.name

    @property
    def address(self) -> str | None:
        """Return the optional device address."""
        return self._device_config.address

    @property
    def state(self) -> PowerState | None:
        """Return the device state."""
        if self._power_state is None:
            return PowerState.OFF
        return self._power_state

    def check_client_connected(self) -> bool:
        """
        Check if the external client (SamsungTVWSAsyncRemote) is connected.

        Note: Network connection does NOT always indicate power state.
        - Frame TVs maintain connection even when off (in art mode)
        - Older TVs maintain connection for ~65 seconds after power off
        Use get_power_state() or the state property for actual power status.
        """
        return self._client is not None and self._client.is_alive()

    @property
    def source_list(self) -> list[str]:
        """Return a list of available input sources."""
        return sorted(self._app_list)

    @property
    def source(self) -> str:
        """Return the current input source."""
        return self._active_source

    @property
    def attributes(self) -> dict[str, any]:
        """Return the device attributes."""
        updated_data = {
            MediaAttr.STATE: self.state,
        }
        if self.source_list:
            updated_data[MediaAttr.SOURCE_LIST] = self.source_list
        if self.source:
            updated_data[MediaAttr.SOURCE] = self.source
        return updated_data

    @property
    def power_off_in_progress(self) -> bool:
        """Return if power off has been recently requested."""
        return (
            self._end_of_power_off is not None
            and self._end_of_power_off > datetime.utcnow()
        )

    @property
    def power_on_in_progress(self) -> bool:
        """Return if power on has been recently requested."""
        return (
            self._end_of_power_on is not None
            and self._end_of_power_on > datetime.utcnow()
        )

    @property
    def power_state(self) -> PowerState | None:
        """Return the current power state."""
        if self._power_state is None:
            return PowerState.OFF
        return self._power_state

    @property
    def timeout(self) -> int:
        """Return the timeout for the connection."""
        if self._device_config.token == "":
            return 30
        return 3

    async def create_client(self) -> SamsungTVWSAsyncRemote:
        """
        Create the Samsung TV WebSocket client instance.

        Called by base class when connecting.
        """
        _LOG.debug("[%s] Creating client for %s", self.log_id, self._device_config.address)
        return SamsungTVWSAsyncRemote(
            host=self._device_config.address,
            port=8002,
            key_press_delay=0.1,
            token=self._device_config.token,
            name="Unfolded Circle Remote",
            timeout=self.timeout,
        )

    async def connect_client(self) -> None:
        """
        Connect and set up the Samsung TV client.

        Called by base class after create_client().
        """
        await self._client.start_listening(self.handle_remote_event)

        # Update token if it changed during connection
        if self._client.token and self._client.token != self._device_config.token:
            _LOG.debug("[%s] Token updated", self.log_id)
            self._device_config.token = self._client.token
            if self._config_manager:
                self._config_manager.update(self._device_config)

        # Verify connection
        if not self._client.is_alive():
            raise ConnectionError("Failed to establish WebSocket connection")

        # Get initial state and fetch app list
        self.get_power_state()
        self.events.emit(
            DeviceEvents.UPDATE,
            self.get_entity_id(),
            {MediaAttr.STATE: self._power_state},
        )

        await asyncio.sleep(1)
        await self._update_app_list()

    async def disconnect_client(self) -> None:
        """
        Disconnect the Samsung TV client.

        Called by base class during disconnect.
        """
        if self._client:
            await self._client.close()

    async def disconnect(self) -> None:
        """
        Disconnect from Samsung.

        The base class handles stopping the watchdog and calling disconnect_client().
        """
        _LOG.debug("[%s] Disconnecting from device", self.log_id)
        await super().disconnect()
        _LOG.debug("[%s] Disconnected", self.log_id)

    async def close(self) -> None:
        """Close the connection."""
        # Cancel power on task if running
        if self._power_on_task and not self._power_on_task.done():
            self._power_on_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._power_on_task
        self._power_on_task = None

        # Close connection
        if self._client:
            await self._client.close()
            self._client = None

    async def check_connection_and_reconnect(self) -> None:
        """Check if the connection is alive and reconnect if not."""
        if self._client is None:
            _LOG.debug("[%s] Client is None, connecting", self.log_id)
            await self.connect()
            return

        if not self._client.is_alive():
            _LOG.debug("[%s] Connection lost, reconnecting", self.log_id)
            # Clean up old client before reconnecting (like main branch did)
            with contextlib.suppress(Exception):
                await self._client.close()
            self._client = None
            await self.connect()

    async def _process_update(self, data: dict[str, Any]) -> None:  # pylint: disable=too-many-branches
        """Process device state updates."""
        _LOG.debug("[%s] Process update", self.log_id)
        update = {}

        # We only update device state (playing, paused, etc) if the power state is On
        # otherwise we'll set the state to Off in the polling method
        if hasattr(data, "device_state"):
            self._state = data.device_state
            update[MediaAttr.STATE] = data.device_state
        else:
            _LOG.debug("[%s] No device_state in update data", self.log_id)

    async def _update_app_list(self) -> None:
        """Update the list of installed applications."""
        _LOG.debug("[%s] Updating app list", self.log_id)
        update = {}

        try:
            # Always include standard inputs
            update[MediaAttr.SOURCE_LIST] = [
                "TV",
                "HDMI",
                "HDMI1",
                "HDMI2",
                "HDMI3",
                "HDMI4",
            ]

            if self._client and self._client.is_alive():
                # Request app list - this returns the parsed list directly
                app_list = await self._client.app_list()

                if app_list:
                    # Successfully got app list from the async method
                    _LOG.debug(
                        "[%s] Retrieved %d apps via app_list()",
                        self.log_id,
                        len(app_list),
                    )
                    # Convert list to dict format
                    self._app_list = {app["name"]: app["appId"] for app in app_list}
                elif not self._app_list:
                    # Fallback: try the alternative command-based method
                    _LOG.debug(
                        "[%s] app_list() returned None, trying alternative method",
                        self.log_id,
                    )
                    await self._get_app_list_via_remote()

            # Add all installed apps to source list
            if self._app_list:
                _LOG.debug(
                    "[%s] Adding %d apps to source list",
                    self.log_id,
                    len(self._app_list),
                )
                for app_name in sorted(self._app_list.keys()):
                    update[MediaAttr.SOURCE_LIST].append(app_name)
            else:
                _LOG.warning("[%s] No apps found in app list", self.log_id)

        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Error updating app list: %s", self.log_id, ex)

        # Emit update with source list
        _LOG.debug(
            "[%s] Emitting source list with %d items",
            self.log_id,
            len(update.get(MediaAttr.SOURCE_LIST, [])),
        )
        self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

    async def _get_app_list_via_remote(self) -> list[str, str]:
        if not self.is_connected:
            return {}
        try:
            app_list = await self._client.send_command(
                ChannelEmitCommand.get_installed_app()
            )
            if app_list is None:
                return []
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] App list: remote error", self.log_id)
            return []

    async def launch_app(
        self, app_id: str | None = None, app_name: str | None = None
    ) -> None:
        """Launch an app on the TV."""
        if self.power_off_in_progress:
            _LOG.debug(
                "[%s] TV is powering off, not sending launch_app command", self.log_id
            )
            return
        if app_name:
            if app_name == "TV":
                await self.send_key("KEY_TV")
                return
            elif app_name == "HDMI":
                await self.send_key("KEY_HDMI")
                return
            elif app_name == "HDMI1":
                await self.send_key("KEY_HDMI1")
                return
            elif app_name == "HDMI2":
                await self.send_key("KEY_HDMI2")
                return
            elif app_name == "HDMI3":
                await self.send_key("KEY_HDMI3")
                return
            elif app_name == "HDMI4":
                await self.send_key("KEY_HDMI4")
                return
            else:
                # Get app_id from app list, with error handling
                app_id = self._app_list.get(app_name)
                if app_id is None:
                    _LOG.warning(
                        "[%s] App '%s' not found in app list, cannot launch",
                        self.log_id,
                        app_name,
                    )
                    return

        if app_id is None:
            _LOG.error("[%s] No app_id provided to launch_app", self.log_id)
            return

        async with aiohttp.ClientSession() as session:
            with contextlib.suppress(HttpApiError):
                rest_api = SamsungTVAsyncRest(
                    host=self._device_config.address, port=8002, session=session
                )
                await rest_api.rest_app_run(app_id)

    async def send_key(self, key: str, **kwargs: Any) -> None:
        """Send a key to the TV."""
        hold_time = kwargs.get("hold_time", None)  # in ms
        await self.check_connection_and_reconnect()
        if self._client is not None and self._client.is_alive():
            hold_time = float(hold_time / 1000) if hold_time else None
            if hold_time:
                await self._client.send_command(SendRemoteKey.hold(key, hold_time))
            else:
                await self._client.send_command(SendRemoteKey.click(key))
            return
        _LOG.error(
            "[%s] Cannot send key '%s', TV is not connected (_client: %s)",
            self.log_id,
            key,
            self._client is not None,
        )

    async def toggle_power(self, power: bool | None = None) -> None:
        """
        Handle power state change.

        Frame TVs maintain network connection even when off/in standby, so we use
        REST API to determine actual power state. Older TVs use network connection.
        """
        update = {}

        if self.power_off_in_progress:
            _LOG.debug(
                "[%s] TV is powering off, canceling and attempting power on",
                self.log_id,
            )
            await self.send_key("KEY_POWER")
            self._end_of_power_off = None
            self._power_on_task = asyncio.create_task(self.power_on_wol())
            update[MediaAttr.STATE] = PowerState.ON
            self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)
            return

        if self.power_on_in_progress:
            _LOG.debug("[%s] TV is powering on, ignoring power command", self.log_id)
            return

        # Determine target power state
        if power is None:
            self.get_power_state()
            power = self._power_state in [PowerState.OFF, PowerState.STANDBY]

        if power:
            # === POWER ON ===
            await self._handle_power_on()
        else:
            # === POWER OFF ===
            await self._handle_power_off()

        update[MediaAttr.STATE] = self._power_state
        self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

    async def _handle_power_on(self) -> None:
        """Handle turning the TV on."""
        # For all TVs, check current power state
        # REST API should work for both old and new TVs
        if self._power_state == PowerState.ON:
            _LOG.debug("[%s] Device is already fully ON", self.log_id)
            return
        elif self._power_state == PowerState.STANDBY:
            # TV is in standby/art mode - just send power key
            _LOG.debug("[%s] Device in STANDBY, sending KEY_POWER", self.log_id)
            await self.send_key("KEY_POWER")
            self._power_state = PowerState.ON
        else:
            # TV is completely off - need WOL
            _LOG.debug("[%s] Device is OFF, initiating Wake-on-LAN", self.log_id)
            self._end_of_power_on = datetime.utcnow() + timedelta(seconds=17)
            self._power_on_task = asyncio.create_task(self.power_on_wol())
            self._power_state = PowerState.ON

    async def _handle_power_off(self) -> None:
        """Handle turning the TV off."""
        _LOG.debug("[%s] Sending KEY_POWER to turn off", self.log_id)
        await self.send_key("KEY_POWER")

        if self.device_config.supports_art_mode:
            # Frame TVs with art mode - power off enters art mode/standby
            # These typically transition to standby quickly (REST API will report "standby")
            _LOG.debug("[%s] Frame TV: will enter art mode/standby", self.log_id)
            self._end_of_power_off = datetime.utcnow() + timedelta(seconds=5)
            self._power_state = PowerState.STANDBY
        else:
            # Regular TVs - power off fully, but network connection can take
            # up to 65 seconds to drop. REST API should report "off" immediately though.
            _LOG.debug(
                "[%s] Regular TV: entering power off (network may stay alive briefly)",
                self.log_id,
            )
            self._end_of_power_off = datetime.utcnow() + timedelta(seconds=65)
            self._power_state = PowerState.OFF

    async def power_on_wol(self) -> None:
        """
        Power on the TV using Wake-on-LAN.

        Sends magic packets and waits for the TV to respond.
        Uses REST API to check actual power state (works for all Samsung TVs).
        """
        update = {}
        _LOG.debug("[%s] Starting Wake-on-LAN sequence", self.log_id)

        for i in range(8):
            _LOG.debug("[%s] Sending magic packet (%s/8)", self.log_id, i + 1)
            wakeonlan.send_magic_packet(self._device_config.mac_address)
            await asyncio.sleep(2)

            # Check if TV has powered on
            await self.check_connection_and_reconnect()

            # Check actual power state via REST API (works for all TVs)
            self.get_power_state()
            if self._power_state == PowerState.ON:
                _LOG.debug("[%s] TV powered on successfully (state: ON)", self.log_id)
                break
            else:
                _LOG.debug(
                    "[%s] TV not fully on yet (state: %s)",
                    self.log_id,
                    self._power_state,
                )

        # Final state check
        self.get_power_state()
        if self._power_state != PowerState.ON:
            _LOG.warning(
                "[%s] Unable to wake TV after 8 attempts (final state: %s)",
                self.log_id,
                self._power_state,
            )

        self._end_of_power_on = None
        update[MediaAttr.STATE] = self._power_state
        self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

    def get_power_state(self) -> PowerState:
        """
        Return the power status of the device.

        REST API works for all Samsung TVs, but only TVs with reports_power_state=True
        actually report their power state. For others, fall back to network state.
        """
        update = {}

        if self.device_config.reports_power_state:
            # This TV is configured to report power state via REST API
            # Query the REST API for actual power state
            power_state = (
                self.get_device_info().get("device", None).get("PowerState", None)
            )

            if power_state:
                # REST API successfully returned power state
                match power_state:
                    case "on":
                        self._power_state = PowerState.ON
                        self._end_of_power_on = None
                        _LOG.debug("[%s] REST API reports: ON", self.log_id)
                    case "standby":
                        self._power_state = PowerState.STANDBY
                        _LOG.debug(
                            "[%s] REST API reports: STANDBY (art mode/quick-start)",
                            self.log_id,
                        )
                    case "off":
                        self._power_state = PowerState.OFF
                        _LOG.debug("[%s] REST API reports: OFF", self.log_id)
                    case _:
                        # Unknown power state from REST API
                        self._power_state = PowerState.OFF
                        _LOG.debug(
                            "[%s] REST API reports unknown state: %s (assuming OFF)",
                            self.log_id,
                            power_state,
                        )
            else:
                # REST API should report power state but didn't - TV likely completely off
                _LOG.debug(
                    "[%s] REST API failed to return power state - TV likely OFF",
                    self.log_id,
                )
                self._power_state = PowerState.OFF
        else:
            # This TV doesn't report power state via REST API
            # Fall back to network connection state with grace period handling
            client = self._client

            if client is not None and client.is_alive():
                if self.power_off_in_progress:
                    # User just requested power off, but network connection is still alive
                    # (can take up to 65 seconds for older TVs to drop connection)
                    # This grace period prevents false "on" state during shutdown
                    self._power_state = PowerState.OFF
                    _LOG.debug(
                        "[%s] Network alive but in power-off grace period", self.log_id
                    )
                else:
                    self._power_state = PowerState.ON
                    _LOG.debug(
                        "[%s] Network connection alive and no power-off pending - assuming ON",
                        self.log_id,
                    )
                    self._end_of_power_on = None
            else:
                _LOG.debug("[%s] Network connection not alive - TV is OFF", self.log_id)
                self._power_state = PowerState.OFF

        update[MediaAttr.STATE] = self._power_state
        self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

    def handle_remote_event(self, event: str, response: Any) -> None:
        """Handle remote events."""
        if event == ED_INSTALLED_APP_EVENT:
            apps = {
                app["name"]: app["appId"]
                for app in sorted(
                    parse_installed_app(response),
                    key=lambda app: cast(str, app["name"]),
                )
            }
            self._app_list = apps
            _LOG.debug(
                "[%s] Installed apps updated via event: %d apps", self.log_id, len(apps)
            )

            # Emit update with the new app list
            update = {
                MediaAttr.SOURCE_LIST: [
                    "TV",
                    "HDMI",
                    "HDMI1",
                    "HDMI2",
                    "HDMI3",
                    "HDMI4",
                ]
                + sorted(self._app_list.keys())
            }
            self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

    def get_device_info(self) -> dict[str, Any]:
        """Get REST info from the TV."""
        rest = None
        try:
            rest = RestTV(self.device_config)
            info = rest.tv.rest_device_info()
            _LOG.debug("[%s] REST info: %s", self.log_id, info)
            return info
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Unable to retrieve rest info. TV may be offline", self.log_id
            )
            return {"device": {"PowerState": "off"}}
        finally:
            if rest:
                rest.close()

    def get_art_info(self) -> dict[str, Any]:
        """Get ART info from the TV."""
        rest = None
        try:
            rest = RestTV(self.device_config)

            supported = rest.tv.art().supported()
            _LOG.debug("[%s] Art Supported: %s", self.log_id, supported)
            if supported:
                _LOG.debug(
                    "[%s] Art Current: %s", self.log_id, rest.tv.art().get_current()
                )
                _LOG.debug(
                    "[%s] Art Available: %s", self.log_id, rest.tv.art().available()
                )
                _LOG.debug(
                    "[%s] Art Mode: %s", self.log_id, rest.tv.art().get_artmode()
                )
            return {"supported": supported}
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Unable to retrieve art info. TV may be offline: %s",
                self.log_id,
                ex,
            )
            return {"supported": False}
        finally:
            if rest:
                rest.close()

    def toggle_art_mode(self, state: bool) -> None:
        """Toggle ART mode on the TV."""
        rest = None
        try:
            rest = RestTV(self.device_config)

            supported = rest.tv.art().supported()
            _LOG.debug("[%s] Art Supported: %s", self.log_id, supported)
            if state:
                rest.tv.art().set_artmode(True)
            else:
                rest.tv.art().set_artmode(False)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Unable to set art mode. TV may be offline: %s",
                self.log_id,
                ex,
            )
        finally:
            if rest:
                rest.close()

    def get_entity_id(self) -> str:
        """Return the entity ID for this device."""
        return create_entity_id(EntityTypes.MEDIA_PLAYER, self.identifier)


class RestTV:
    """Representing an Samsung TV Device with REST API."""

    def __init__(
        self,
        device_config: SamsungConfig,
    ) -> None:
        """Create instance."""
        self.tv = SamsungTVWS(
            device_config.address,
            port=8002,
            timeout=2,
            name="Unfolded Circle",
        )

    def close(self) -> None:
        """Close the REST API connection."""
        self.tv.close()
        return
