"""
Setup flow for Apple TV Remote integration.

:copyright: (c) 2023-2024 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import re
from enum import IntEnum
import config
from config import SamsungDevice
from samsungtvws import SamsungTVWS
from discover import SddpDiscovery
from ucapi import (
    AbortDriverSetup,
    DriverSetupRequest,
    IntegrationSetupError,
    RequestUserInput,
    SetupAction,
    SetupComplete,
    SetupDriver,
    SetupError,
    UserDataResponse,
)

_LOG = logging.getLogger(__name__)


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    CONFIGURATION_MODE = 1
    DISCOVER = 2
    DEVICE_CHOICE = 3


_setup_step = SetupSteps.INIT
_cfg_add_device: bool = False

_user_input_manual = RequestUserInput(
    {"en": "Samsung TV Setup"},
    [
        {
            "id": "info",
            "label": {
                "en": "Setup your Samsung TV",
            },
            "field": {
                "label": {
                    "value": {
                        "en": (
                            "Please supply the IP address or Hostname of your Samsung TV."
                        ),
                    }
                }
            },
        },
        {
            "field": {"text": {"value": ""}},
            "id": "ip",
            "label": {
                "en": "IP Address",
            },
        },
    ],
)


async def driver_setup_handler(
    msg: SetupDriver,
) -> SetupAction:  # pylint: disable=too-many-return-statements
    """
    Dispatch driver setup requests to corresponding handlers.

    Either start the setup process or handle the selected Apple TV device.

    :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement
    global _cfg_add_device  # pylint: disable=global-statement

    if isinstance(msg, DriverSetupRequest):
        _setup_step = SetupSteps.INIT
        _cfg_add_device = False
        return await _handle_driver_setup(msg)

    if isinstance(msg, UserDataResponse):
        _LOG.debug("%s", msg)
        if (
            _setup_step == SetupSteps.CONFIGURATION_MODE
            and "action" in msg.input_values
        ):
            return await _handle_configuration_mode(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") != "manual"
        ):
            return await _handle_creation(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") == "manual"
        ):
            return await _handle_manual()
        _LOG.error("No user input was received for step: %s", msg)
    elif isinstance(msg, AbortDriverSetup):
        _LOG.info("Setup was aborted with code: %s", msg.error)
        _setup_step = SetupSteps.INIT

    return SetupError()


async def _handle_driver_setup(
    msg: DriverSetupRequest,
) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver. The reconfigure flag determines the setup flow:

    - Reconfigure is True:
        show the configured devices and ask user what action to perform (add, delete, reset).
    - Reconfigure is False: clear the existing configuration and show device discovery screen.
      Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

    :param msg: driver setup request data, only `reconfigure` flag is of interest.
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement

    reconfigure = msg.reconfigure
    _LOG.debug("Starting driver setup, reconfigure=%s", reconfigure)

    if reconfigure:
        _setup_step = SetupSteps.CONFIGURATION_MODE

        # get all configured devices for the user to choose from
        dropdown_devices = []
        for device in config.devices.all():
            dropdown_devices.append(
                {"id": device.identifier, "label": {"en": f"{device.name}"}}
            )

        dropdown_actions = [
            {
                "id": "add",
                "label": {
                    "en": "Add a new Samsung TV",
                },
            },
        ]

        # add remove & reset actions if there's at least one configured device
        if dropdown_devices:
            dropdown_actions.append(
                {
                    "id": "update",
                    "label": {
                        "en": "Update information for selected Samsung TV",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "remove",
                    "label": {
                        "en": "Remove selected Samsung TV",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "reset",
                    "label": {
                        "en": "Reset configuration and reconfigure",
                        "de": "Konfiguration zurücksetzen und neu konfigurieren",
                        "fr": "Réinitialiser la configuration et reconfigurer",
                    },
                },
            )
        else:
            # dummy entry if no devices are available
            dropdown_devices.append({"id": "", "label": {"en": "---"}})

        return RequestUserInput(
            {"en": "Configuration mode", "de": "Konfigurations-Modus"},
            [
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_devices[0]["id"],
                            "items": dropdown_devices,
                        }
                    },
                    "id": "choice",
                    "label": {
                        "en": "Configured Devices",
                        "de": "Konfigurerte Geräte",
                        "fr": "Appareils configurés",
                    },
                },
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_actions[0]["id"],
                            "items": dropdown_actions,
                        }
                    },
                    "id": "action",
                    "label": {
                        "en": "Action",
                        "de": "Aktion",
                        "fr": "Appareils configurés",
                    },
                },
            ],
        )

    # Initial setup, make sure we have a clean configuration
    config.devices.clear()  # triggers device instance removal
    _setup_step = SetupSteps.DISCOVER
    return await _handle_discovery()


async def _handle_configuration_mode(
    msg: UserDataResponse,
) -> RequestUserInput | SetupComplete | SetupError:
    """
    Process user data response from the configuration mode screen.

    User input data:

    - ``choice`` contains identifier of selected device
    - ``action`` contains the selected action identifier

    :param msg: user input data from the configuration mode screen.
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement
    global _cfg_add_device  # pylint: disable=global-statement

    action = msg.input_values["action"]

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    match action:
        case "add":
            _cfg_add_device = True
        case "update":
            choice = msg.input_values["choice"]
            if not config.devices.remove(choice):
                _LOG.warning("Could not update device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            _setup_step = SetupSteps.DISCOVER
            return await _handle_discovery()
        case "remove":
            choice = msg.input_values["choice"]
            if not config.devices.remove(choice):
                _LOG.warning("Could not remove device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            config.devices.store()
            return SetupComplete()
        case "reset":
            config.devices.clear()  # triggers device instance removal
        case _:
            _LOG.error("Invalid configuration action: %s", action)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    _setup_step = SetupSteps.DISCOVER
    return _user_input_manual


async def _handle_manual() -> RequestUserInput | SetupError:
    return _user_input_manual


async def _handle_discovery() -> RequestUserInput | SetupError:
    """
    Process user data response from the first setup process screen.
    """
    global _setup_step  # pylint: disable=global-statement

    sddp = SddpDiscovery()
    await sddp.get(search_pattern="Samsung", response_wait_time=1)
    if len(sddp.discovered) > 0:
        _LOG.debug("Found Samsung TVs")

        dropdown_devices = []
        for device in sddp.discovered:
            dropdown_devices.append(
                {"id": device.address, "label": {"en": f"{device.type}"}}
            )

        dropdown_devices.append({"id": "manual", "label": {"en": "Setup Manually"}})

        return RequestUserInput(
            {"en": "Discovered Samsung TVs"},
            [
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_devices[0]["id"],
                            "items": dropdown_devices,
                        }
                    },
                    "id": "ip",
                    "label": {
                        "en": "Discovered TVs:",
                    },
                },
            ],
        )

    # Initial setup, make sure we have a clean configuration
    config.devices.clear()  # triggers device instance removal
    _setup_step = SetupSteps.DISCOVER
    return _user_input_manual


async def _handle_creation(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response from the first setup process screen.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    reports_power_state = False
    ip = msg.input_values["ip"]
    if ip is not None and ip != "":
        _LOG.debug("Connecting to Samsung TV at %s", ip)

        tv = SamsungTVWS(
            ip,
            port=8002,
            timeout=30,
            name="Unfolded Circle",
        )

        info = tv.rest_device_info()

        if info and info.get("PowerState", None) is not None:
            reports_power_state = True

        _LOG.info("Samsung TV info: %s", info)

    # if we are adding a new device: make sure it's not already configured
    if _cfg_add_device and config.devices.contains(info.get("identifier")):
        _LOG.info(
            "Skipping found device %s: already configured",
            info.get("device").get("name"),
        )
        return SetupError(error_type=IntegrationSetupError.OTHER)
    name = re.sub(r"^\[TV\] ", "", info.get("device").get("name"))
    device = SamsungDevice(
        identifier=info.get("id"),
        name=name,
        token=tv.token,
        address=ip,
        mac_address=info.get("device").get(
            "wifiMac"
        ),  # Both wired and wireless use the same key
        reports_power_state=reports_power_state,
    )
    tv.close()
    config.devices.add_or_update(device)

    await asyncio.sleep(1)

    _LOG.info("Setup successfully completed for %s [%s]", device.name, device)

    return SetupComplete()
