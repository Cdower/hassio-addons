"""Constants for the Sleeptracker integration."""

from __future__ import annotations

from datetime import timedelta
from enum import IntEnum

DOMAIN = "sleeptracker"
MANUFACTURER = "Tempur-Pedic"

CONF_BED_CONTROLS = "bed_controls"
CONF_STATUS_INTERVAL = "status_interval"
CONF_SLEEP_INTERVAL = "sleep_interval"

DEFAULT_STATUS_INTERVAL = 60  # seconds
DEFAULT_SLEEP_INTERVAL = 60  # minutes
MIN_STATUS_INTERVAL = 15
MIN_SLEEP_INTERVAL = 15

# Device info, room environment and snore-relief settings change slowly (the
# processor uploads environment readings about every 20 minutes), so they are
# refreshed on this cadence rather than on every status poll.
SLOW_REFRESH = timedelta(minutes=10)

# After a motor or preset command, poll status this often until the frame
# reports it has stopped, so position sensors follow the movement.
FOLLOW_UP_DELAY = 3  # seconds
FOLLOW_UP_POLLS = 10

SERVICE_SEND_COMMAND = "send_command"
ATTR_CONFIG_ENTRY = "config_entry_id"
ATTR_PROCESSOR_ID = "processor_id"
ATTR_COMMAND = "command"
ATTR_PAYLOAD = "payload"


class Command(IntEnum):
    """``bedControlCommand`` codes accepted by ``adjustableBaseControls``."""

    STATUS = 1

    PRESET_ZERO_G = 0
    PRESET_FLAT = 2
    PRESET_TV = 3
    PRESET_ANTI_SNORE = 4
    PRESET_FAVORITE = 6
    PRESET_SNORE_1 = 7
    PRESET_SNORE_2 = 8

    # Save the current position into a preset's memory slot.
    PROGRAM_TV = 300
    PROGRAM_ANTI_SNORE = 302
    PROGRAM_ZERO_G = 303
    PROGRAM_FAVORITE = 304

    HEAD_UP = 100
    HEAD_DOWN = 101
    FOOT_UP = 102
    FOOT_DOWN = 103
    LUMBAR_UP = 104
    LUMBAR_DOWN = 105
    LUMBAR_STOP = 106
    HEAD_STOP = 107
    FOOT_STOP = 108
    TILT_UP = 120
    TILT_DOWN = 121
    TILT_STOP = 122

    MASSAGE_HEAD_STEP = 210
    MASSAGE_FOOT_STEP = 211
    MASSAGE_STEP = 225
    MASSAGE_PATTERN_STEP = 226
    MASSAGE_TIMER_STEP = 231

    TOGGLE_SAFETY_LIGHT = 230


# Extra payload the app sends with the per-zone massage steps.
MASSAGE_STEP_PAYLOAD = {"massageAdjustment": 1, "requestStatus": True}

# Snapshot ``massagePattern`` values. 255 is reported while massage is off.
MASSAGE_PATTERNS = {0: "off", 1: "pulse", 2: "constant", 3: "ripple", 255: "off"}
