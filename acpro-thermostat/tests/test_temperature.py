"""Tests for setpoint conversion."""

from __future__ import annotations

import pytest

from acpro_thermostat import temperature
from acpro_thermostat.const import TEMP_MAX_C, TEMP_MIN_C


def test_every_reachable_fahrenheit_setpoint_round_trips() -> None:
    """The encoder is the decoder's inverse, so no setpoint drifts by a degree."""
    low, high = temperature.fahrenheit_range()

    for wanted in range(low, high + 1):
        set_tem, tem_rec = temperature.encode_fahrenheit(wanted)

        assert temperature.decode_fahrenheit(set_tem, tem_rec) == wanted


def test_encoded_celsius_stays_within_the_protocol_range() -> None:
    low, high = temperature.fahrenheit_range()

    for wanted in range(low, high + 1):
        set_tem, tem_rec = temperature.encode_fahrenheit(wanted)

        assert TEMP_MIN_C <= set_tem <= TEMP_MAX_C
        assert tem_rec in (0, 1)


def test_fahrenheit_range_covers_a_normal_comfort_band() -> None:
    low, high = temperature.fahrenheit_range()

    assert low <= 62
    assert high >= 84


def test_setpoints_outside_the_range_are_clamped_not_rejected() -> None:
    low, high = temperature.fahrenheit_range()

    assert temperature.encode_fahrenheit(-40) == temperature.encode_fahrenheit(low)
    assert temperature.encode_fahrenheit(150) == temperature.encode_fahrenheit(high)


def test_fractional_fahrenheit_is_rounded() -> None:
    assert temperature.encode_fahrenheit(70.4) == temperature.encode_fahrenheit(70)
    assert temperature.encode_fahrenheit(70.6) == temperature.encode_fahrenheit(71)


def test_decode_is_monotonic_in_both_columns() -> None:
    previous = None
    for set_tem in range(TEMP_MIN_C, TEMP_MAX_C + 1):
        for tem_rec in (0, 1):
            value = temperature.decode_fahrenheit(set_tem, tem_rec)
            if previous is not None:
                assert value >= previous
            previous = value


@pytest.mark.parametrize(
    ("celsius", "expected"),
    [(0, 32), (20, 68), (30, 86), (16, 61)],
)
def test_celsius_to_fahrenheit(celsius: int, expected: int) -> None:
    assert temperature.celsius_to_fahrenheit(celsius) == expected


def test_celsius_setpoints_are_clamped_to_the_protocol_range() -> None:
    assert temperature.clamp_celsius(5) == TEMP_MIN_C
    assert temperature.clamp_celsius(99) == TEMP_MAX_C
    assert temperature.clamp_celsius(21.4) == 21
