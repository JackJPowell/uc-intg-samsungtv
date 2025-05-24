"""Discovery module for SDDP protocol."""

from dataclasses import dataclass
from typing import Iterable, Optional

import sddp_discovery_protocol as sddp
from sddp_discovery_protocol.client import DEFAULT_RESPONSE_WAIT_TIME
from sddp_discovery_protocol.constants import SDDP_MULTICAST_ADDRESS, SDDP_PORT


@dataclass
class SddpResponseInfo:
    """
    This class is used to store information about a response received from the SDDP protocol.
    It contains the datagram and the address of the sender.
    """

    def __init__(self, address=None, tv_type=None):
        self.address = address
        self.type = tv_type

    def __repr__(self):
        return f"SddpResponseInfo(type={self.type}, address={self.address})"


class SddpDiscovery:
    """
    This class is used to store information about a response received from the SDDP protocol.
    It contains the datagram and the address of the sender.
    """

    def __init__(self):
        self.datagrams: list = []
        self.discovered: list[SddpResponseInfo] = []

    async def get(
        self,
        search_pattern: str = "*",
        response_wait_time: float = DEFAULT_RESPONSE_WAIT_TIME,
        multicast_address: str = SDDP_MULTICAST_ADDRESS,
        multicast_port: int = SDDP_PORT,
        bind_addresses: Optional[Iterable[str]] = None,
        include_loopback: bool = False,
    ) -> None:
        """Get the datagram and address of the sender."""
        async with sddp.SddpClient(
            search_pattern=search_pattern,
            response_wait_time=response_wait_time,
            multicast_address=multicast_address,
            multicast_port=multicast_port,
            bind_addresses=bind_addresses,
            include_loopback=include_loopback,
        ) as client:
            async with client.search(
                search_pattern=search_pattern, response_wait_time=response_wait_time
            ) as search_request:
                async for response_info in search_request.iter_responses():
                    info = SddpResponseInfo(
                        response_info.datagram.hdr_from[0],
                        response_info.datagram.hdr_type,
                    )
                    self.datagrams.append(response_info.datagram)
                    self.discovered.append(info)
