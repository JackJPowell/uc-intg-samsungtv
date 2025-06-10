"""Samsung TV integration constants."""

from enum import Enum, IntEnum
from ucapi.media_player import States as MediaStates


class SimpleCommands(str, Enum):
    """Additional simple commands of the Samsung TV not covered by media-player features."""

    CH_LIST = "CH_LIST"
    EXIT = "EXIT"
    SLEEP = "SLEEP"
    HDMI_1 = "HDMI_1"
    HDMI_2 = "HDMI_2"
    HDMI_3 = "HDMI_3"
    HDMI_4 = "HDMI_4"
    DEVICE_INFO = "DEVICE_INFO"


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
