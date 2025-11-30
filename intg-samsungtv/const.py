"""Samsung TV integration constants."""

from dataclasses import dataclass
from enum import Enum, IntEnum

from ucapi.media_player import States as MediaStates


@dataclass
class SamsungDevice:
    """Samsung device configuration."""

    identifier: str
    """Unique identifier of the device. (MAC Address)"""
    name: str
    """Friendly name of the device."""
    token: str
    """Token for connection to device."""
    address: str
    """IP Address of device"""
    mac_address: str | None = None
    """MAC Address of device"""
    reports_power_state: bool = False
    """True if the device reports power state via REST API (Frame TVs and some newer models)."""
    supports_art_mode: bool = False
    """True if the device supports art mode (Frame TVs only)."""


class SimpleCommands(str, Enum):
    """Additional simple commands of the Samsung TV not covered by media-player features."""

    CH_LIST = "Channel List"
    EXIT = "Exit"
    SLEEP = "Sleep"
    DEVICE_INFO = "Device Info"
    ART_INFO = "Art Info"
    ART_MODE_ON = "Art Mode On"
    ART_MODE_OFF = "Art Mode Off"
    STANDBY = "Standby"
    FORCE_POWER = "Force Power"


class States(IntEnum):
    """State of a connected Samsung TV."""

    UNKNOWN = 0
    UNAVAILABLE = 1
    OFF = 2
    ON = 3


SAMSUNG_STATE_MAPPING = {
    States.OFF: MediaStates.OFF,
    States.ON: MediaStates.ON,
    States.UNAVAILABLE: MediaStates.UNAVAILABLE,
    States.UNKNOWN: MediaStates.UNKNOWN,
}
