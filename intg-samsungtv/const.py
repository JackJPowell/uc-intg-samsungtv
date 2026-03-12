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
    smartthings_worker_url: str | None = None
    """Base URL of the assigned SmartThings OAuth worker (e.g. 'https://smartthings1.jackattack51.workers.dev')."""


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

# Coordinator worker — routes new users to a sub-worker with available capacity.
# Sub-workers (smartthings1, smartthings2, ...) each have a separate SmartThings
# app registration with its own 20-user limit. The coordinator picks the least-full
# one and returns its base URL so the client can store it for all future calls.
SMARTTHINGS_COORDINATOR_URL = "https://smartthings.jackattack51.workers.dev"
SMARTTHINGS_WORKER_AUTHORIZE = f"{SMARTTHINGS_COORDINATOR_URL}/authorize"

# Max users per sub-worker SmartThings app (Samsung-imposed limit for non-certified apps)
SMARTTHINGS_WORKER_CAPACITY = 20
