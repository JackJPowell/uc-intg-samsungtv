"""Discover Samsung TVs in local network using SDDP protocol."""

import logging
from typing import Any

from ucapi_framework import DiscoveredDevice
from ucapi_framework.discovery import SDDPDiscovery

_LOG = logging.getLogger(__name__)


class SamsungTVDiscovery(SDDPDiscovery):
    """Discover Samsung TVs in local network using SDDP protocol."""

    def parse_sddp_response(
        self, datagram: Any, response_info: Any
    ) -> DiscoveredDevice | None:
        """
        Parse SDDP response into DiscoveredDevice.

        :param datagram: SDDP datagram with headers (hdr_from, hdr_type, etc.)
        :param response_info: Full response info object from SDDP client
        :return: DiscoveredDevice or None if parsing fails
        """
        try:
            # Extract IP address from the datagram
            ip_address = datagram.hdr_from[0]

            # Extract device type (model/series information)
            device_type = (
                datagram.hdr_type if hasattr(datagram, "hdr_type") else "Samsung TV"
            )

            # Create identifier from IP address
            # We'll use IP-based identifier initially; MAC address can be obtained during connection
            identifier = f"samsung_{ip_address.replace('.', '_')}"

            # Use device type as the name
            device_name = device_type if device_type else "Samsung TV"

            _LOG.debug(
                "Parsed Samsung TV: %s at %s (type: %s)",
                device_name,
                ip_address,
                device_type,
            )

            return DiscoveredDevice(
                identifier=identifier,
                name=device_name,
                address=ip_address,
                extra_data={
                    "device_type": device_type,
                    "raw_datagram": str(datagram),
                },
            )

        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("Failed to parse SDDP device: %s", err)
            return None
