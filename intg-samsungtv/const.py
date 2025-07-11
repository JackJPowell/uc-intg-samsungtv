"""Samsung TV integration constants."""

from enum import Enum, IntEnum
from ucapi.media_player import States as MediaStates


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
