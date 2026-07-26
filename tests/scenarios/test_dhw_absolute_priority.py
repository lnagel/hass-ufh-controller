"""
End-to-end DHW cycles under absolute priority.

Walks a complete DHW charge from start to recovery expiry, verifying that
circuits close, stay closed through the hold-off and across a reload or
restart, that quota stops accruing once flow decays, and that latent heat
capture is deferred rather than cancelled.
"""

from datetime import UTC, datetime, timedelta

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ufh_controller.const import (
    DHWPriority,
    TimingConfig,
    ValveState,
)
from custom_components.ufh_controller.core.controller import (
    ControllerConfig,
    HeatingController,
)
from custom_components.ufh_controller.core.zone import (
    CircuitType,
    ZoneAction,
    ZoneConfig,
)
from tests.conftest import setup_zone_historical, setup_zone_pid

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
RECOVERY = 300
FLUSH_DURATION = 480
DHW_DURATION = 900


def build_controller() -> HeatingController:
    """Create an absolute-priority controller with a regular and flush circuit."""
    config = ControllerConfig(
        controller_id="heating",
        name="Heating Controller",
        dhw_active_entity="binary_sensor.boiler_dhw",
        dhw_priority=DHWPriority.ABSOLUTE,
        timing=TimingConfig(
            dhw_recovery_time=RECOVERY,
            flush_duration=FLUSH_DURATION,
        ),
        zones=[
            ZoneConfig(
                zone_id="living_room",
                name="Living Room",
                temp_sensor="sensor.living_room_temp",
                valve_switch="switch.living_room_valve",
            ),
            ZoneConfig(
                zone_id="bathroom",
                name="Bathroom",
                temp_sensor="sensor.bathroom_temp",
                valve_switch="switch.bathroom_valve",
                circuit_type=CircuitType.FLUSH,
            ),
        ],
    )
    return HeatingController(config, started_at=NOW)


def demand_zone(
    controller: HeatingController,
    zone_id: str,
    *,
    duty_cycle: float,
    valve_position: float,
) -> None:
    """Give a zone a PID duty cycle and matching valve/flow history."""
    setup_zone_pid(controller, zone_id, 20.0, duty_cycle)
    setup_zone_historical(
        controller, zone_id, valve_position=valve_position, window=False
    )
    runtime = controller.get_zone_runtime(zone_id)
    runtime.update_requested_duration(controller.config.timing.observation_period)
    runtime.state.valve_state = (
        ValveState.ON if valve_position >= 1.0 else ValveState.OFF
    )


async def test_full_dhw_cycle_closes_and_resumes() -> None:
    """A running zone is closed for DHW plus recovery, then resumes."""
    controller = build_controller()
    demand_zone(controller, "living_room", duty_cycle=60.0, valve_position=1.0)

    # Heating normally before DHW starts
    controller.update_dhw_state(dhw_active=False, now=NOW)
    actions = controller.evaluate(now=NOW)
    assert actions.valve_actions["living_room"] == ZoneAction.STAY_ON

    # DHW starts - the open circuit is commanded closed immediately
    dhw_start = NOW + timedelta(minutes=1)
    controller.update_dhw_state(dhw_active=True, now=dhw_start)
    actions = controller.evaluate(now=dhw_start)
    assert actions.valve_actions["living_room"] == ZoneAction.TURN_OFF
    assert actions.heat_request is False

    # Valve has closed; it stays closed for the rest of the charge
    controller.get_zone_runtime("living_room").state.valve_state = ValveState.OFF
    setup_zone_historical(controller, "living_room", valve_position=0.0, window=False)
    mid_dhw = dhw_start + timedelta(seconds=DHW_DURATION // 2)
    controller.update_dhw_state(dhw_active=True, now=mid_dhw)
    actions = controller.evaluate(now=mid_dhw)
    assert actions.valve_actions["living_room"] == ZoneAction.STAY_OFF

    # DHW ends but the hold-off keeps the circuit shut
    dhw_end = dhw_start + timedelta(seconds=DHW_DURATION)
    controller.update_dhw_state(dhw_active=False, now=dhw_end)
    actions = controller.evaluate(now=dhw_end)
    assert controller.state.dhw_block is True
    assert actions.valve_actions["living_room"] == ZoneAction.STAY_OFF

    still_hot = dhw_end + timedelta(seconds=RECOVERY - 30)
    controller.update_dhw_state(dhw_active=False, now=still_hot)
    actions = controller.evaluate(now=still_hot)
    assert actions.valve_actions["living_room"] == ZoneAction.STAY_OFF

    # Hold-off expires and normal scheduling resumes
    resumed = dhw_end + timedelta(seconds=RECOVERY + 30)
    controller.update_dhw_state(dhw_active=False, now=resumed)
    actions = controller.evaluate(now=resumed)
    assert controller.state.dhw_block is False
    assert actions.valve_actions["living_room"] == ZoneAction.TURN_ON


async def test_quota_stops_accruing_once_flow_decays() -> None:
    """
    A blocked zone is charged only for the heat it actually received.

    The previous version of this test set valve_position=0.0, so flow was
    already false and update_used_duration no-opped regardless of the block -
    it would have passed with the whole feature removed. This one starts from
    a zone that was genuinely running when DHW asserted.
    """
    controller = build_controller()
    demand_zone(controller, "living_room", duty_cycle=60.0, valve_position=1.0)
    runtime = controller.get_zone_runtime("living_room")
    remaining_before = runtime.state.remaining_duration
    assert remaining_before > 0
    assert runtime.state.flow is True

    controller.update_dhw_state(dhw_active=True, now=NOW)
    assert (
        controller.evaluate(now=NOW).valve_actions["living_room"] == ZoneAction.TURN_OFF
    )

    # Quota still accrues while the actuator is closing and flow reads true
    runtime.update_used_duration(30.0)
    charged_while_closing = runtime.state.used_duration
    assert charged_while_closing > 0

    # Once the estimated position falls below the flow threshold it stops
    setup_zone_historical(controller, "living_room", valve_position=0.0, window=False)
    for step in range(1, 6):
        moment = NOW + timedelta(seconds=60 * step)
        controller.update_dhw_state(dhw_active=True, now=moment)
        controller.evaluate(now=moment)
        runtime.update_used_duration(60.0)

    assert runtime.state.used_duration == charged_while_closing
    assert runtime.state.remaining_duration == remaining_before - charged_while_closing


async def test_latent_heat_capture_is_deferred_not_cancelled() -> None:
    """The flush window opens after the hold-off, at its full duration."""
    controller = build_controller()
    controller.state.flush_enabled = True

    # Both zones start with quota met, so nothing competes with the flush
    demand_zone(controller, "living_room", duty_cycle=0.0, valve_position=0.0)
    demand_zone(controller, "bathroom", duty_cycle=0.0, valve_position=0.0)

    controller.update_dhw_state(dhw_active=True, now=NOW)
    dhw_end = NOW + timedelta(seconds=DHW_DURATION)
    controller.update_dhw_state(dhw_active=False, now=dhw_end)

    # Still blocked - capturing now would push DHW-temperature water into a floor
    during_recovery = dhw_end + timedelta(seconds=RECOVERY - 30)
    controller.update_dhw_state(dhw_active=False, now=during_recovery)
    actions = controller.evaluate(now=during_recovery)
    assert actions.flush_request is False
    assert actions.valve_actions["bathroom"] == ZoneAction.STAY_OFF

    # Hold-off expired - the deferred flush window opens
    after_recovery = dhw_end + timedelta(seconds=RECOVERY + 30)
    controller.update_dhw_state(dhw_active=False, now=after_recovery)
    actions = controller.evaluate(now=after_recovery)
    assert actions.flush_request is True
    assert actions.valve_actions["bathroom"] == ZoneAction.TURN_ON

    # The full configured duration is available, not a truncated remainder
    near_end = dhw_end + timedelta(seconds=RECOVERY + FLUSH_DURATION - 30)
    controller.update_dhw_state(dhw_active=False, now=near_end)
    assert controller.evaluate(now=near_end).flush_request is True

    expired = dhw_end + timedelta(seconds=RECOVERY + FLUSH_DURATION + 30)
    controller.update_dhw_state(dhw_active=False, now=expired)
    assert controller.evaluate(now=expired).flush_request is False


async def test_hold_off_survives_config_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """An in-place config reload must not release circuits early."""
    hass.states.async_set("binary_sensor.dhw_active", STATE_ON)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator.controller.config.dhw_priority = DHWPriority.ABSOLUTE
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.controller.state.dhw_block is True

    # DHW ends - the recovery hold-off is armed
    hass.states.async_set("binary_sensor.dhw_active", STATE_OFF)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.controller.state.dhw_block is True
    armed_until = coordinator.controller.state.dhw_block_until
    assert armed_until is not None

    # A parameter change mid-recovery rebuilds the controller in place
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "dhw_priority": DHWPriority.ABSOLUTE.value},
    )
    await coordinator.async_reload_config()
    await hass.async_block_till_done()

    assert coordinator.controller.state.dhw_block is True
    assert coordinator.controller.state.dhw_block_until == armed_until


async def test_hold_off_survives_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_temp_sensor: None,
) -> None:
    """A restart mid-recovery restores the deadline from storage."""
    hass.states.async_set("binary_sensor.dhw_active", STATE_OFF)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    deadline = datetime.now(UTC) + timedelta(seconds=RECOVERY)
    stored = {
        "dhw_active": False,
        "dhw_block": True,
        "dhw_block_until": deadline.isoformat(),
    }

    coordinator.controller.config.dhw_priority = DHWPriority.ABSOLUTE
    coordinator._restore_controller_state(stored)

    assert coordinator.controller.state.dhw_block is True
    assert coordinator.controller.state.dhw_block_until == deadline

    # The restored deadline still governs the next recompute
    coordinator.controller.update_dhw_state(
        dhw_active=False, now=deadline - timedelta(seconds=1)
    )
    assert coordinator.controller.state.dhw_block is True
    coordinator.controller.update_dhw_state(
        dhw_active=False, now=deadline + timedelta(seconds=1)
    )
    assert coordinator.controller.state.dhw_block is False
