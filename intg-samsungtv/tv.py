"""
This module implements the Samsung TV communication of the Remote Two integration driver.

"""

import asyncio
import contextlib
import json
import logging
import ssl
import time
from asyncio import AbstractEventLoop
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, cast

import aiohttp
import certifi
import wakeonlan
from const import (
    SamsungConfig,
    SMARTTHINGS_WORKER_REFRESH,
)
from pysmartthings import SmartThings
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
        super().__init__(
            device_config,
            loop,
            enable_watchdog=False,
            max_reconnect_attempts=None,
            config_manager=config_manager,
        )
        self._mac_address: str = device_config.mac_address
        self._app_list: dict[str, str] = {}
        self._end_of_power_off: datetime | None = None
        self._end_of_power_on: datetime | None = None
        self._active_source: str = ""
        self._power_on_task: asyncio.Task | None = None
        self._power_state: PowerState | None = None
        self._device_uuid: str | None = None  # TV's UUID from REST API (duid)

        # SmartThings Cloud API client (optional - for advanced features like input source)
        self._smartthings_api: SmartThings | None = None
        self._smartthings_device_id: str | None = None
        self._last_smartthings_poll: datetime | None = None
        self._smartthings_capabilities: set[str] = set()

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
    def attributes(self) -> dict[str, Any]:
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
        _LOG.debug(
            "[%s] Creating client for %s", self.log_id, self._device_config.address
        )
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
        Note: We don't raise exceptions here because a TV that doesn't respond
        is simply OFF, not in an error state. The watchdog will keep trying.
        """
        try:
            await self._client.start_listening(self.handle_remote_event)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.debug("[%s] Could not connect (TV likely off): %s", self.log_id, err)
            self._power_state = PowerState.OFF
            self.events.emit(
                DeviceEvents.UPDATE,
                self.get_entity_id(),
                {MediaAttr.STATE: PowerState.OFF},
            )
            self.events.emit(
                DeviceEvents.UPDATE,
                create_entity_id(EntityTypes.REMOTE, self.identifier),
                {MediaAttr.STATE: PowerState.OFF},
            )
            return

        # Update token if it changed during connection
        if self._client.token and self._client.token != self._device_config.token:
            _LOG.debug("[%s] Token updated", self.log_id)
            self._device_config.token = self._client.token
            if self._config_manager:
                self._config_manager.update(self._device_config)

        # Verify connection - if not alive, TV is just off
        if not self._client.is_alive():
            _LOG.debug("[%s] Connection not alive, TV is off", self.log_id)
            self._power_state = PowerState.OFF
            self.events.emit(
                DeviceEvents.UPDATE,
                self.get_entity_id(),
                {MediaAttr.STATE: PowerState.OFF},
            )
            return

        # Get initial state
        self.get_power_state()
        self.events.emit(
            DeviceEvents.UPDATE,
            self.get_entity_id(),
            {MediaAttr.STATE: self._power_state},
        )

        # Get device UUID from REST API for SmartThings matching
        device_info = self.get_device_info()
        if device_info and "device" in device_info:
            duid = device_info["device"].get("duid")
            if duid:
                # Extract UUID from "uuid:919b18c4-1db7-4f71-8230-fd62c3b92413" format
                self._device_uuid = duid.replace("uuid:", "")
                _LOG.debug(
                    "[%s] Extracted device UUID: %s", self.log_id, self._device_uuid
                )

        # Initialize SmartThings API client first if OAuth token is configured
        # This allows SmartThings to be used as fallback when fetching app list
        if self._device_config.smartthings_access_token and not self._smartthings_api:
            await self._init_smartthings_client()

        await asyncio.sleep(1)
        await self._update_app_list()

    async def _init_smartthings_client(self) -> None:
        """
        Initialize SmartThings API client and discover the TV device.

        Called during connect_client if SmartThings OAuth token is configured.
        Automatically refreshes tokens aggressively for battery-powered devices.
        """
        if not self._device_config.smartthings_access_token:
            # No SmartThings authentication configured
            return

        # Aggressive token refresh strategy for battery-powered devices
        # Refresh if token expires within 12 hours (50% of 24hr token lifetime)
        # This ensures we refresh whenever the device is awake
        if self._device_config.smartthings_token_expires:
            time_until_expiry = (
                self._device_config.smartthings_token_expires - time.time()
            )
            if time_until_expiry <= 43200:  # 12 hours in seconds
                _LOG.info(
                    "[%s] SmartThings OAuth token expires in %.1f hours, refreshing proactively",
                    self.log_id,
                    time_until_expiry / 3600,
                )
                await self._refresh_smartthings_token()

        token = self._device_config.smartthings_access_token

        try:
            # Create aiohttp session for SmartThings API with certifi CA bundle
            # Uses up-to-date Mozilla CA bundle which includes GTS Root R4
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            session = aiohttp.ClientSession(connector=connector)

            self._smartthings_api = SmartThings(
                session=session,
                token=token,
            )
            _LOG.debug(
                "[%s] SmartThings API client initialized", self.log_id
            )  # Discover the device in SmartThings
            await self._discover_smartthings_device()
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.warning(
                "[%s] Failed to initialize SmartThings client: %s", self.log_id, ex
            )
            self._smartthings_api = None

    async def _refresh_smartthings_token(self) -> None:
        """
        Refresh SmartThings OAuth access token using refresh token via worker.

        Updates the device config with new access token and expiration time.
        """
        if not self._device_config.smartthings_refresh_token:
            _LOG.error(
                "[%s] Cannot refresh token: no refresh token available", self.log_id
            )
            return

        try:
            # Use certifi CA bundle for SSL verification
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                # Use Cloudflare Worker to refresh token (keeps client credentials secure)
                data = {
                    "refresh_token": self._device_config.smartthings_refresh_token,
                }

                async with session.post(
                    SMARTTHINGS_WORKER_REFRESH,
                    json=data,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response_text = await response.text()
                    if response.status != 200:
                        _LOG.error(
                            "[%s] Failed to refresh SmartThings token (status %d): %s",
                            self.log_id,
                            response.status,
                            response_text,
                        )
                        return

                    token_data = await response.json()
                    access_token = token_data.get("access_token")
                    refresh_token = token_data.get("refresh_token")
                    expires_in = token_data.get("expires_in", 86400)  # Default 24 hours

                    if not access_token:
                        _LOG.error(
                            "[%s] No access token in refresh response", self.log_id
                        )
                        return

                    # Update device config with new tokens
                    self._device_config.smartthings_access_token = access_token
                    if refresh_token:
                        # New refresh token may be provided
                        self._device_config.smartthings_refresh_token = refresh_token
                    self._device_config.smartthings_token_expires = (
                        int(time.time()) + expires_in
                    )

                    # Save updated config
                    if self._config_manager:
                        self._config_manager.update(self._device_config)

                    _LOG.info(
                        "[%s] Successfully refreshed SmartThings OAuth token (expires in %d seconds)",
                        self.log_id,
                        expires_in,
                    )

        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error refreshing SmartThings token: %s", self.log_id, ex)

    async def disconnect_client(self) -> None:
        """
        Disconnect the Samsung TV client.

        Called by base class during disconnect.
        """
        if self._client:
            await self._client.close()

        # Clean up SmartThings client
        if self._smartthings_api:
            self._smartthings_api = None
            self._smartthings_device_id = None

    async def disconnect(self) -> None:
        """
        Disconnect from Samsung.

        Override base class to emit OFF state instead of DISCONNECTED.
        For a TV, disconnecting means it's off, not unavailable.
        """
        _LOG.debug("[%s] Disconnecting from device", self.log_id)

        # Disconnect the client
        if self._client:
            with contextlib.suppress(Exception):
                await self.disconnect_client()
            self._client = None

        self._is_connected = False
        self._power_state = PowerState.OFF

        # Emit OFF state for both entities instead of DISCONNECTED
        self.events.emit(
            DeviceEvents.UPDATE,
            self.get_entity_id(),
            {MediaAttr.STATE: PowerState.OFF},
        )
        self.events.emit(
            DeviceEvents.UPDATE,
            create_entity_id(EntityTypes.REMOTE, self.identifier),
            {MediaAttr.STATE: PowerState.OFF},
        )
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
            with contextlib.suppress(Exception):
                await self._client.close()
            self._client = None
            await self.connect()
        else:
            # Connection is alive - poll SmartThings for status updates if available
            if self._smartthings_api and self._power_state == PowerState.ON:
                update = await self.query_smartthings_status()
                if update:
                    self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

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
                # Try SmartThings as fallback if enabled
                if self._smartthings_api:
                    _LOG.debug(
                        "[%s] Attempting to retrieve source list from SmartThings",
                        self.log_id,
                    )
                    smartthings_sources = await self._get_smartthings_source_list()
                    if smartthings_sources:
                        _LOG.debug(
                            "[%s] Adding %d sources from SmartThings",
                            self.log_id,
                            len(smartthings_sources),
                        )
                        update[MediaAttr.SOURCE_LIST].extend(smartthings_sources)

        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Error updating app list: %s", self.log_id, ex)

        # Emit update with source list
        _LOG.debug(
            "[%s] Emitting source list with %d items",
            self.log_id,
            len(update.get(MediaAttr.SOURCE_LIST, [])),
        )
        self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

    async def _get_app_list_via_remote(self) -> dict[str, str]:
        if not self.is_connected:
            return {}
        try:
            app_list = await self._client.send_command(
                ChannelEmitCommand.get_installed_app()
            )
            if app_list is None:
                return {}
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] App list: remote error", self.log_id)
            return {}
        return {}

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
            elif app_name in ["HDMI", "HDMI1", "HDMI2", "HDMI3", "HDMI4"]:
                # Try SmartThings API first for HDMI inputs (local API doesn't support this)
                if self._smartthings_api:
                    _LOG.debug(
                        "[%s] Using SmartThings API for HDMI input: %s",
                        self.log_id,
                        app_name,
                    )
                    success = await self.set_input_source_smartthings(app_name)
                    if success:
                        return
                    _LOG.warning(
                        "[%s] SmartThings failed for %s, falling back to KEY command",
                        self.log_id,
                        app_name,
                    )

                # Fallback to local KEY commands (may not work on all models)
                if app_name == "HDMI":
                    await self.send_key("KEY_HDMI")
                elif app_name == "HDMI1":
                    await self.send_key("KEY_HDMI1")
                elif app_name == "HDMI2":
                    await self.send_key("KEY_HDMI2")
                elif app_name == "HDMI3":
                    await self.send_key("KEY_HDMI3")
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

        # Query SmartThings for updated source after launching app
        if self._smartthings_api:
            await asyncio.sleep(1)  # Give app time to launch
            update = await self.query_smartthings_status(force=True)
            if update:
                self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

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

            # Query SmartThings status after volume/playback keys for immediate feedback
            if self._smartthings_api and key in [
                "KEY_VOLUP",
                "KEY_VOLDOWN",
                "KEY_MUTE",
                "KEY_PLAY",
                "KEY_PAUSE",
                "KEY_STOP",
                "KEY_PLAYPAUSE",
                "KEY_FF",
                "KEY_REWIND",
            ]:
                # Small delay for TV to process command
                await asyncio.sleep(0.3)
                update = await self.query_smartthings_status(force=True)
                if update:
                    self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)
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
            # TV is completely off - use SmartThings if available, otherwise WOL
            if self._device_config.supports_power_on_by_ocf and self._smartthings_api:
                _LOG.debug(
                    "[%s] Device is OFF, using SmartThings to power on", self.log_id
                )
                success = await self.power_on_smartthings()
                if success:
                    self._power_state = PowerState.ON
                else:
                    # Fallback to WOL if SmartThings fails
                    _LOG.warning(
                        "[%s] SmartThings power on failed, falling back to WOL",
                        self.log_id,
                    )
                    _LOG.debug(
                        "[%s] Device is OFF, initiating Wake-on-LAN", self.log_id
                    )
                    self._end_of_power_on = datetime.utcnow() + timedelta(seconds=17)
                    self._power_on_task = asyncio.create_task(self.power_on_wol())
                    self._power_state = PowerState.ON
            else:
                # No SmartThings or doesn't support OCF power - use WOL
                _LOG.debug("[%s] Device is OFF, initiating Wake-on-LAN", self.log_id)
                self._end_of_power_on = datetime.utcnow() + timedelta(seconds=17)
                self._power_on_task = asyncio.create_task(self.power_on_wol())
                self._power_state = PowerState.ON

    async def _handle_power_off(self) -> None:
        """Handle turning the TV off."""
        # Use SmartThings if available for more reliable power off
        if self._smartthings_api and self._smartthings_device_id:
            _LOG.debug("[%s] Using SmartThings to turn off", self.log_id)
            success = await self.power_off_smartthings()
            if not success:
                # Fallback to KEY_POWER if SmartThings fails
                _LOG.warning(
                    "[%s] SmartThings power off failed, using KEY_POWER", self.log_id
                )
                await self.send_key("KEY_POWER")
        else:
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

    def get_power_state(self) -> None:
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

    async def _discover_smartthings_device(self) -> bool:
        """
        Discover the Samsung TV device in SmartThings.

        Uses the device's MAC address to identify it in SmartThings.
        Returns True if device was found, False otherwise.
        """
        if not self._smartthings_api:
            return False

        if not self._device_config.mac_address:
            _LOG.warning(
                "[%s] Cannot discover SmartThings device: MAC address not available",
                self.log_id,
            )
            return False

        try:
            devices = await self._smartthings_api.devices()
            # Match by MAC address
            # SmartThings MAC addresses are typically uppercase without colons
            mac_normalized = self._device_config.mac_address.replace(":", "").upper()

            _LOG.debug(
                "[%s] Searching for TV with MAC: %s (normalized: %s) among %d SmartThings devices",
                self.log_id,
                self._device_config.mac_address,
                mac_normalized,
                len(devices),
            )
            _LOG.debug(
                "[%s] Will also try matching by IP: %s, name: %s, and UUID: %s",
                self.log_id,
                self._device_config.address,
                self._device_config.name,
                self._device_uuid if self._device_uuid else "N/A",
            )

            matched_device = None
            match_method = None

            for device in devices:
                # Get device attributes
                device_mac = (
                    getattr(device, "device_network_id", "").replace(":", "").upper()
                )
                device_label = getattr(device, "label", "")
                device_type = getattr(device, "type", "")
                
                # Log all potentially useful attributes for debugging
                _LOG.debug(
                    "[%s] Checking device: %s (label: %s, type: %s, device_network_id: %s)",
                    self.log_id,
                    device.device_id,
                    device_label,
                    device_type,
                    getattr(device, "device_network_id", "N/A"),
                )
                
                # Log additional attributes that might help with matching
                _LOG.debug(
                    "[%s]   Additional attributes - ocf_device_type: %s, manufacturer_name: %s, device_manufacturer_code: %s",
                    self.log_id,
                    getattr(device, "ocf_device_type", "N/A"),
                    getattr(device, "manufacturer_name", "N/A"),
                    getattr(device, "device_manufacturer_code", "N/A"),
                )
                
                # Strategy 1: Match by UUID - most reliable if available
                # Check if device_id or device_network_id contains the TV's UUID
                if self._device_uuid:
                    device_id_lower = device.device_id.lower()
                    uuid_lower = self._device_uuid.lower()
                    # Check if UUID appears in device_id or device_network_id
                    if uuid_lower in device_id_lower or (
                        device_mac and uuid_lower in device_mac.lower()
                    ):
                        matched_device = device
                        match_method = f"UUID match ({self._device_uuid})"
                        _LOG.info(
                            "[%s] Found device by UUID in device_id/network_id",
                            self.log_id,
                        )
                        break

                # Strategy 2: Match by device_network_id (MAC address) - most reliable
                if device_mac and device_mac == mac_normalized:
                    matched_device = device
                    match_method = f"MAC address ({device_mac})"
                    break

                # Strategy 3: Match by device name (label)
                # SmartThings often prefixes with [TV]
                if device_label and not matched_device:
                    # Remove [TV] prefix and compare
                    label_clean = device_label.replace("[TV] ", "").strip()
                    if label_clean == self._device_config.name:
                        matched_device = device
                        match_method = f"name match ('{device_label}')"
                        # Don't break - continue looking in case we find a MAC match

            # Check if we found a device
            if not matched_device:
                _LOG.warning(
                    "[%s] SmartThings device not found - tried MAC: %s, Name: %s",
                    self.log_id,
                    mac_normalized,
                    self._device_config.name,
                )
                return False

            # We found a device!
            self._smartthings_device_id = matched_device.device_id
            _LOG.info(
                "[%s] Found SmartThings device via %s (ID: %s)",
                self.log_id,
                match_method,
                matched_device.device_id,
            )

            # Log device capabilities and type to understand what's available
            device_type = getattr(matched_device, "type", "UNKNOWN")
            capabilities = getattr(matched_device, "capabilities", [])

            _LOG.info(
                "[%s] SmartThings device details - Type: %s, Device ID: %s",
                self.log_id,
                device_type,
                matched_device.device_id,
            )
            _LOG.debug(
                "[%s] All capabilities: %s",
                self.log_id,
                capabilities,
            )
            _LOG.debug(
                "[%s] Has supportsPowerOnByOcf capability: %s",
                self.log_id,
                "samsungvd.supportsPowerOnByOcf" in capabilities,
            )

            # Check if TV supports power on via OCF (network wake without WOL)
            # Conservative approach: Default to NOT supporting network power on
            supports_network_power = False

            # Refresh device status to populate all attributes
            # When devices() is called, status.attributes may be empty
            try:
                if hasattr(matched_device, "status") and matched_device.status:
                    _LOG.debug(
                        "[%s] Refreshing device status to populate attributes",
                        self.log_id,
                    )
                    await matched_device.status.refresh()
                    status = matched_device.status

                    # Log all available status attributes for debugging
                    if hasattr(status, "attributes"):
                        _LOG.debug(
                            "[%s] All status attributes after refresh: %s",
                            self.log_id,
                            list(status.attributes.keys()),
                        )

                        # Try to get the supportsPowerOnByOcf attribute value
                        ocf_value = status.attributes.get("supportsPowerOnByOcf")

                        if ocf_value:
                            # Log detailed information about the OCF attribute
                            _LOG.info(
                                "[%s] supportsPowerOnByOcf found - Value: %s, Unit: %s, Data: %s",
                                self.log_id,
                                getattr(ocf_value, "value", None),
                                getattr(ocf_value, "unit", None),
                                getattr(ocf_value, "data", None),
                            )

                            # Only enable if the attribute has a truthy value
                            # TVs that support it will have this populated with data
                            # TVs that don't support it will have it empty/None
                            if hasattr(ocf_value, "value") and ocf_value.value:
                                supports_network_power = True
                                _LOG.info(
                                    "[%s] OCF power on IS SUPPORTED (value=%s) - will use SmartThings for power",
                                    self.log_id,
                                    ocf_value.value,
                                )
                            else:
                                _LOG.info(
                                    "[%s] OCF power on NOT supported (value=%s) - will use WOL",
                                    self.log_id,
                                    getattr(ocf_value, "value", None),
                                )
                        else:
                            _LOG.info(
                                "[%s] supportsPowerOnByOcf attribute not found in status - will use WOL",
                                self.log_id,
                            )
                    else:
                        _LOG.warning(
                            "[%s] Device status has no attributes",
                            self.log_id,
                        )
                else:
                    _LOG.warning(
                        "[%s] Device has no status object",
                        self.log_id,
                    )
            except Exception as ex:
                _LOG.warning(
                    "[%s] Error checking supportsPowerOnByOcf: %s",
                    self.log_id,
                    ex,
                    exc_info=True,
                )

            if supports_network_power:
                self._device_config.supports_power_on_by_ocf = True
                _LOG.info(
                    "[%s] TV supports network-based power on - will use SmartThings for power control",
                    self.log_id,
                )
            else:
                self._device_config.supports_power_on_by_ocf = False
                _LOG.info(
                    "[%s] TV does not support network-based power on - will use WOL for power on",
                    self.log_id,
                )

            # Save the updated config to disk so it persists across restarts
            if self._config_manager:
                self._config_manager.update(self._device_config)
                _LOG.debug(
                    "[%s] Saved supports_power_on_by_ocf setting to config",
                    self.log_id,
                )

            return True

        except aiohttp.ClientResponseError as ex:
            if ex.status == 401:
                _LOG.warning(
                    "[%s] SmartThings API returned 401 Unauthorized - token may have expired",
                    self.log_id,
                )
                # Try refreshing the token
                await self._refresh_smartthings_token()
                # Don't retry here - let the caller retry if needed
                return False
            else:
                _LOG.error(
                    "[%s] SmartThings API error during discovery: %s", self.log_id, ex
                )
                return False
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error discovering SmartThings device: %s", self.log_id, ex)
            return False

    async def _get_smartthings_device(self):
        """
        Get the SmartThings device object.

        Returns the device object if available, None otherwise.
        Handles API availability check, device discovery, and device lookup.
        """
        if not self._smartthings_api:
            return None

        if not self._smartthings_device_id:
            _LOG.debug(
                "[%s] No SmartThings device ID cached, attempting discovery",
                self.log_id,
            )
            if not await self._discover_smartthings_device():
                return None

        try:
            devices = await self._smartthings_api.devices()
            _LOG.debug(
                "[%s] Looking for SmartThings device ID: %s among %d devices",
                self.log_id,
                self._smartthings_device_id,
                len(devices),
            )

            device = next(
                (d for d in devices if d.device_id == self._smartthings_device_id), None
            )

            if not device:
                _LOG.warning(
                    "[%s] SmartThings device ID %s not found in device list",
                    self.log_id,
                    self._smartthings_device_id,
                )
                # Log all available devices to help diagnose
                _LOG.debug("[%s] Available SmartThings devices:", self.log_id)
                for dev in devices:
                    _LOG.debug(
                        "  - ID: %s, Label: %s, Type: %s",
                        dev.device_id,
                        getattr(dev, "label", "N/A"),
                        getattr(dev, "type", "N/A"),
                    )

                # Try re-discovering in case the device ID changed
                _LOG.info(
                    "[%s] Attempting to re-discover SmartThings device", self.log_id
                )
                self._smartthings_device_id = None
                if await self._discover_smartthings_device():
                    # Retry lookup with new device ID
                    device = next(
                        (
                            d
                            for d in devices
                            if d.device_id == self._smartthings_device_id
                        ),
                        None,
                    )
                    if device:
                        _LOG.info(
                            "[%s] Successfully found device after re-discovery",
                            self.log_id,
                        )
                        return device

                _LOG.error(
                    "[%s] SmartThings device not found even after re-discovery",
                    self.log_id,
                )
                return None

            _LOG.debug(
                "[%s] Found SmartThings device: %s",
                self.log_id,
                getattr(device, "label", self._smartthings_device_id),
            )
            return device
        except aiohttp.ClientResponseError as ex:
            if ex.status == 401:
                _LOG.warning(
                    "[%s] SmartThings API returned 401 Unauthorized - attempting token refresh and retry",
                    self.log_id,
                )
                # Refresh token
                await self._refresh_smartthings_token()
                
                # Recreate API client with new token
                if self._device_config.smartthings_access_token:
                    try:
                        ssl_context = ssl.create_default_context(cafile=certifi.where())
                        connector = aiohttp.TCPConnector(ssl=ssl_context)
                        session = aiohttp.ClientSession(connector=connector)
                        self._smartthings_api = SmartThings(
                            session=session,
                            token=self._device_config.smartthings_access_token,
                        )
                        _LOG.debug(
                            "[%s] Recreated SmartThings API client with refreshed token",
                            self.log_id,
                        )
                        
                        # Retry getting device list with new token
                        devices = await self._smartthings_api.devices()
                        device = next(
                            (
                                d
                                for d in devices
                                if d.device_id == self._smartthings_device_id
                            ),
                            None,
                        )
                        if device:
                            _LOG.info(
                                "[%s] Successfully retrieved device after token refresh",
                                self.log_id,
                            )
                            return device
                    except Exception as retry_ex:  # pylint: disable=broad-exception-caught
                        _LOG.error(
                            "[%s] Failed to get device even after token refresh: %s",
                            self.log_id,
                            retry_ex,
                        )
                return None
            else:
                _LOG.error(
                    "[%s] SmartThings API error: %s", self.log_id, ex
                )
                return None
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error getting SmartThings device: %s", self.log_id, ex)
            return None

    async def _get_smartthings_source_list(self) -> list[str] | None:
        """
        Retrieve supported input sources from SmartThings.

        Returns a list of source names if available, None otherwise.
        This can be used as a fallback when local API fails to provide sources.
        """
        device = await self._get_smartthings_device()
        if not device:
            return None

        try:
            await device.status.refresh()
            attributes = device.status.attributes

            supported_sources_attr = attributes.get("supportedInputSources")
            if supported_sources_attr and hasattr(supported_sources_attr, "value"):
                try:
                    # The value is a JSON string that needs to be parsed
                    sources_list = json.loads(supported_sources_attr.value)
                    if sources_list and isinstance(sources_list, list):
                        _LOG.debug(
                            "[%s] Retrieved %d sources from SmartThings",
                            self.log_id,
                            len(sources_list),
                        )
                        return sources_list
                except (json.JSONDecodeError, TypeError) as ex:
                    _LOG.debug(
                        "[%s] Could not parse supportedInputSources: %s",
                        self.log_id,
                        ex,
                    )
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Error retrieving SmartThings source list: %s", self.log_id, ex
            )

        return None

    async def set_input_source_smartthings(self, source: str) -> bool:
        """
        Set input source using SmartThings Cloud API.

        This is a workaround for the limitation in the local WebSocket API
        which doesn't support setting input sources on Samsung TVs.

        Note: TV must be powered on and network-connected for SmartThings
        to reach it. Use WOL if needed before calling this.
        """
        # Ensure TV is awake (SmartThings needs network connection)
        if self._power_state != PowerState.ON:
            _LOG.debug(
                "[%s] TV is off, waking via WOL before SmartThings command", self.log_id
            )
            await self._handle_power_on()
            # Wait for TV to fully wake up
            await asyncio.sleep(3)

        device = await self._get_smartthings_device()
        if not device:
            return False

        try:
            # Execute command to set input source
            # SmartThings API uses: device.command(component, capability, command, args)
            await device.command(
                "main",  # component
                "samsungvd.mediaInputSource",  # capability
                "setInputSource",  # command
                [source],  # args
            )
            _LOG.debug("[%s] SmartThings: Set input source to %s", self.log_id, source)
            self._active_source = source

            # Query status to confirm and get any other updates
            await asyncio.sleep(0.5)
            update = await self.query_smartthings_status(force=True)
            if update:
                self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

            return True
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "[%s] Error setting input source via SmartThings: %s", self.log_id, ex
            )
            return False

    async def power_on_smartthings(self) -> bool:
        """
        Power on the TV using SmartThings Cloud API.

        Only works if the TV supports power on via OCF (network-based wake).
        Returns True if successful, False otherwise.
        """
        if not self._device_config.supports_power_on_by_ocf:
            _LOG.debug("[%s] TV does not support SmartThings power on", self.log_id)
            return False

        device = await self._get_smartthings_device()
        if not device:
            return False

        try:
            # Use the switch capability to turn on
            await device.command(
                "main",  # component
                "switch",  # capability
                "on",  # command
                [],  # no args
            )
            _LOG.info("[%s] SmartThings: Powered on TV", self.log_id)
            return True
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error powering on via SmartThings: %s", self.log_id, ex)
            return False

    async def power_off_smartthings(self) -> bool:
        """
        Power off the TV using SmartThings Cloud API.

        Returns True if successful, False otherwise.
        """
        device = await self._get_smartthings_device()
        if not device:
            return False

        try:
            # Use the switch capability to turn off
            await device.command(
                "main",  # component
                "switch",  # capability
                "off",  # command
                [],  # no args
            )
            _LOG.info("[%s] SmartThings: Powered off TV", self.log_id)
            return True
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error powering off via SmartThings: %s", self.log_id, ex)
            return False

    async def send_smartthings_command(
        self, command: str, query_after: bool = False, delay: float = 0.5
    ) -> bool:
        """
        Send a media control command via SmartThings API.

        Args:
            command: The command name (e.g., 'channel_up', 'play', 'pause')
            query_after: Whether to query status after the command
            delay: Seconds to wait before querying status (if query_after is True)

        Returns:
            True if successful, False otherwise
        """
        device = await self._get_smartthings_device()
        if not device:
            return False

        try:
            match command:
                case "channel_up":
                    await device.channel_up()
                    _LOG.debug("[%s] SmartThings: Channel up", self.log_id)
                case "channel_down":
                    await device.channel_down()
                    _LOG.debug("[%s] SmartThings: Channel down", self.log_id)
                case "volume_up":
                    await device.volume_up()
                    _LOG.debug("[%s] SmartThings: Volume up", self.log_id)
                case "volume_down":
                    await device.volume_down()
                    _LOG.debug("[%s] SmartThings: Volume down", self.log_id)
                case "mute":
                    await device.mute()
                    _LOG.debug("[%s] SmartThings: Mute", self.log_id)
                case "unmute":
                    await device.unmute()
                    _LOG.debug("[%s] SmartThings: Unmute", self.log_id)
                case "play":
                    await device.play()
                    _LOG.debug("[%s] SmartThings: Play", self.log_id)
                case "pause":
                    await device.pause()
                    _LOG.debug("[%s] SmartThings: Pause", self.log_id)
                case "stop":
                    await device.stop()
                    _LOG.debug("[%s] SmartThings: Stop", self.log_id)
                case "fast_forward":
                    await device.fast_forward()
                    _LOG.debug("[%s] SmartThings: Fast forward", self.log_id)
                case "rewind":
                    await device.rewind()
                    _LOG.debug("[%s] SmartThings: Rewind", self.log_id)
                case "menu" | "tools":
                    # Try using the samsungvd.remoteControl capability with sendKey command
                    await device.command(
                        "main", "samsungvd.remoteControl", "sendKey", ["TOOLS"]
                    )
                    _LOG.debug("[%s] SmartThings: Sent TOOLS key", self.log_id)
                case _:
                    _LOG.warning(
                        "[%s] Unknown SmartThings command: %s", self.log_id, command
                    )
                    return False

            # Query status to get updated info if requested
            if query_after:
                await asyncio.sleep(delay)
                update = await self.query_smartthings_status(force=True)
                if update:
                    self.events.emit(DeviceEvents.UPDATE, self.get_entity_id(), update)

            return True
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "[%s] Error sending %s via SmartThings: %s", self.log_id, command, ex
            )
            return False

    async def channel_up_smartthings(self) -> bool:
        """Send channel up command via SmartThings API."""
        return await self.send_smartthings_command("channel_up", query_after=True)

    async def channel_down_smartthings(self) -> bool:
        """Send channel down command via SmartThings API."""
        return await self.send_smartthings_command("channel_down", query_after=True)

    async def fast_forward_smartthings(self) -> bool:
        """Send fast forward command via SmartThings API."""
        return await self.send_smartthings_command("fast_forward")

    async def rewind_smartthings(self) -> bool:
        """Send rewind command via SmartThings API."""
        return await self.send_smartthings_command("rewind")

    async def send_menu_smartthings(self) -> bool:
        """Send menu/tools command via SmartThings API."""
        return await self.send_smartthings_command("menu")

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

    async def query_smartthings_status(self, force: bool = False) -> dict[str, Any]:
        """
        Query comprehensive status from SmartThings API.

        Retrieves media playback state, volume, input source, mute status,
        and other attributes if available.

        Args:
            force: If True, ignore polling interval and query immediately

        Returns:
            Dictionary with MediaAttr keys and values to emit
        """
        update = {}

        if not self._smartthings_api or not self._smartthings_device_id:
            return update

        # Rate limiting: only poll every 5 seconds unless forced
        if not force and self._last_smartthings_poll:
            time_since_poll = (
                datetime.utcnow() - self._last_smartthings_poll
            ).total_seconds()
            if time_since_poll < 5:
                _LOG.debug(
                    "[%s] Skipping SmartThings poll (last poll %.1fs ago)",
                    self.log_id,
                    time_since_poll,
                )
                return update

        try:
            # Get the device object to access its status
            devices = await self._smartthings_api.devices()
            device = next(
                (d for d in devices if d.device_id == self._smartthings_device_id), None
            )

            if not device or not hasattr(device, "status") or not device.status:
                _LOG.warning(
                    "[%s] SmartThings device or status not available", self.log_id
                )
                return update

            status = device.status
            self._last_smartthings_poll = datetime.utcnow()

            if not hasattr(status, "attributes"):
                _LOG.warning("[%s] Device status has no attributes", self.log_id)
                return update

            attributes = status.attributes

            # Log available attributes for debugging (only on first poll)
            if not self._smartthings_capabilities:
                self._smartthings_capabilities = set(attributes.keys())
                _LOG.info(
                    "[%s] SmartThings attributes detected: %s",
                    self.log_id,
                    ", ".join(sorted(self._smartthings_capabilities)),
                )
                # Also log actual values for debugging
                _LOG.debug("[%s] SmartThings attribute values:", self.log_id)
                for attr_name, attr_obj in attributes.items():
                    if hasattr(attr_obj, "value"):
                        _LOG.debug("  %s = %s", attr_name, attr_obj.value)

            # Volume
            volume_attr = attributes.get("volume")
            if volume_attr and hasattr(volume_attr, "value"):
                update[MediaAttr.VOLUME] = int(volume_attr.value)
                _LOG.debug(
                    "[%s] SmartThings volume: %s", self.log_id, volume_attr.value
                )

            # Mute status
            mute_attr = attributes.get("mute")
            if mute_attr and hasattr(mute_attr, "value"):
                # Convert "muted"/"unmuted" to boolean
                is_muted = mute_attr.value == "muted"
                update[MediaAttr.MUTED] = is_muted
                _LOG.debug("[%s] SmartThings mute: %s", self.log_id, is_muted)

            # Media playback state
            playback_attr = attributes.get("playbackStatus")
            if playback_attr and hasattr(playback_attr, "value"):
                playback_state = playback_attr.value
                _LOG.debug("[%s] SmartThings playback: %s", self.log_id, playback_state)
                # Note: ucapi STATE is for power (ON/OFF), not playback state

            # Media title (check various possible attribute names)
            for title_attr_name in [
                "mediaTitle",
                "title",
                "programName",
                "trackDescription",
            ]:
                title_attr = attributes.get(title_attr_name)
                if title_attr and hasattr(title_attr, "value") and title_attr.value:
                    update[MediaAttr.MEDIA_TITLE] = title_attr.value
                    _LOG.debug(
                        "[%s] SmartThings media title: %s",
                        self.log_id,
                        title_attr.value,
                    )
                    break

            # Media artist
            artist_attr = attributes.get("trackDescription")
            if artist_attr and hasattr(artist_attr, "value") and artist_attr.value:
                # Check if we didn't already use this as title
                if (
                    MediaAttr.MEDIA_TITLE not in update
                    or update[MediaAttr.MEDIA_TITLE] != artist_attr.value
                ):
                    update[MediaAttr.MEDIA_ARTIST] = artist_attr.value
                    _LOG.debug(
                        "[%s] SmartThings media artist: %s",
                        self.log_id,
                        artist_attr.value,
                    )

            # Input source
            input_attr = attributes.get("inputSource")
            if input_attr and hasattr(input_attr, "value"):
                source = input_attr.value
                self._active_source = source
                update[MediaAttr.SOURCE] = source
                _LOG.debug("[%s] SmartThings input source: %s", self.log_id, source)

            # Supported input sources are now retrieved via _get_smartthings_source_list()
            # and used as fallback in _update_app_list() when local API fails

            # TV Channel number and name
            channel_attr = attributes.get("tvChannel")
            channel_name_attr = attributes.get("tvChannelName")

            # Build channel string if we have channel info and no media title yet
            if (MediaAttr.MEDIA_TITLE not in update) and (
                channel_attr or channel_name_attr
            ):
                channel_parts = []

                if (
                    channel_attr
                    and hasattr(channel_attr, "value")
                    and channel_attr.value
                ):
                    channel_parts.append(f"Channel {channel_attr.value}")
                    _LOG.debug(
                        "[%s] SmartThings TV channel: %s",
                        self.log_id,
                        channel_attr.value,
                    )

                if (
                    channel_name_attr
                    and hasattr(channel_name_attr, "value")
                    and channel_name_attr.value
                ):
                    channel_parts.append(channel_name_attr.value)
                    _LOG.debug(
                        "[%s] SmartThings TV channel name: %s",
                        self.log_id,
                        channel_name_attr.value,
                    )

                if channel_parts:
                    update[MediaAttr.MEDIA_TITLE] = " - ".join(channel_parts)
                    _LOG.debug(
                        "[%s] Using channel info as media title: %s",
                        self.log_id,
                        update[MediaAttr.MEDIA_TITLE],
                    )

            return update

        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "[%s] Error querying SmartThings status: %s",
                self.log_id,
                ex,
                exc_info=True,
            )
            return update

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
