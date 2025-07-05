"""
This module implements the Samsung TV communication of the Remote Two integration driver.

"""

import asyncio
import contextlib
import logging
from asyncio import AbstractEventLoop
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, ParamSpec, TypeVar, cast

import aiohttp
import wakeonlan
import config
from config import SamsungDevice
from pyee.asyncio import AsyncIOEventEmitter
from samsungtvws import SamsungTVWS
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.event import ED_INSTALLED_APP_EVENT, parse_installed_app
from samsungtvws.exceptions import HttpApiError
from samsungtvws.remote import ChannelEmitCommand, SendRemoteKey
from ucapi.media_player import Attributes as MediaAttr

_LOG = logging.getLogger(__name__)

BACKOFF_MAX = 30
BACKOFF_SEC = 2


class EVENTS(IntEnum):
    """Internal driver events."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    PAIRED = 3
    ERROR = 4
    UPDATE = 5


_SamsungTvT = TypeVar("_SamsungTvT", bound="SamsungTv")
_P = ParamSpec("_P")


class PowerState(StrEnum):
    """Playback state for companion protocol."""

    OFF = "OFF"
    ON = "ON"
    STANDBY = "STANDBY"


class SamsungTv:
    """Representing an Samsung TV Device."""

    def __init__(
        self, device: SamsungDevice, loop: AbstractEventLoop | None = None
    ) -> None:
        """Create instance."""
        self._loop: AbstractEventLoop = loop or asyncio.get_running_loop()
        self.events = AsyncIOEventEmitter(self._loop)
        self._is_connected: bool = False
        self._samsungtv: SamsungTVWS | None = None
        self._samsungtv_remote: SamsungTVWSAsyncRemote | None = None
        self._device: SamsungDevice = device
        self._mac_address: str = device.mac_address
        self._connect_task = None
        self._connection_attempts: int = 0
        self._polling = None
        self._poll_interval: int = 10
        self._state: PowerState | None = None
        self._app_list: dict[str, str] = {}
        self._volume_level: float = 0.0
        self._end_of_power_off: datetime | None = None
        self._end_of_power_on: datetime | None = None
        self._active_source: str = ""
        self._power_on_task: asyncio.Task | None = None
        self._power_state: PowerState | None = None

    @property
    def device_config(self) -> SamsungDevice:
        """Return the device configuration."""
        return self._device

    @property
    def identifier(self) -> str:
        """Return the device identifier."""
        if not self._device.identifier:
            raise ValueError("Instance not initialized, no identifier available")
        return self._device.identifier

    @property
    def log_id(self) -> str:
        """Return a log identifier."""
        return self._device.name if self._device.name else self._device.identifier

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._device.name

    @property
    def address(self) -> str | None:
        """Return the optional device address."""
        return self._device.address

    @property
    def state(self) -> PowerState | None:
        """Return the device state."""
        if self._power_state is None:
            return PowerState.OFF
        return self._power_state

    @property
    def is_connected(self) -> bool:
        """Return if the device is connected."""
        return self._samsungtv is not None and self._samsungtv.is_alive()

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
        if self._device.token == "":
            return 30
        return 3

    async def connect(self) -> None:
        """Establish connection to TV."""
        if self._samsungtv is not None and self._samsungtv.is_alive():
            return

        _LOG.debug("[%s] Connecting to device", self.log_id)
        if not self._connect_task and not self._samsungtv:
            self.events.emit(EVENTS.CONNECTING, self._device.identifier)
            self._connect_task = asyncio.create_task(self._connect_setup())
        else:
            _LOG.debug(
                "[%s] Not starting connect setup (Samsung TV: %s, ConnectTask: %s)",
                self.log_id,
                self._samsungtv is not None,
                self._connect_task is not None,
            )

    async def _connect_setup(self) -> None:
        try:
            await self._connect()

            if (
                self._samsungtv is not None
                and self._samsungtv.token != self._device.token
            ):
                _LOG.debug(
                    "[%s] Token changed - Old: %s, New: %s",
                    self.log_id,
                    self._device.token,
                    self._samsungtv.token,
                )
                self._device.token = self._samsungtv.token
                config.devices.update(self._device)

            if self._samsungtv is not None and self._samsungtv.is_alive():
                _LOG.debug("[%s] Device is alive", self.log_id)
                self.events.emit(
                    EVENTS.UPDATE, self._device.identifier, {"state": PowerState.ON}
                )
            else:
                _LOG.debug("[%s] Device is not alive", self.log_id)
                self.events.emit(
                    EVENTS.UPDATE, self._device.identifier, {"state": PowerState.OFF}
                )
                await self.disconnect()
        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Could not connect: %s", self.log_id, err)
            self._samsungtv = None
        finally:
            _LOG.debug("[%s] Connect setup finished", self.log_id)

        self.events.emit(EVENTS.CONNECTED, self._device.identifier)
        _LOG.debug("[%s] Connected", self.log_id)

        await asyncio.sleep(1)
        await self._start_polling()
        await self._update_app_list()

    async def _connect(self) -> None:
        """Connect to the device."""
        _LOG.debug(
            "[%s] Connecting to TVWS device at IP address: %s",
            self.log_id,
            self._device.address,
        )
        self._samsungtv = SamsungTVWSAsyncRemote(
            host=self._device.address,
            port=8002,
            key_press_delay=0.1,
            token=self._device.token,
            name="Unfolded Circle Remote",
            timeout=self.timeout,
        )

        try:
            print("[%s] Start listening", self.log_id)
            await self._samsungtv.start_listening(self.handle_remote_event)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(
                f"An error occurred while connecting to the TV (Start Listening): {e}"
            )

    async def disconnect(self, continue_polling: bool = True) -> None:
        """Disconnect from Samsung."""
        _LOG.debug("[%s] Disconnecting from device", self.log_id)
        if not continue_polling:
            await self._stop_polling()

        try:
            if self._connect_task:
                _LOG.debug("[%s] Cancelling connect task", self.log_id)
                self._connect_task.cancel()
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception(
                "[%s] An error occurred while cancelling the connect task: %s",
                self.log_id,
                err,
            )
        finally:
            self._connect_task = None

        try:
            if self._samsungtv:
                _LOG.debug("[%s] Closing SamsungTVWS connection", self.log_id)
                await self._samsungtv.close()
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception(
                "[%s] An error occurred while closing SamsungTVWS connection: %s",
                self.log_id,
                err,
            )
        finally:
            self._samsungtv = None

        _LOG.debug("[%s] Disconnected", self.log_id)

    async def close(self) -> None:
        """Close the connection."""
        if self._samsungtv:
            await self._samsungtv.close()
            self._samsungtv = None

    async def _start_polling(self) -> None:
        if not self._polling:
            self._polling = self._loop.create_task(self._poll_worker())
            _LOG.debug("[%s] Polling started", self.log_id)

    async def _stop_polling(self) -> None:
        if self._polling:
            self._polling.cancel()
            self._polling = None
            _LOG.debug("[%s] Polling stopped", self.log_id)
        else:
            _LOG.debug("[%s] Polling was already stopped", self.log_id)

    async def check_connection_and_reconnect(self) -> None:
        """Check if the connection is alive and reconnect if not."""
        if self._samsungtv is None:
            _LOG.debug("[%s] Connection is not alive, reconnecting", self.log_id)
            await self.connect()
            return

        try:
            if not self._samsungtv.is_alive():
                await self.disconnect()
                await self.connect()
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception(
                "[%s] An error occurred while reconnecting: %s",
                self.log_id,
                err,
            )

    async def _process_update(self, data: {}) -> None:  # pylint: disable=too-many-branches
        _LOG.debug("[%s] Process update", self.log_id)
        update = {}

        # We only update device state (playing, paused, etc) if the power state is On
        # otherwise we'll set the state to Off in the polling method
        self._state = data.device_state
        update["state"] = data.device_state

    async def _update_app_list(self) -> None:
        _LOG.debug("[%s] Updating app list", self.log_id)
        update = {}

        try:
            update["source_list"] = ["TV", "HDMI", "HDMI1", "HDMI2", "HDMI3", "HDMI4"]
            if self._samsungtv.is_alive():
                await self._samsungtv.app_list()
                if not self._app_list:
                    await self._get_app_list_via_remote()

            if self._app_list is None or len(self._app_list) == 0:
                _LOG.error("[%s] Unable to retrieve app list.", self.log_id)

            for app in self._app_list:
                update["source_list"].append(app)
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] App list: protocol error", self.log_id)

        self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

    async def _get_app_list_via_remote(self) -> list[str, str]:
        if not self.is_connected:
            return {}
        try:
            app_list = await self._samsungtv.send_command(
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
            _LOG.debug("TV is powering off, not sending launch_app command")
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
                app_id = self._app_list[app_name]

        async with aiohttp.ClientSession() as session:
            with contextlib.suppress(HttpApiError):
                rest_api = SamsungTVAsyncRest(
                    host=self._device.address, port=8002, session=session
                )
                await rest_api.rest_app_run(app_id)

    async def send_key(self, key: str, **kwargs: Any) -> None:
        """Send a key to the TV."""
        hold_time = kwargs.get("hold_time", None)  # in ms
        await self.check_connection_and_reconnect()
        if self._samsungtv is not None and self._samsungtv.is_alive():
            hold_time = float(hold_time / 1000) if hold_time else None
            if hold_time:
                await self._samsungtv.send_command(SendRemoteKey.hold(key, hold_time))
            else:
                await self._samsungtv.send_command(SendRemoteKey.click(key))
            return
        _LOG.error(
            "[%s] Cannot send key '%s', TV is not connected (_samsungtv: %s)",
            self.log_id,
            key,
            self._samsungtv is not None,
        )

    async def _poll_worker(self) -> None:
        await asyncio.sleep(1)
        while True:
            self.get_power_state()
            await asyncio.sleep(5)

    async def toggle_power(self, power: bool | None = None) -> None:
        """Handle power state change."""
        update = {}
        if self.power_off_in_progress:
            _LOG.debug("TV is powering off, attempting to send power command")
            await self.send_key("KEY_POWER")
            self._end_of_power_off = None
            self._power_on_task = asyncio.create_task(self.power_on_wol())
            update["state"] = PowerState.ON
            self.events.emit(EVENTS.UPDATE, self._device.identifier, update)
            return

        if self.power_on_in_progress:
            _LOG.debug("TV is powering on, not sending power command")
            return

        if power is None:
            self.get_power_state()
            power = self._power_state in [PowerState.OFF, PowerState.STANDBY]

        if power:
            if self.device_config.reports_power_state:
                if self.device_config.supports_art_mode:
                    rest = RestTV(self.device_config)
                    in_art_mode = rest.tv.art().get_artmode()
                    rest.close()
                    _LOG.debug(
                        "[%s] Device is in art mode: %s", self.log_id, in_art_mode
                    )
                    if in_art_mode:
                        self.send_key("KEY_POWER")
                else:
                    if self._power_state == PowerState.ON:
                        _LOG.debug("[%s] Device is already ON", self.log_id)
                        self._power_state = PowerState.ON
                    elif self._power_state == PowerState.STANDBY:
                        _LOG.debug("[%s] Device is in standby mode", self.log_id)
                        await self.send_key("KEY_POWER")
                        self._power_state = PowerState.ON
                    else:
                        self._end_of_power_on = datetime.utcnow() + timedelta(
                            seconds=17
                        )
                        self._power_on_task = asyncio.create_task(self.power_on_wol())
                        self._power_state = PowerState.ON
            else:
                if self._samsungtv is not None and self._samsungtv.is_alive():
                    _LOG.debug("[%s] Device is already ON", self.log_id)
                    self._power_state = PowerState.ON
                else:
                    self._end_of_power_on = datetime.utcnow() + timedelta(seconds=17)
                    self._power_on_task = asyncio.create_task(self.power_on_wol())
                    self._power_state = PowerState.ON
        else:
            await self.send_key("KEY_POWER")
            self._end_of_power_off = datetime.utcnow() + timedelta(seconds=65)
            self._power_state = PowerState.OFF

        update["state"] = self._power_state
        self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

    async def power_on_wol(self) -> None:
        """Power on the TV."""
        update = {}
        for i in range(8):
            _LOG.debug("[%s] Sending magic packet (%s)", self.log_id, i)
            wakeonlan.send_magic_packet(self._device.mac_address)
            await asyncio.sleep(2)
            if self.power_state == PowerState.ON:
                break
            else:
                _LOG.debug("[%s] Device is not alive yet", self.log_id)
                await self.check_connection_and_reconnect()

        if not self.is_connected:
            _LOG.warning("[%s] Unable to wake TV", self.log_id)
            self._power_state = PowerState.OFF

        update["state"] = self._power_state
        self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

    def get_power_state(self) -> PowerState:
        """Return the power status of the device."""
        update = {}
        samsungtv = None
        if isinstance(self, SamsungTVWSAsyncRemote):
            samsungtv = self
        else:
            samsungtv = self._samsungtv

        if self.device_config.reports_power_state:
            power_state = (
                self.get_device_info().get("device", None).get("PowerState", None)
            )
            match power_state:
                case "on":
                    self._power_state = PowerState.ON
                case "standby":
                    self._power_state = PowerState.STANDBY
                case "off":
                    self._power_state = PowerState.OFF
                case _:
                    self._power_state = PowerState.OFF
        else:
            if samsungtv is not None and samsungtv.is_alive():
                if self.power_off_in_progress:
                    self._power_state = PowerState.OFF
                    _LOG.debug("[%s] Device is alive", self.log_id)
                else:
                    self._power_state = PowerState.ON
                    _LOG.debug("[%s] Device is alive", self.log_id)
                    self._end_of_power_on = None
            else:
                _LOG.debug(
                    "[%s] SamsungTVWS Connection is not alive (Samsung TV: %s, ConnectTask: %s)",
                    self.log_id,
                    self._samsungtv is not None,
                    self._connect_task is not None,
                )
                self._power_state = PowerState.OFF

        update["state"] = self._power_state
        self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

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
            _LOG.debug("Installed apps updated: %s", self._app_list)

    def get_device_info(self) -> dict[str, Any]:
        """Get REST info from the TV."""
        try:
            rest = RestTV(self.device_config)
            info = rest.tv.rest_device_info()
            _LOG.debug("REST info: %s", info)
            rest.close()
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Unable to retreive rest info. TV may be offline", self.log_id
            )
            rest.close()
            info = {"device": {"PowerState": "off"}}
        return info

    def get_art_info(self) -> dict[str, Any]:
        """Get ART info from the TV."""
        try:
            rest = RestTV(self.device_config)

            supported = rest.tv.art().supported()
            _LOG.debug("Art Supported: %s", supported)
            if supported:
                _LOG.debug("Art Mode: %s", rest.tv.art().get_artmode())
                _LOG.debug("Art Available: %s", rest.tv.art().available())
                _LOG.debug("Art Current: %s", rest.tv.art().get_current())
            rest.close()
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Unable to retreive art info. TV may be offline %s",
                self.log_id,
                ex,
            )
            rest.close()
        return

    def toggle_art_mode(self) -> None:
        """Toggle ART info from the TV."""
        try:
            rest = RestTV(self.device_config)

            supported = rest.tv.art().supported()
            _LOG.debug("Art Supported: %s", supported)
            in_art_mode = rest.tv.art().get_artmode()
            _LOG.debug("[%s] Device is in art mode: %s", self.log_id, in_art_mode)
            if in_art_mode:
                rest.tv.art().set_artmode(False)
            else:
                rest.tv.art().set_artmode(True)
            rest.close()
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.debug(
                "[%s] Unable to retreive art info. TV may be offline %s",
                self.log_id,
                ex,
            )
            rest.close()
        return


class RestTV:
    """Representing an Samsung TV Device with REST API."""

    def __init__(
        self,
        device_config: SamsungDevice,
    ) -> SamsungTVWS:
        """Create instance."""
        self.tv = SamsungTVWS(
            device_config.address,
            port=8002,
            timeout=2,
            name="Unfolded Circle",
        )

    async def close(self) -> None:
        """Get REST info from the TV."""
        self.tv.close()
        return
