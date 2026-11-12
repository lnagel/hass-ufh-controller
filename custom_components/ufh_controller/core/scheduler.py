"""
Flow-rate-aware zone scheduling for Underfloor Heating Controller.

This module provides post-processing of zone actions to constrain aggregate
flow rate within configured bounds. It is called after per-zone evaluation
and before flush logic.
"""

from __future__ import annotations

from .zone import ZoneAction, ZoneRuntime


def _enforce_max_flow(
    result: dict[str, ZoneAction],
    zones: dict[str, ZoneRuntime],
    max_flow: float,
) -> None:
    """Demote TURN_ON candidates that would exceed max aggregate flow (in-place)."""
    # Committed flow from zones that are staying on
    committed_flow = 0.0
    for zone_id, action in result.items():
        if action == ZoneAction.STAY_ON:
            flow_rate = zones[zone_id].config.nominal_flow_rate
            if flow_rate is not None:
                committed_flow += flow_rate

    # Collect TURN_ON candidates that have a flow rate
    candidates: list[tuple[str, float, float]] = []
    for zone_id, action in result.items():
        if action != ZoneAction.TURN_ON:
            continue
        flow_rate = zones[zone_id].config.nominal_flow_rate
        if flow_rate is None:
            continue
        remaining_quota = (
            zones[zone_id].state.requested_duration - zones[zone_id].state.used_duration
        )
        candidates.append((zone_id, remaining_quota, flow_rate))

    if not candidates:
        return

    # Sort by remaining quota descending (front-load high-demand zones)
    candidates.sort(key=lambda c: c[1], reverse=True)

    for zone_id, _remaining_quota, flow_rate in candidates:
        if committed_flow + flow_rate <= max_flow:
            committed_flow += flow_rate
        elif committed_flow == 0.0:
            # No other zones running — never starve a single zone
            committed_flow += flow_rate
        else:
            result[zone_id] = ZoneAction.STAY_OFF


def apply_flow_constraint(
    desired_actions: dict[str, ZoneAction],
    zones: dict[str, ZoneRuntime],
    optimal_flow_rate_min: float | None,
    optimal_flow_rate_max: float | None,
) -> dict[str, ZoneAction]:
    """
    Constrain zone TURN_ON actions to keep aggregate flow within bounds.

    Max-flow: Zones already ON (STAY_ON) are committed and cannot be preempted.
    TURN_ON candidates are sorted by remaining quota descending (front-loading:
    zones needing the most time get priority). Zones without a nominal_flow_rate
    pass through unconstrained.

    If a single zone's flow exceeds remaining capacity and no other zones are
    running, it turns on anyway (never starve a zone).

    Min-flow: After max-flow admission, if total prospective flow (STAY_ON +
    admitted TURN_ON) is below the minimum, all TURN_ON are demoted to STAY_OFF.
    Opening valves when the boiler won't fire (insufficient flow) is wasteful.

    Args:
        desired_actions: Zone ID → ZoneAction from evaluate_zone().
        zones: Zone ID → ZoneRuntime for flow rate and state lookup.
        optimal_flow_rate_min: Lower bound on aggregate flow (L/min).
        optimal_flow_rate_max: Upper bound on aggregate flow (L/min).

    Returns:
        Updated actions dict with some TURN_ON demoted to STAY_OFF.

    """
    result = dict(desired_actions)

    if optimal_flow_rate_max is not None:
        _enforce_max_flow(result, zones, optimal_flow_rate_max)

    # Min-flow: if total prospective flow < min, don't open new zones.
    # Boiler won't fire with insufficient flow — opening valves is wasteful.
    if optimal_flow_rate_min is not None:
        total_flow = 0.0
        for zid, action in result.items():
            if action not in (ZoneAction.TURN_ON, ZoneAction.STAY_ON):
                continue
            flow = zones[zid].config.nominal_flow_rate
            if flow is not None:
                total_flow += flow
        if total_flow < optimal_flow_rate_min:
            result = {
                zid: (ZoneAction.STAY_OFF if a == ZoneAction.TURN_ON else a)
                for zid, a in result.items()
            }

    return result
