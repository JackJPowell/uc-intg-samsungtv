"""Discovery module for SDDP protocol."""

from typing import Optional, Iterable
import sddp_discovery_protocol as sddp
from sddp_discovery_protocol.constants import SDDP_MULTICAST_ADDRESS, SDDP_PORT
from sddp_discovery_protocol.client import DEFAULT_RESPONSE_WAIT_TIME


class SddpResponseInfo:
    """
    This class is used to store information about a response received from the SDDP protocol.
    It contains the datagram and the address of the sender.
    """

    def __init__(self):
        self.datagram = None
        self.address = None

    def __repr__(self):
        return f"SddpResponseInfo(datagram={self.datagram}, address={self.address})"


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
            async with client.search() as search_request:
                async for response_info in search_request.iter_responses():
                    self.datagram = response_info.datagram
                    self.address = response_info.src_addr
