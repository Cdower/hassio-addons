"""Setup, entity and action tests for the Sleeptracker integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sleeptracker.const import DOMAIN

from .conftest import EMAIL, PROCESSOR_ID, FakeApi


def eid(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Return the entity ID registered for a unique ID."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id, f"no {platform} entity with unique_id {unique_id}"
    return entity_id


def bed(hass: HomeAssistant, platform: str, key: str) -> str:
    """Return a bed entity's ID."""
    return eid(hass, platform, f"{PROCESSOR_ID}_{key}")


def sleep(hass: HomeAssistant, key: str) -> str:
    """Return a sleep sensor's entity ID."""
    return eid(hass, "sensor", f"{EMAIL}_sleep_{key}")


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED


async def test_entities_reflect_bed(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """The fixture bed produces the expected entities and states."""
    await setup(hass, config_entry)

    assert hass.states.get(bed(hass, "light", "safety_light")).state == "off"
    # 6841 pulses at 193 ticks per degree.
    head = hass.states.get(bed(hass, "sensor", "head_angle"))
    assert float(head.state) == 35.4
    assert hass.states.get(bed(hass, "cover", "motor_head")).state == "open"
    assert hass.states.get(bed(hass, "cover", "motor_foot")).state == "closed"
    assert hass.states.get(bed(hass, "cover", "motor_head")).attributes["angle"] == 35.4
    assert float(hass.states.get(bed(hass, "sensor", "temperature")).state) == 28.0
    assert float(hass.states.get(bed(hass, "sensor", "humidity")).state) == 37.8
    assert float(hass.states.get(bed(hass, "sensor", "co2")).state) == 557
    assert hass.states.get(bed(hass, "sensor", "massage_pattern")).state == "off"
    assert hass.states.get(bed(hass, "binary_sensor", "frame_connected")).state == "on"
    assert hass.states.get(bed(hass, "switch", "snore_relief_tilt")).state == "on"

    registry = er.async_get(hass)
    # The roster has head, foot and lumbar motors but no head tilt, and
    # head and foot massage.
    assert registry.async_get_entity_id("cover", DOMAIN, f"{PROCESSOR_ID}_motor_lumbar")
    assert not registry.async_get_entity_id("cover", DOMAIN, f"{PROCESSOR_ID}_motor_head_tilt")
    for key in (
        "preset_flat",
        "preset_zero_g",
        "preset_tv",
        "preset_anti_snore",
        "preset_favorite",
        "program_favorite",
        "massage_head_step",
        "massage_foot_step",
        "massage_step",
        "massage_pattern_step",
        "massage_timer_step",
    ):
        assert registry.async_get_entity_id("button", DOMAIN, f"{PROCESSOR_ID}_{key}"), key


async def test_sleep_sensors(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Sleep sensors show the latest night."""
    await setup(hass, config_entry)

    score = hass.states.get(sleep(hass, "sleep_score"))
    assert score.state == "80"
    assert score.attributes["nights_recorded"] == 3
    assert score.attributes["stages"][1]["stage"] == "light"
    assert hass.states.get(sleep(hass, "night")).state == "2026-11-07"
    assert float(hass.states.get(sleep(hass, "total_sleep")).state) == 7.0
    assert float(hass.states.get(sleep(hass, "hrv_rmssd")).state) == 31.2
    assert hass.states.get(sleep(hass, "wake_time")).state == "2026-11-07T17:30:00+00:00"


async def test_light_toggles_only_when_needed(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Turning the light on sends the toggle once and reads back the state."""
    await setup(hass, config_entry)
    light = bed(hass, "light", "safety_light")

    await hass.services.async_call("light", "turn_on", {"entity_id": light}, blocking=True)
    assert mock_api.commands == [(230, {})]
    assert hass.states.get(light).state == "on"

    await hass.services.async_call("light", "turn_on", {"entity_id": light}, blocking=True)
    assert mock_api.commands == [(230, {})]

    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    assert mock_api.commands == [(230, {}), (230, {})]
    assert hass.states.get(light).state == "off"


async def test_cover_and_buttons_send_commands(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Motors and buttons map to the documented command codes."""
    await setup(hass, config_entry)
    head = bed(hass, "cover", "motor_head")

    for service in ("open_cover", "close_cover", "stop_cover"):
        await hass.services.async_call("cover", service, {"entity_id": head}, blocking=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": bed(hass, "button", "preset_flat")}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": bed(hass, "button", "massage_head_step")}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_api.commands == [
        (100, {}),
        (101, {}),
        (107, {}),
        (2, {}),
        (210, {"massageAdjustment": 1, "requestStatus": True}),
    ]


async def test_snore_relief_switch(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Switching one response off keeps the other setting."""
    await setup(hass, config_entry)
    vibration = bed(hass, "switch", "snore_relief_vibration")

    await hass.services.async_call("switch", "turn_off", {"entity_id": vibration}, blocking=True)
    assert mock_api.snore_sets == [(True, False)]
    assert hass.states.get(vibration).state == "off"
    assert hass.states.get(bed(hass, "switch", "snore_relief_tilt")).state == "on"


async def test_send_command_service(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """The raw command service sends the code and returns the cloud's reply."""
    await setup(hass, config_entry)

    result = await hass.services.async_call(
        DOMAIN,
        "send_command",
        {"config_entry_id": config_entry.entry_id, "command": 7, "payload": {"x": 1}},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_api.commands == [(7, {"x": 1})]
    assert result["response"]["snapshots"][0]["side"] == 0


async def test_sleep_device_is_under_the_bed(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """The sleep device links to the bed device it belongs to."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    devices = {
        identifier: device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        for _, identifier in device.identifiers
    }
    bed_device = devices[str(PROCESSOR_ID)]
    sleep_device = devices[f"sleep_{EMAIL}"]
    assert sleep_device.via_device_id == bed_device.id
    assert bed_device.name == "Bedroom"
    # Named after the bed, so the account's email stays out of entity IDs.
    assert sleep_device.name == "Bedroom sleep"
    sleep_ids = [
        entity.entity_id
        for entity in er.async_entries_for_device(er.async_get(hass), sleep_device.id)
    ]
    assert "sensor.bedroom_sleep_sleep_score" in sleep_ids
    assert not [i for i in sleep_ids if "example" in i or "sleeper" in i]


async def test_statistics_keyed_by_bed_and_side(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Statistic IDs name the bed and the account's side, not the account."""
    with patch(
        "custom_components.sleeptracker.async_import_sleep_statistics", AsyncMock()
    ) as import_stats:
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    _, summaries, sleeper, name = import_stats.call_args.args
    assert len(summaries) == 3
    assert sleeper == f"bed{PROCESSOR_ID}_side1"
    assert name == "Bedroom sleep"


async def test_statistics_without_own_sensor(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """An account with no sleep sensor on the bed falls back to its entry ID."""
    sensor_map = await mock_api.async_get_sensor_map(PROCESSOR_ID)
    for sensor in sensor_map:
        sensor["self"] = False
    with (
        patch.object(mock_api, "async_get_sensor_map", AsyncMock(return_value=sensor_map)),
        patch(
            "custom_components.sleeptracker.async_import_sleep_statistics", AsyncMock()
        ) as import_stats,
    ):
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert import_stats.call_args.args[2] == f"account_{config_entry.entry_id}"


async def test_bed_controls_option_off(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """A second account on the same bed can load sleep data only."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={"bed_controls": False})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    registry = er.async_get(hass)
    assert not registry.async_get_entity_id("light", DOMAIN, f"{PROCESSOR_ID}_safety_light")
    assert hass.states.get(sleep(hass, "sleep_score")).state == "80"


async def test_unload(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """The entry unloads cleanly."""
    await setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redact(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Diagnostics keep the bed data but drop credentials and serials."""
    from custom_components.sleeptracker.diagnostics import async_get_config_entry_diagnostics

    await setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(diag)
    assert "hunter2" not in text
    assert EMAIL not in text
    assert "TESTSERIAL0001" not in text
    assert diag["sleep"]["nights"] == 3
    assert diag["beds"][str(PROCESSOR_ID)]["status"]["snapshots"][0]["safetyLightOn"] is False


async def test_split_base_ids_include_side(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """With two controllers, entities follow the account's side and carry it in their ID."""
    controller = next(i for i in mock_api.status["invariants"] if i["type"] == "controller")
    other = {**controller, "position": {"side": 1}}
    mock_api.status["invariants"].append(other)
    right = {**mock_api.status["snapshots"][0], "side": 1, "safetyLightOn": True}
    mock_api.status["snapshots"].append(right)

    await setup(hass, config_entry)

    # The fixture sensor map marks unit 1 as this account's side.
    light = bed(hass, "light", "side1_safety_light")
    assert hass.states.get(light).state == "on"
