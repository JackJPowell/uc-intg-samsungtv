"""
Setup flow for Samsung TV integration.

:copyright: (c) 2023-2024 by Jack Powell
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import html
import json
import logging
import re
import ssl
import time
from typing import Any

import aiohttp
import certifi
from const import (
    SMARTTHINGS_COORDINATOR_URL,
    SMARTTHINGS_WORKER_AUTHORIZE,
    SamsungConfig,
)
from samsungtvws import SamsungTVWS
from ucapi import (
    IntegrationSetupError,
    RequestUserInput,
    SetupError,
)
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
                                    "Enable SmartThings for features like input source control and power management. "
                                ),
                            }
                        }
                    },
                },
                {
                    "field": {"checkbox": {"value": False}},
                    "id": "enable_smartthings",
                    "label": {
                        "en": "Enable SmartThings",
                    },
                },
            ],
        )

    async def get_additional_configuration_screen(
        self, device_config: SamsungConfig, previous_input: dict[str, Any]
    ) -> RequestUserInput | SetupError | None:
        """Honor the first screen's selection and reuse existing authorization."""
        if str(previous_input.get("enable_smartthings", False)).lower() != "true":
            return None

        # Reuse only current configuration; fresh setup and reset clear credentials.
        candidates = list(self.config.all())
        candidates.sort(
            key=lambda config: config.identifier != device_config.identifier
        )
        seen = set()
        uncertain = False
        for existing in candidates:
            credentials = (
                existing.smartthings_access_token,
                existing.smartthings_refresh_token,
                existing.smartthings_worker_url,
            )
            if credentials in seen or not any(credentials[:2]):
                continue
            seen.add(credentials)
            valid = await self._validate_smartthings_tokens(existing)
            if valid is None:
                uncertain = True
                continue
            if not valid:
                continue
            device_config.smartthings_access_token = existing.smartthings_access_token
            device_config.smartthings_refresh_token = existing.smartthings_refresh_token
            device_config.smartthings_token_expires = existing.smartthings_token_expires
            device_config.smartthings_worker_url = existing.smartthings_worker_url
            _LOG.info("Reusing SmartThings authorization from '%s'", existing.name)
            return None

        # A network/service failure does not prove that authorization was revoked.
        if uncertain:
            _LOG.warning(
                "Unable to verify saved SmartThings authorization; retry setup"
            )
            return SetupError(IntegrationSetupError.OTHER)
        return await self._get_oauth_auth_screen()

    async def _validate_smartthings_tokens(self, config: SamsungConfig) -> bool | None:
        """Validate access, refresh rejected tokens, or return None on service failure."""
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        try:
            async with aiohttp.ClientSession(
                connector=connector, timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                if config.smartthings_access_token:
                    async with session.get(
                        "https://api.smartthings.com/v1/devices",
                        headers={
                            "Authorization": f"Bearer {config.smartthings_access_token}"
                        },
                    ) as response:
                        if response.status == 200:
                            return True
                        if response.status not in (401, 403):
                            return None

                if not config.smartthings_refresh_token:
                    return False
                async with session.post(
                    f"{config.smartthings_worker_url or SMARTTHINGS_COORDINATOR_URL}/refresh",
                    json={"refresh_token": config.smartthings_refresh_token},
                ) as response:
                    if response.status != 200:
                        # Only invalid_grant establishes that new authorization is needed.
                        data = await response.json()
                        details = data.get("details", "")
                        if response.status in (400, 401, 403) and (
                            data.get("error") == "invalid_grant"
                            or "invalid_grant" in str(details)
                        ):
                            return False
                        return None
                    tokens = await response.json()
                    if not tokens.get("access_token"):
                        return None
                    expires_at = int(time.time()) + int(tokens.get("expires_in", 86400))
                    old_refresh_token = config.smartthings_refresh_token
                    config.smartthings_access_token = tokens["access_token"]
                    config.smartthings_refresh_token = (
                        tokens.get("refresh_token") or old_refresh_token
                    )
                    config.smartthings_token_expires = expires_at

                # Keep TVs sharing this grant in sync when the refresh token rotates.
                for existing in self.config.all():
                    if (
                        existing.smartthings_refresh_token == old_refresh_token
                        and existing.smartthings_worker_url
                        == config.smartthings_worker_url
                    ):
                        existing.smartthings_access_token = (
                            config.smartthings_access_token
                        )
                        existing.smartthings_refresh_token = (
                            config.smartthings_refresh_token
                        )
                        existing.smartthings_token_expires = expires_at
                for existing in self.config.all():
                    if (
                        existing.smartthings_refresh_token
                        == config.smartthings_refresh_token
                        and existing.smartthings_worker_url
                        == config.smartthings_worker_url
                    ):
                        self.config.update(existing)
                return True
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            _LOG.warning(
                "Could not validate or refresh saved SmartThings authorization"
            )
            return None

    async def handle_additional_configuration_response(
        self, msg: Any
    ) -> SamsungConfig | RequestUserInput | SetupError | None:
        """
        Handle response from additional configuration screen.

        :param msg: User data response from additional screen
        :return: Updated config, next screen, or None to complete
        """
        input_values = msg.input_values
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
                expires_at = int(time.time()) + int(tokens.get("expires_in", 86400))

                _LOG.info("Storing SmartThings OAuth tokens")

                # Persist SmartThings tokens on the current pending config as well.
                self._pending_device_config.smartthings_access_token = access_token  # type: ignore
                self._pending_device_config.smartthings_refresh_token = refresh_token  # type: ignore
                self._pending_device_config.smartthings_token_expires = expires_at  # type: ignore
                if self._assigned_worker_url:
                    self._pending_device_config.smartthings_worker_url = (
                        self._assigned_worker_url
                    )  # type: ignore[union-attr]

                return None  # Save and complete

            except json.JSONDecodeError as err:
                _LOG.error("Invalid JSON format: %s", err)
                return SetupError(IntegrationSetupError.OTHER)
            except Exception as err:  # pylint: disable=broad-except
                _LOG.error("Error storing OAuth tokens: %s", err, exc_info=True)
                return SetupError(IntegrationSetupError.OTHER)

        _LOG.error("Missing SmartThings OAuth token submission")
        return SetupError(IntegrationSetupError.OTHER)

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
                                "Check the box below to reuse saved authorization or set up OAuth after selecting your TV."
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

            # Create device config. The framework will call get_additional_configuration_screen
            # after this to handle SmartThings authorization if needed.
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
                                "label": {"en": "Enable SmartThings"},
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
