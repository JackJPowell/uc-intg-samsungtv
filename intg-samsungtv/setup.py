"""
Setup flow for Samsung TV integration.

:copyright: (c) 2023-2024 by Jack Powell
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
import re
import ssl
import time
import json
from typing import Any
import aiohttp
import certifi
from const import (
    SamsungConfig,
    SMARTTHINGS_WORKER_AUTHORIZE,
)
from samsungtvws import SamsungTVWS
from ucapi import IntegrationSetupError, RequestUserInput, SetupError
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
        {
            "id": "smartthings_info",
            "label": {
                "en": "SmartThings OAuth (Optional)",
            },
            "field": {
                "label": {
                    "value": {
                        "en": (
                            "Enable SmartThings for advanced features like input source control. "
                            "Click 'Next' to skip or 'Authorize SmartThings' to set up OAuth."
                        ),
                    }
                }
            },
        },
        {
            "field": {"checkbox": {"value": False}},
            "id": "enable_smartthings",
            "label": {
                "en": "Authorize SmartThings",
            },
        },
    ],
)


_OAUTH_AUTH_SCHEMA = None  # Will be dynamically generated


class SamsungSetupFlow(BaseSetupFlow[SamsungConfig]):
    """Setup flow handler for Samsung TV integration."""

    def __init__(self, *args, **kwargs):
        """Initialize the setup flow."""
        super().__init__(*args, **kwargs)
        self._oauth_state: str | None = None
        self._device_info: dict[str, Any] | None = None
        self._smartthings_enabled: bool = False

    def get_manual_entry_form(self) -> RequestUserInput:
        """
        Get the manual entry form for Samsung TV setup.

        :return: RequestUserInput for manual entry
        """
        return _MANUAL_INPUT_SCHEMA

    async def get_additional_configuration_screen(
        self, device_config: SamsungConfig, previous_input: dict[str, Any]
    ) -> RequestUserInput | None:
        """
        Get additional configuration screen for SmartThings OAuth (optional).

        :param device_config: The device configuration from query_device
        :param previous_input: Input values from the previous screen
        :return: RequestUserInput for SmartThings OAuth or None to skip
        """
        # If SmartThings was already enabled, don't show this screen again
        if self._smartthings_enabled:
            return None

        return RequestUserInput(
            {"en": "SmartThings Setup (Optional)"},
            [
                {
                    "id": "smartthings_info",
                    "label": {"en": "SmartThings Integration"},
                    "field": {
                        "label": {
                            "value": {
                                "en": (
                                    "Enable SmartThings for features like HDMI input switching and improved power management.\\n\\n"
                                    "Click 'Skip' to complete setup without SmartThings, or check the box below to authorize."
                                )
                            }
                        }
                    },
                },
                {
                    "field": {"checkbox": {"value": False}},
                    "id": "enable_smartthings",
                    "label": {"en": "Enable SmartThings"},
                },
            ],
        )

    async def handle_additional_configuration_response(
        self, msg: Any
    ) -> SamsungConfig | RequestUserInput | SetupError | None:
        """
        Handle response from additional configuration screen.

        :param msg: User data response from additional screen
        :return: Updated config, next screen, or None to complete
        """
        input_values = msg.input_values

        if input_values.get("enable_smartthings").lower() == "false":
            return None

        # Check if we're handling OAuth tokens
        if "tokens_json" in input_values:
            tokens_json = input_values.get("tokens_json", "").strip()

            if not tokens_json:
                _LOG.error("Missing tokens JSON")
                return SetupError(IntegrationSetupError.OTHER)

            try:
                # Parse JSON from worker response
                tokens = json.loads(tokens_json)

                access_token = tokens.get("access_token", "").strip()
                refresh_token = tokens.get("refresh_token", "").strip()

                if not access_token or not refresh_token:
                    _LOG.error("Missing access_token or refresh_token in JSON")
                    return SetupError(IntegrationSetupError.OTHER)

                # Default to 24 hours (86400 seconds) expiration
                expires_at = int(time.time()) + 86400

                _LOG.info("Storing SmartThings OAuth tokens")

                # Update pending config with OAuth tokens
                self._pending_device_config.smartthings_access_token = access_token  # type: ignore
                self._pending_device_config.smartthings_refresh_token = refresh_token  # type: ignore
                self._pending_device_config.smartthings_token_expires = expires_at  # type: ignore

                return None  # Save and complete

            except json.JSONDecodeError as err:
                _LOG.error("Invalid JSON format: %s", err)
                return SetupError(IntegrationSetupError.OTHER)
            except Exception as err:  # pylint: disable=broad-except
                _LOG.error("Error storing OAuth tokens: %s", err, exc_info=True)
                return SetupError(IntegrationSetupError.OTHER)

        # Check if user wants to enable SmartThings
        enable_smartthings = input_values.get("enable_smartthings", False)

        if enable_smartthings:
            # Mark SmartThings as enabled so we don't show the checkbox again
            self._smartthings_enabled = True
            # Show OAuth authorization screen
            return await self._get_oauth_auth_screen()

        # User skipped SmartThings, complete setup
        return None

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> RequestUserInput | SamsungConfig | SetupError:
        """
        Process user data response from the first setup process screen.

        :param msg: response data from the requested user data
        :return: the setup action on how to continue
        """
        # Get IP from manual entry ("address")
        ip = input_values.get("address")

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
            if (
                self._add_mode
                and self.config is not None
                and self.config.contains(info.get("identifier", ""))
            ):
                _LOG.info(
                    "Skipping found device %s: already configured",
                    info.get("device").get("name"),
                )
                return SetupError(IntegrationSetupError.OTHER)
            name = re.sub(r"^\[TV\] ", "", info.get("device").get("name"))

            identifier: str = info.get("id", "")
            assert identifier is not None

            # Store device info for later use in additional configuration
            self._device_info = {
                "identifier": identifier,
                "name": name,
                "token": tv.token,
                "address": ip,
                "mac_address": info.get("device").get("wifiMac"),
                "reports_power_state": reports_power_state,
            }

            # Return config - framework will call get_additional_configuration_screen if defined
            return SamsungConfig(
                identifier=identifier,
                name=name,
                token=tv.token,  # type: ignore
                address=ip,
                mac_address=info.get("device").get(  # type: ignore
                    "wifiMac"
                ),  # Both wired and wireless use the same key
                reports_power_state=reports_power_state,
            )

        except Exception as err:  # pylint: disable=broad-except
            _LOG.error("Setup error for Samsung TV at %s: %s", ip, err)
            return SetupError(IntegrationSetupError.OTHER)

    async def _get_oauth_auth_screen(self) -> RequestUserInput | SetupError:
        """Generate OAuth authorization screen using worker."""
        try:
            # Get authorization URL from worker
            # Use certifi CA bundle for SSL verification
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(SMARTTHINGS_WORKER_AUTHORIZE) as response:
                    if response.status != 200:
                        _LOG.error(
                            "Failed to get auth URL from worker: %d", response.status
                        )
                        return SetupError(IntegrationSetupError.OTHER)

                    data = await response.json()
                    auth_url = data.get("authorizationUrl")

                    if not auth_url:
                        _LOG.error("No authorization URL in worker response")
                        return SetupError(IntegrationSetupError.OTHER)

                    return RequestUserInput(
                        {"en": "SmartThings OAuth Authorization"},
                        [
                            {
                                "id": "oauth_info",
                                "label": {"en": "Authorize SmartThings"},
                                "field": {
                                    "label": {
                                        "value": {
                                            "en": (
                                                f"Click the [authorization link]({auth_url}) to authorize access to your SmartThings account.\n\n"
                                                "After authorizing, you'll see a page with your tokens. "
                                                "Click 'Copy All as JSON' and paste the entire JSON response below."
                                            )
                                        }
                                    }
                                },
                            },
                            {
                                "field": {"textarea": {"value": ""}},
                                "id": "tokens_json",
                                "label": {"en": "Tokens (JSON)"},
                            },
                        ],
                    )
        except Exception as err:
            _LOG.error("Error getting OAuth authorization URL: %s", err, exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)
