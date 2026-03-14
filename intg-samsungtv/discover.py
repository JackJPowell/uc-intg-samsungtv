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
            _LOG.debug("Received SDDP response: datagram=%s", datagram)

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
                "Extracted Samsung discovery fields: ip=%s, type=%s, identifier=%s, response_info=%s",
                ip_address,
                device_type,
                identifier,
                response_info,
            )

            discovered_device = DiscoveredDevice(
                identifier=identifier,
                name=device_name,
                address=ip_address,
                extra_data={
                    "device_type": device_type,
                    "raw_datagram": str(datagram),
                },
            )

            _LOG.debug(
                "Returning discovered Samsung TV: name=%s, address=%s, identifier=%s",
                discovered_device.name,
                discovered_device.address,
                discovered_device.identifier,
            )

            return discovered_device

        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception(
                "Failed to parse SDDP device: datagram=%s, response_info=%s, error=%s",
                datagram,
                response_info,
                err,
            )
            return None