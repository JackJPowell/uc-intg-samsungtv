"""
This module implements the Samsung TV communication of the Remote Two integration driver.

"""

import asyncio
import contextlib
import logging
from asyncio import AbstractEventLoop
from datetime import datetime, timedelta
from enum import Enum, IntEnum
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


class PowerState(Enum):
    """Playback state for companion protocol."""

    OFF = "OFF"
    ON = "ON"


class SamsungTv:
    """Representing an Samsung TV Device."""

    def __init__(
        self, device: SamsungDevice, loop: AbstractEventLoop | None = None
    ) -> None:
        """Create instance."""
        self._loop: AbstractEventLoop = loop or asyncio.get_running_loop()
        self.events = AsyncIOEventEmitter(self._loop)
        self._is_on: bool = False
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
    def is_on(self) -> bool | None:
        """Whether the Samsung TV is on or off. Returns None if not connected."""
        return self._is_on

    @property
    def state(self) -> PowerState | None:
        """Return the device state."""
        if self.is_on:
            return PowerState.ON
        return PowerState.OFF

    @property
    def power_off_in_progress(self) -> bool:
        """Return if power off has been recently requested."""
        return (
            self._end_of_power_off is not None
            and self._end_of_power_off > datetime.utcnow()
        )

    def _backoff(self) -> float:
        if self._connection_attempts * BACKOFF_SEC >= BACKOFF_MAX:
            return BACKOFF_MAX

        return self._connection_attempts * BACKOFF_SEC

    def _handle_disconnect(self):
        """Handle that the device disconnected and restart connect loop."""
        _ = asyncio.ensure_future(self._stop_polling())
        if self._samsungtv:
            self._samsungtv = None
        self._start_connect_loop()

    async def connect(self) -> None:
        """Establish connection to TV."""
        if self._samsungtv is not None and self._samsungtv.is_alive():
            return

        _LOG.debug("[%s] Connecting to device", self.log_id)
        self._start_connect_loop()

    def _start_connect_loop(self) -> None:
        if not self._connect_task and not self._samsungtv:
            # or (self._samsungtv and not self._samsungtv.is_alive())
            self.events.emit(EVENTS.CONNECTING, self._device.identifier)
            self._connect_task = asyncio.create_task(self._connect_loop())
        else:
            _LOG.debug(
                "[%s] Not starting connect loop (Samsung TV: %s, isOn: %s)",
                self.log_id,
                self._samsungtv is None,
                self._is_on,
            )

    async def _connect_loop(self) -> None:
        _LOG.debug("[%s] Starting connect loop", self.log_id)
        # is_connected = False

        # if self._samsungtv is not None:
        #     if self._samsungtv.is_alive():
        #         is_connected = True
        #         _LOG.debug("[%s] Already connected", self.log_id)

        # while not is_connected:
        #     if self._samsungtv is not None:
        #         if self._samsungtv.is_alive():
        #             is_connected = True
        #             _LOG.debug("[%s] Already connected", self.log_id)
        #             break
        #     await self.close()
        #     await self._connect_once()

        while self._samsungtv is None:
            await self._connect_once()
            if self._samsungtv is not None:
                break

            self._connection_attempts += 1
            backoff = self._backoff()
            _LOG.debug("[%s] Trying to connect again in %ds", self.log_id, backoff)
            await asyncio.sleep(backoff)

        _LOG.debug("[%s] Connect loop ended", self.log_id)
        self._connect_task = None

        # Reset the backoff counter
        self._connection_attempts = 0

        await self._start_polling()
        await self._update_app_list()

        self.events.emit(EVENTS.CONNECTED, self._device.identifier)
        _LOG.debug("[%s] Connected", self.log_id)

    async def _connect_once(self) -> None:
        try:
            await self._connect()

            if (
                self._samsungtv is not None
                and self._samsungtv.token != self._device.token
            ):
                _LOG.debug("[%s] Token changed, reconnecting", self.log_id)
                self._device.token = self._samsungtv.token
                config.devices.update(self._device)

            if self._samsungtv is not None and self._samsungtv.is_alive():
                _LOG.debug("[%s] Device is alive", self.log_id)
                self._is_on = True
                self.events.emit(
                    EVENTS.UPDATE, self._device.identifier, {"state": PowerState.ON}
                )
            else:
                _LOG.debug("[%s] Device is not alive", self.log_id)
                self._is_on = False
                self.events.emit(
                    EVENTS.UPDATE, self._device.identifier, {"state": PowerState.OFF}
                )
        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Could not connect: %s", self.log_id, err)
            self._samsungtv = None
        finally:
            _LOG.debug("[%s] Connect once finished", self.log_id)

    async def _connect(self) -> None:
        """Connect to the device."""
        _LOG.debug("[%s] Connecting to device", self.log_id)
        self._samsungtv = SamsungTVWSAsyncRemote(
            host=self._device.address,
            port=8002,
            key_press_delay=0.1,
            token=self._device.token,
            name="Unfolded Circle Remote",
        )

        try:
            print("[%s] Start listening", self.log_id)
            await self._samsungtv.start_listening(handle_remote_event)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(
                f"An error occurred while connecting to the TV (Start Listening): {e}"
            )

    async def disconnect(self) -> None:
        """Disconnect from Samsung."""
        _LOG.debug("[%s] Disconnecting from device", self.log_id)
        await self._stop_polling()

        try:
            if self._samsungtv:
                await self._samsungtv.close()
            if self._connect_task:
                self._connect_task.cancel()
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception(
                "[%s] An error occurred while disconnecting: %s", self.log_id, err
            )
        finally:
            self._samsungtv = None
            self._connect_task = None

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
                await self.close()
                self._samsungtv = None
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

        # self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

    async def _update_app_list(self) -> None:
        _LOG.debug("[%s] Updating app list", self.log_id)
        update = {}
        app_list = None

        try:
            update["sourceList"] = ["TV", "HDMI"]
            if self._samsungtv.is_alive():
                app_list = await self._samsungtv.app_list()
                if not app_list:
                    app_list = await self._get_app_list_via_remote()
            if not app_list:
                _LOG.error("[%s] Unable to retrieve app list.", self.log_id)
                return
            for app in app_list:
                self._app_list[app.get("name")] = app.get("appId")
                update["sourceList"].append(app.get("name"))
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] App list: protocol error", self.log_id)

        self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

    async def _get_app_list_via_remote(self) -> dict[str, str]:
        if not self.is_on or not self._samsungtv:
            return {}

        return await self._samsungtv.send_commands(
            ChannelEmitCommand.get_installed_app()
        )

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
            else:
                app_id = self._app_list[app_name]

        async with aiohttp.ClientSession() as session:
            with contextlib.suppress(HttpApiError):
                rest_api = SamsungTVAsyncRest(
                    host=self._device.address, port=8002, session=session
                )
                await rest_api.rest_app_run(app_id)

    async def send_key(self, key: str) -> None:
        """Send a key to the TV."""
        await self._samsungtv.send_command(SendRemoteKey.click(key))

    async def _poll_worker(self) -> None:
        await asyncio.sleep(1)
        while True:
            self.check_power_status()
            await asyncio.sleep(5)

    async def toggle_power(self, power: bool | None = None) -> None:
        """Handle power state change."""
        if self.power_off_in_progress:
            _LOG.debug("TV is powering off, not sending power command")
            return
        update = {}
        if not power:
            await self.connect()
            self.check_power_status()
            power = not self._is_on

        if power:
            await self.close()
            for i in range(6):
                _LOG.debug("[%s] Sending magic packet (%s)", self.log_id, i)
                wakeonlan.send_magic_packet(self._device.mac_address)
                await asyncio.sleep(3)
                await self.check_connection_and_reconnect()
                self.check_power_status()
                if self._is_on:
                    break

            if not self._is_on:
                _LOG.warning("[%s] Unable to wake TV", self.log_id)
                return

            await self._update_app_list()
            update["state"] = PowerState.ON
        else:
            await self.send_key("KEY_POWER")
            self._end_of_power_off = datetime.utcnow() + timedelta(seconds=15)
            self._is_on = False
            await self.disconnect()
            update["state"] = PowerState.OFF

        self.events.emit(EVENTS.UPDATE, self._device.identifier, update)

    def check_power_status(self) -> None:
        """Return the power status of the device."""
        update = {}
        previous_state = self.is_on

        if self._samsungtv is not None:
            if self._samsungtv.is_alive():
                _LOG.debug("[%s] Device is alive", self.log_id)
                self._is_on = True
                update["state"] = PowerState.ON
            else:
                _LOG.debug(
                    "[%s] Device is not alive _samsungtv is not None", self.log_id
                )
                self._is_on = False
                update["state"] = PowerState.OFF
        else:
            _LOG.debug("[%s] Device is not alive. _samsungtv is None", self.log_id)
            self._is_on = False
            update["state"] = PowerState.OFF

        # tv = SamsungTVWS(
        #     self._device.address,
        #     port=8002,
        #     token=self._device.token,
        #     timeout=1,
        #     name="Unfolded Circle Remote",
        # )
        # try:
        #     tv.rest_device_info()
        #     self._is_on = True
        #     update["state"] = PowerState.ON
        #     tv = None
        # except Exception:  # pylint: disable=broad-exception-caught
        #     self._is_on = False
        #     update["state"] = PowerState.OFF

        if self.power_off_in_progress:
            self._is_on = False

        if previous_state != self.is_on:
            self.events.emit(EVENTS.UPDATE, self._device.identifier, update)


def handle_remote_event(event: str, response: Any) -> None:
    """Handle remote events."""
    if event == ED_INSTALLED_APP_EVENT:
        apps = {
            app["name"]: app["appId"]
            for app in sorted(
                parse_installed_app(response),
                key=lambda app: cast(str, app["name"]),
            )
        }
        print(apps)
