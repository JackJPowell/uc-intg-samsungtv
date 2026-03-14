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

import aiohttp
from ucapi_framework import DiscoveredDevice
from ucapi_framework.discovery import SDDPDiscovery

_LOG = logging.getLogger(__name__)


class SamsungTVDiscovery(SDDPDiscovery):
    """Discover Samsung TVs in local network using SDDP protocol."""

    async def discover(self) -> list[DiscoveredDevice]:
        """
        Perform Samsung TV discovery using both SDDP and direct API probing.

        Runs both methods concurrently and merges the results, deduplicating by
        IP address. This catches TVs in mixed environments where multicast may
        be blocked or a TV doesn't respond to SDDP.

        :return: List of discovered devices
        """
        _LOG.info("Starting Samsung TV discovery")
        sddp_devices, direct_devices = await asyncio.gather(
            super().discover(),
            self._direct_api_discovery(),
        )

        devices = self._merge_devices(sddp_devices, direct_devices)
        _LOG.info(
            "Samsung TV discovery complete: %d SDDP + %d direct API = %d unique TV(s)",
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
            ip_address = datagram.hdr_from[0]
            device_type = (
                datagram.hdr_type if hasattr(datagram, "hdr_type") else "Samsung TV"
            )
            identifier = f"samsung_{ip_address.replace('.', '_')}"
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
                    "response_info": str(response_info),
                    "discovery_method": "sddp",
                },
            )

        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("Failed to parse SDDP device: %s", err)
            return None

    async def _direct_api_discovery(self) -> list[DiscoveredDevice]:
        """
        Probe the primary LAN subnet for Samsung TVs via http://IP:8001/api/v2/.

        Only scans subnets with a prefix length >= 24 (i.e. /24 or smaller) to
        avoid scanning thousands of hosts on large networks.

        :return: List of discovered devices
        """
        subnet = self._get_local_subnet()
        if subnet is None:
            _LOG.warning("No suitable local subnet found for direct Samsung TV probing")
            return []

        ips = [str(ip) for ip in subnet.hosts()]
        _LOG.info("Direct API scan: probing %d host(s) on %s", len(ips), subnet)

        max_concurrency = 64
        semaphore = asyncio.Semaphore(max_concurrency)
        connect_timeout = aiohttp.ClientTimeout(connect=0.5, total=1.5)

        async def probe_one(
            session: aiohttp.ClientSession, ip: str
        ) -> DiscoveredDevice | None:
            async with semaphore:
                return await self._probe_samsung_tv(session, ip, connect_timeout)

        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *(probe_one(session, ip) for ip in ips), return_exceptions=False
            )

        devices = [d for d in results if d is not None]
        _LOG.info("Direct API scan complete: %d Samsung TV(s) found", len(devices))
        return devices

    def _get_local_subnet(self) -> ipaddress.IPv4Network | None:
        """
        Determine the primary LAN subnet by assuming a /24 prefix.

        :return: IPv4Network or None if the local IP cannot be determined
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                local_ip = sock.getsockname()[0]
            network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            _LOG.debug("Using subnet %s for direct scan", network)
            return network
        except OSError as err:
            _LOG.warning("Failed to determine local subnet: %s", err)
            return None

    async def _probe_samsung_tv(
        self,
        session: aiohttp.ClientSession,
        ip: str,
        timeout: aiohttp.ClientTimeout,
    ) -> DiscoveredDevice | None:
        """
        Probe a single host via Samsung's REST API.

        First does a fast TCP connect check on port 8001 to avoid spending the
        full HTTP timeout on hosts that have nothing listening.

        :param session: Shared aiohttp session
        :param ip: IP address to probe
        :param timeout: aiohttp timeout configuration
        :return: DiscoveredDevice or None
        """
        # Fast pre-check: attempt TCP connect before issuing the HTTP request.
        # This eliminates the connect portion of the timeout for closed ports.
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 8001), timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError):
            return None

        url = f"http://{ip}:8001/api/v2/"
        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)

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
            _LOG.debug("Direct API found Samsung TV: %s at %s", friendly_name, ip)

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

        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None

    def _merge_devices(
        self,
        sddp_devices: list[DiscoveredDevice],
        direct_devices: list[DiscoveredDevice],
    ) -> list[DiscoveredDevice]:
        """
        Merge SDDP and direct API results, deduplicating by IP address.

        Where the same IP is found by both methods, the direct API result is
        preferred as it carries richer metadata.

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
            existing_method = (merged[key].extra_data or {}).get("discovery_method")
            new_method = (device.extra_data or {}).get("discovery_method")
            if existing_method != "direct_api" and new_method == "direct_api":
                merged[key] = device

        return sorted(merged.values(), key=lambda d: d.address or "")
