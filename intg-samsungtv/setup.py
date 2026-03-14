"""
Setup flow for Samsung TV integration.

:copyright: (c) 2023-2024 by Jack Powell
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import html
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


_OAUTH_AUTH_SCHEMA = None  # Will be dynamically generated


class SamsungSetupFlow(BaseSetupFlow[SamsungConfig]):
    """Setup flow handler for Samsung TV integration."""

    def __init__(self, *args, **kwargs):
        """Initialize the setup flow."""
        super().__init__(*args, **kwargs)
        self._oauth_state: str | None = None
        self._device_info: dict[str, Any] | None = None
        self._smartthings_enabled: bool = False
        self._assigned_worker_url: str | None = None

    def get_manual_entry_form(self) -> RequestUserInput:
        """
        Get the manual entry form for Samsung TV setup.

        :return: RequestUserInput for manual entry
        """
        return RequestUserInput(
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

    async def get_additional_configuration_screen(
        self, device_config: SamsungConfig, previous_input: dict[str, Any]
    ) -> RequestUserInput | None:
        """
        Get additional configuration screen for SmartThings OAuth (optional).

        :param device_config: The device configuration from query_device
        :param previous_input: Input values from the previous screen
        :return: RequestUserInput for SmartThings OAuth or None to skip
        """
        _LOG.debug(
            "get_additional_configuration_screen called for device=%s with previous_input=%s smartthings_enabled=%s",
            getattr(device_config, "identifier", None),
            previous_input,
            self._smartthings_enabled,
        )

        # If SmartThings was already enabled, don't show this screen again
        if self._smartthings_enabled:
            _LOG.debug(
                "SmartThings already enabled; skipping additional configuration screen"
            )
            return None

        # If SmartThings was already requested via the discovery checkbox, skip
        # straight to the OAuth screen without asking again.
        enable_from_discovery = (
            str(previous_input.get("enable_smartthings", "false")).lower() == "true"
        )
        if enable_from_discovery:
            _LOG.debug(
                "SmartThings requested from discovery flow; going directly to OAuth screen"
            )
            self._smartthings_enabled = True
            result = await self._get_oauth_auth_screen()
            if isinstance(result, RequestUserInput):
                return result
            # OAuth screen failed — log and fall through to show checkbox instead
            _LOG.warning(
                "Failed to get OAuth screen from discovery path; showing checkbox fallback"
            )

        _LOG.debug("Showing optional SmartThings setup screen")
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
        _LOG.debug(
            "handle_additional_configuration_response called with input_values=%s",
            input_values,
        )

        # Check if we're handling OAuth token submission (second pass of the SmartThings flow)
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
                if self._assigned_worker_url:
                    self._pending_device_config.smartthings_worker_url = (
                        self._assigned_worker_url
                    )  # type: ignore

                _LOG.debug(
                    "Stored SmartThings OAuth tokens for device=%s using worker_url=%s expires_at=%s",
                    getattr(self._pending_device_config, "identifier", None),
                    self._assigned_worker_url,
                    expires_at,
                )

                return None  # Save and complete

            except json.JSONDecodeError as err:
                _LOG.error("Invalid JSON format: %s", err)
                return SetupError(IntegrationSetupError.OTHER)
            except Exception as err:  # pylint: disable=broad-except
                _LOG.error("Error storing OAuth tokens: %s", err, exc_info=True)
                return SetupError(IntegrationSetupError.OTHER)

        # Check if user wants to enable SmartThings.
        # The framework sends checkbox values as strings ("true"/"false"), not booleans.
        enable_smartthings_raw = input_values.get("enable_smartthings", "false")
        enable_smartthings = str(enable_smartthings_raw).lower() == "true"

        _LOG.debug(
            "SmartThings selection processed: raw=%s parsed=%s",
            enable_smartthings_raw,
            enable_smartthings,
        )

        if enable_smartthings:
            # Mark SmartThings as enabled so we don't show the checkbox again
            self._smartthings_enabled = True
            _LOG.debug("User enabled SmartThings; showing OAuth authorization screen")
            # Show OAuth authorization screen
            return await self._get_oauth_auth_screen()

        # User skipped SmartThings, complete setup
        _LOG.debug("User skipped SmartThings; completing setup without OAuth")
        return None

    def get_additional_discovery_fields(self) -> list[dict]:
        """Add SmartThings OAuth prompt to the discovery selection screen."""
        _LOG.debug("Providing additional discovery fields for SmartThings option")
        return [
            {
                "id": "smartthings_info",
                "label": {"en": "SmartThings OAuth (Optional)"},
                "field": {
                    "label": {
                        "value": {
                            "en": (
                                "Enable SmartThings for advanced features like input source control. "
                                "Check the box below to set up OAuth after selecting your TV."
                            )
                        }
                    }
                },
            },
            {
                "field": {"checkbox": {"value": False}},
                "id": "enable_smartthings",
                "label": {"en": "Authorize SmartThings"},
            },
        ]

    async def prepare_input_from_discovery(
        self, discovered: Any, additional_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Map a discovered Samsung TV to the input_values format expected by query_device."""
        _LOG.debug(
            "Preparing input from discovered device: name=%s, address=%s, identifier=%s, additional_input=%s",
            getattr(discovered, "name", None),
            getattr(discovered, "address", None),
            getattr(discovered, "identifier", None),
            additional_input,
        )
        return {
            "address": discovered.address,
            "enable_smartthings": additional_input.get("enable_smartthings", False),
        }

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

        _LOG.debug("query_device called with input_values=%s", input_values)

        try:
            reports_power_state = False
            if ip is None:
                _LOG.debug("No IP address provided; returning manual entry form")
                return self.get_manual_entry_form()

            _LOG.debug("Connecting to Samsung TV at %s", ip)

            tv = SamsungTVWS(
                ip,
                port=8002,
                timeout=30,
                name="Unfolded Circle",
            )

            info = tv.rest_device_info()
            tv.close()

            if info and info.get("device", None).get("PowerState", None) is not None:  # type: ignore[union-attr]
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
                    info.get("device").get("name"),  # type: ignore[union-attr]
                )
                return SetupError(IntegrationSetupError.OTHER)
            # HTML-decode the name to convert entities like &quot; to actual quotes
            raw_name = info.get("device").get("name")  # type: ignore[union-attr]
            decoded_name = html.unescape(raw_name)
            name = re.sub(r"^\[TV\] ", "", decoded_name)

            identifier: str = info.get("id", "")
            assert identifier is not None

            # Store device info for later use in additional configuration
            self._device_info = {
                "identifier": identifier,
                "name": name,
                "token": tv.token,
                "address": ip,
                "mac_address": info.get("device").get("wifiMac"),  # type: ignore[union-attr]
                "reports_power_state": reports_power_state,
            }

            _LOG.debug(
                "Stored Samsung device info for setup: %s",
                self._device_info,
            )

            # Return config - framework will call get_additional_configuration_screen if defined
            _LOG.debug(
                "Returning SamsungConfig for device: name=%s, identifier=%s, address=%s, mac=%s, reports_power_state=%s",
                name,
                identifier,
                ip,
                info.get("device").get("wifiMac"),  # type: ignore[union-attr]
                reports_power_state,
            )

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
            _LOG.error("Setup error for Samsung TV at %s: %s", ip, err, exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)

    async def _get_oauth_auth_screen(self) -> RequestUserInput | SetupError:
        """Generate OAuth authorization screen using coordinator worker."""
        try:
            _LOG.debug("Requesting SmartThings OAuth authorization URL")
            # Get authorization URL from coordinator worker.
            # The coordinator picks the least-full sub-worker and returns
            # its base URL so we can store it for all future token operations.
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
                    worker_url = data.get("workerUrl")

                    if not auth_url:
                        _LOG.error("No authorization URL in worker response")
                        return SetupError(IntegrationSetupError.OTHER)

                    # Store the assigned worker URL so handle_additional_configuration_response
                    # can persist it onto the device config alongside the tokens.
                    self._assigned_worker_url = worker_url
                    _LOG.debug("Assigned SmartThings worker: %s", worker_url)

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
