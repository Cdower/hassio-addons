"""Property names and value maps used by the AC Pro communicating control.

The control reports and accepts state as a list of short property names (the
protocol calls them *columns*).  Not every column exists on every unit -- an
air handler has no louvres, for instance -- so the bridge probes for the ones
this control actually answers to and only exposes those.
"""

from __future__ import annotations

from typing import Final

# --- Core columns ----------------------------------------------------------

PROP_POWER: Final = "Pow"
PROP_MODE: Final = "Mod"
PROP_TARGET_TEMP: Final = "SetTem"
PROP_TEMP_UNIT: Final = "TemUn"
PROP_TEMP_HALF: Final = "TemRec"
PROP_FAN_SPEED: Final = "WdSpd"
PROP_CURRENT_TEMP: Final = "TemSen"

#: Columns the bridge needs before it can present a thermostat at all.
REQUIRED_PROPERTIES: Final = (PROP_POWER, PROP_MODE, PROP_TARGET_TEMP)

#: Everything the bridge knows how to ask for, in probe order.
CANDIDATE_PROPERTIES: Final = (
    PROP_POWER,
    PROP_MODE,
    PROP_TARGET_TEMP,
    PROP_TEMP_UNIT,
    PROP_TEMP_HALF,
    PROP_FAN_SPEED,
    PROP_CURRENT_TEMP,
    "StHt",          # auxiliary / electric heat stage
    "SvSt",          # energy saving
    "Quiet",         # quiet operation
    "Tur",           # turbo / boost
    "SwhSlp",        # sleep schedule
    "Lig",           # panel backlight
    "Health",        # ioniser
    "Blo",           # post-run blower ("X-Fan")
    "Air",           # fresh air damper
    "SwUpDn",        # vertical louvre
    "SwingLfRig",    # horizontal louvre
    "AntiDirectBlow",
    "HeatCoolType",
)

# --- Operating modes -------------------------------------------------------

MODE_AUTO: Final = 0
MODE_COOL: Final = 1
MODE_DRY: Final = 2
MODE_FAN: Final = 3
MODE_HEAT: Final = 4

#: Protocol mode -> Home Assistant ``hvac_mode``.  "off" is separate: the
#: control reports it through the power column, not the mode column.
HVAC_MODES: Final = {
    MODE_AUTO: "heat_cool",
    MODE_COOL: "cool",
    MODE_DRY: "dry",
    MODE_FAN: "fan_only",
    MODE_HEAT: "heat",
}
HVAC_MODES_REVERSE: Final = {value: key for key, value in HVAC_MODES.items()}

# --- Fan speeds ------------------------------------------------------------

#: Protocol fan speed -> Home Assistant ``fan_mode``.
FAN_MODES: Final = {
    0: "auto",
    1: "low",
    2: "medium_low",
    3: "medium",
    4: "medium_high",
    5: "high",
}
FAN_MODES_REVERSE: Final = {value: key for key, value in FAN_MODES.items()}

# --- Presets ---------------------------------------------------------------

PRESET_NONE: Final = "none"

#: Home Assistant preset -> the column that switches it on.  Presets are
#: mutually exclusive, so selecting one clears the others.
PRESET_PROPERTIES: Final = {
    "eco": "SvSt",
    "boost": "Tur",
    "comfort": "Quiet",
    "sleep": "SwhSlp",
}

# --- Switches --------------------------------------------------------------

#: Column -> (entity name, entity icon) for the optional toggles.  ``StHt``
#: drives the supplementary electric heat on an air handler; on some units the
#: same column is labelled "8 degree heating" in the manufacturer's app.
SWITCH_PROPERTIES: Final = {
    "StHt": ("Auxiliary heat", "mdi:heat-wave"),
    "Lig": ("Display", "mdi:television-ambient-light"),
    "Health": ("Ioniser", "mdi:air-filter"),
    "Blo": ("Blower purge", "mdi:fan-clock"),
    "Air": ("Fresh air", "mdi:air-conditioner"),
    "SwUpDn": ("Vertical louvre", "mdi:arrow-up-down"),
    "SwingLfRig": ("Horizontal louvre", "mdi:arrow-left-right"),
    "AntiDirectBlow": ("Anti direct blow", "mdi:weather-windy"),
}

#: The control reports temperatures biased by this amount.
TEMP_SENSOR_OFFSET: Final = 40

#: Range the protocol allows for the Celsius setpoint column.
TEMP_MIN_C: Final = 16
TEMP_MAX_C: Final = 30
