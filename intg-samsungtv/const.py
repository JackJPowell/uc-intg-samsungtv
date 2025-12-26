"""Samsung TV integration constants."""

from dataclasses import dataclass
from enum import Enum, IntEnum

from ucapi.media_player import States as MediaStates


@dataclass
class SamsungConfig:
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

    smartthings_access_token: str | None = None
    """OAuth Access Token for SmartThings Cloud API (optional - enables input source control)."""
    smartthings_refresh_token: str | None = None
    """OAuth Refresh Token for SmartThings Cloud API (optional - used to renew access token)."""
    smartthings_token_expires: int | None = None
    """Unix timestamp when the OAuth access token expires (optional)."""
    supports_power_on_by_ocf: bool = False
    """True if the TV supports network-based wake via SmartThings (no WOL needed)."""
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

"""SmartThings OAuth constants."""

# OAuth Configuration using Cloudflare Worker proxy
# Worker keeps client credentials server-side for security
SMARTTHINGS_WORKER_BASE_URL = "https://smartthings.jackattack51.workers.dev"
SMARTTHINGS_WORKER_AUTHORIZE = f"{SMARTTHINGS_WORKER_BASE_URL}/authorize"
SMARTTHINGS_WORKER_CALLBACK = f"{SMARTTHINGS_WORKER_BASE_URL}/oauth/callback"
SMARTTHINGS_WORKER_REFRESH = f"{SMARTTHINGS_WORKER_BASE_URL}/refresh"
