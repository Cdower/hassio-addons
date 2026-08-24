"""Setpoint conversion for the AC Pro communicating control.

The control always stores its setpoint as a whole number of degrees Celsius in
``SetTem``.  When the installer has put the panel into Fahrenheit (``TemUn``
is 1) a companion column, ``TemRec``, carries the half-step that Celsius
cannot express, and the two together name a whole number of degrees
Fahrenheit.

Because 1 degC spans 1.8 degF, the (SetTem, TemRec) pairs tile the Fahrenheit
range with no gaps but with overlaps: some Fahrenheit values are reachable
from two different pairs.  Rather than derive an encoder independently -- and
risk it disagreeing with the decoder by a degree -- the encoder here is built
by inverting the decoder, so ``decode(*encode(f)) == f`` holds for every
value the control can represent.
"""

from __future__ import annotations

from functools import lru_cache

from .const import TEMP_MAX_C, TEMP_MIN_C


def celsius_to_fahrenheit(celsius: float) -> int:
    """Convert to whole degrees Fahrenheit the way the control's firmware does."""
    return round(celsius * 9 / 5 + 32)


def decode_fahrenheit(set_tem: int, tem_rec: int) -> int:
    """Return the Fahrenheit setpoint named by a ``SetTem``/``TemRec`` pair."""
    return celsius_to_fahrenheit(set_tem) - 1 + (1 if tem_rec else 0)


@lru_cache(maxsize=1)
def _encode_table() -> dict[int, tuple[int, int]]:
    """Map each reachable Fahrenheit setpoint back to a ``SetTem``/``TemRec`` pair.

    Built by walking the decoder over every representable pair.  Lower Celsius
    values are visited first and win ties, which keeps the mapping stable and
    keeps ``SetTem`` as close to the true conversion as the protocol allows.
    """
    table: dict[int, tuple[int, int]] = {}
    for set_tem in range(TEMP_MIN_C, TEMP_MAX_C + 1):
        for tem_rec in (0, 1):
            table.setdefault(decode_fahrenheit(set_tem, tem_rec), (set_tem, tem_rec))
    return table


def fahrenheit_range() -> tuple[int, int]:
    """Return the inclusive Fahrenheit setpoint range the control accepts."""
    table = _encode_table()
    return min(table), max(table)


def encode_fahrenheit(fahrenheit: float) -> tuple[int, int]:
    """Return the ``SetTem``/``TemRec`` pair for a Fahrenheit setpoint.

    Values outside the control's range are clamped to it rather than rejected,
    so a thermostat card that offers a wider slider cannot wedge the bridge.
    """
    low, high = fahrenheit_range()
    wanted = min(max(round(fahrenheit), low), high)
    return _encode_table()[wanted]


def clamp_celsius(celsius: float) -> int:
    """Clamp a Celsius setpoint to the range the control accepts."""
    return min(max(round(celsius), TEMP_MIN_C), TEMP_MAX_C)
