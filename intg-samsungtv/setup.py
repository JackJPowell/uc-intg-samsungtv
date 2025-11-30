"""
Setup flow for Samsung TV integration.

:copyright: (c) 2023-2024 by Jack Powell
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
import re
from typing import Any

from const import SamsungDevice
from samsungtvws import SamsungTVWS
from ucapi import IntegrationSetupError, RequestUserInput
from ucapi_framework import BaseSetupFlow

_LOG = logging.getLogger(__name__)

_MANUAL_INPUT_SCHEMA = RequestUserInput(
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
            "id": "address",
            "label": {
                "en": "IP Address",
            },
        },
    ],
)


class SamsungSetupFlow(BaseSetupFlow[SamsungDevice]):
    """Setup flow handler for Samsung TV integration."""

    def get_manual_entry_form(self) -> RequestUserInput:
        """
        Get the manual entry form for Samsung TV setup.

        :return: RequestUserInput for manual entry
        """
        return _MANUAL_INPUT_SCHEMA

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> RequestUserInput | SamsungDevice:
        """
        Process user data response from the first setup process screen.

        :param msg: response data from the requested user data
        :return: the setup action on how to continue
        """
        ip = input_values.get("address", None)

        try:
            reports_power_state = False
            if ip is None:
                return _MANUAL_INPUT_SCHEMA

            _LOG.debug("Connecting to Samsung TV at %s", ip)

            tv = SamsungTVWS(
                ip,
                port=8002,
                timeout=30,
                name="Unfolded Circle",
            )

            info = tv.rest_device_info()
            tv.close()

            if info and info.get("device", None).get("PowerState", None) is not None:
                reports_power_state = True

            _LOG.info("Samsung TV info: %s", info)

            # if we are adding a new device: make sure it's not already configured
            if self._add_mode and self.config.contains(info.get("identifier")):
                _LOG.info(
                    "Skipping found device %s: already configured",
                    info.get("device").get("name"),
                )
                raise IntegrationSetupError("Device already configured")
            name = re.sub(r"^\[TV\] ", "", info.get("device").get("name"))

            return SamsungDevice(
                identifier=info.get("id"),
                name=name,
                token=tv.token,
                address=ip,
                mac_address=info.get("device").get(
                    "wifiMac"
                ),  # Both wired and wireless use the same key
                reports_power_state=reports_power_state,
            )

        except Exception as err:  # pylint: disable=broad-except
            _LOG.error("Setup error for Samsung TV at %s: %s", ip, err)
            raise IntegrationSetupError("Device setup failed") from err
