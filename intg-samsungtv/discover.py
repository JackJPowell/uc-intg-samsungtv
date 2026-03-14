"""
Discover Samsung TVs in local network using SDDP protocol and direct API probing.

:copyright: (c) 2023-2024 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0
"""

import asyncio
import ipaddress
import logging
import socket
from typing import Any

import requests
from ucapi_framework import DiscoveredDevice
from ucapi_framework.discovery import SDDPDiscovery

_LOG = logging.getLogger(__name__)


class SamsungTVDiscovery(SDDPDiscovery):
    """Discover Samsung TVs in local network using SDDP protocol."""

    async def discover(self) -> list[DiscoveredDevice]:
        """
        Perform Samsung TV discovery using both SDDP and direct API probing.

        :return: List of discovered devices
        """
        _LOG.info("Starting Samsung TV discovery")

        # Run the existing SDDP discovery path
        sddp_devices = await super().discover()

        # Run direct API probing against the primary LAN subnet
        direct_devices = await self._direct_api_discovery()

        # Merge and deduplicate, preferring direct API results where both exist
        devices = self._merge_devices(sddp_devices, direct_devices)

        _LOG.info(
            "Samsung TV discovery complete: %s SDDP + %s direct API -> %s unique TVs",
            len(sddp_devices),
            len(direct_devices),
            len(devices),
        )

        self._discovered_devices = devices
        return devices

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
                "Extracted Samsung discovery fields: ip=%s, name=%s, type=%s, identifier=%s, response_info=%s",
                ip_address,
                device_name,
                device_type,
                identifier,
                response_info,
            )

            return DiscoveredDevice(
                identifier=identifier,
                name=device_name,
                address=ip_address,
                extra_data={
                    "device_type": device_type,
                    "raw_datagram": str(datagram),
                    "response_info": str(response_info),
                    "discovery_method": "sddp",
                },
            )

        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "Failed to parse SDDP device: datagram=%s, response_info=%s, error=%s",
                datagram,
                response_info,
                err,
            )
            return None

    async def _direct_api_discovery(self) -> list[DiscoveredDevice]:
        """
        Probe the primary LAN subnet for Samsung TVs via http://IP:8001/api/v2/.

        :return: List of discovered devices
        """
        subnets = self._get_local_subnets()
        if not subnets:
            _LOG.warning("No local subnet detected for direct Samsung TV probing")
            return []

        timeout = 1
        max_concurrency = 64
        semaphore = asyncio.Semaphore(max_concurrency)
        loop = asyncio.get_running_loop()

        ips: list[str] = []
        for subnet in subnets:
            try:
                network = ipaddress.ip_network(subnet, strict=False)
                ips.extend(str(ip) for ip in network.hosts())
            except ValueError:
                _LOG.debug("Skipping invalid subnet: %s", subnet)

        if not ips:
            return []

        _LOG.info(
            "Starting direct Samsung TV probing on %s subnet(s), %s host(s)",
            len(subnets),
            len(ips),
        )

        async def probe_one(ip: str) -> DiscoveredDevice | None:
            async with semaphore:
                return await loop.run_in_executor(
                    None, self._probe_samsung_tv, ip, timeout
                )

        results = await asyncio.gather(*(probe_one(ip) for ip in ips))
        devices = [device for device in results if device is not None]

        _LOG.info("Direct API discovery found %s Samsung TV(s)", len(devices))
        return devices

    def _get_local_subnets(self) -> list[str]:
        """
        Determine the primary LAN subnet for discovery.

        :return: List of subnet strings
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                local_ip = sock.getsockname()[0]

            subnet = ipaddress.ip_network(f"{local_ip}/24", strict=False)

            _LOG.debug("Using primary LAN subnet for Samsung discovery: %s", subnet)

            return [str(subnet)]

        except OSError as err:
            _LOG.warning("Failed to determine primary LAN subnet: %s", err)
            return []

    def _probe_samsung_tv(
        self, ip: str, timeout: int = 1
    ) -> DiscoveredDevice | None:
        """
        Probe a single host via Samsung's direct API.

        :param ip: IP address to probe
        :param timeout: Request timeout in seconds
        :return: DiscoveredDevice or None if not a Samsung TV
        """
        url = f"http://{ip}:8001/api/v2/"

        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            payload = response.json()

            device = payload.get("device", {})
            tv_type = payload.get("type", "")
            friendly_name = (
                device.get("name")
                or payload.get("name")
                or device.get("modelName")
                or "Samsung TV"
            )

            samsung_text = " ".join(
                str(x)
                for x in [
                    tv_type,
                    payload.get("name"),
                    device.get("type"),
                    device.get("name"),
                    device.get("model"),
                    device.get("modelName"),
                    device.get("description"),
                ]
                if x is not None
            ).lower()

            if "samsung" not in samsung_text:
                return None

            identifier = device.get("id") or f"samsung_{ip.replace('.', '_')}"

            return DiscoveredDevice(
                identifier=identifier,
                name=friendly_name,
                address=ip,
                extra_data={
                    "device_type": tv_type,
                    "manufacturer": "Samsung",
                    "model": device.get("model"),
                    "model_name": device.get("modelName"),
                    "description": device.get("description"),
                    "os": device.get("OS"),
                    "power_state": device.get("PowerState"),
                    "token_auth_support": device.get("TokenAuthSupport"),
                    "voice_support": device.get("VoiceSupport"),
                    "network_type": device.get("networkType"),
                    "developer_ip": device.get("developerIP"),
                    "country_code": device.get("countryCode"),
                    "resolution": device.get("resolution"),
                    "remote_version": payload.get("remote"),
                    "api_version": payload.get("version"),
                    "uri": payload.get("uri"),
                    "wifi_mac": device.get("wifiMac"),
                    "duid": device.get("duid"),
                    "discovery_method": "direct_api",
                    "raw_api_response": payload,
                },
            )

        except Exception:
            return None

    def _merge_devices(
        self,
        sddp_devices: list[DiscoveredDevice],
        direct_devices: list[DiscoveredDevice],
    ) -> list[DiscoveredDevice]:
        """
        Merge discovery results by IP, preferring direct API data where available.

        :param sddp_devices: Devices discovered via SDDP
        :param direct_devices: Devices discovered via direct API
        :return: Merged and deduplicated device list
        """
        merged: dict[str, DiscoveredDevice] = {}

        for device in sddp_devices + direct_devices:
            key = device.address or device.identifier

            if key not in merged:
                merged[key] = device
                continue

            existing_method = merged[key].extra_data.get("discovery_method")
            new_method = device.extra_data.get("discovery_method")

            if existing_method != "direct_api" and new_method == "direct_api":
                merged[key] = device

        return sorted(merged.values(), key=lambda d: d.address or "")