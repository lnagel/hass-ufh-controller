"""
Flow-rate-aware zone scheduling for Underfloor Heating Controller.

This module provides post-processing of zone actions to constrain aggregate
flow rate within configured bounds. It is called after per-zone evaluation
and before flush logic.
"""

from __future__ import annotations

from .zone import ZoneAction, ZoneRuntime


def apply_flow_constraint(
    desired_actions: dict[str, ZoneAction],
    zones: dict[str, ZoneRuntime],
    max_flow_rate: float | None,
) -> dict[str, ZoneAction]:
    """
    Constrain zone TURN_ON actions to keep aggregate flow within max_flow_rate.

    Zones already ON (STAY_ON) are committed and cannot be preempted. TURN_ON
    candidates are sorted by remaining quota descending (front-loading: zones
    needing the most time get priority). Zones without a nominal_flow_rate pass
    through unconstrained.

    If a single zone's flow exceeds remaining capacity and no other zones are
    running, it turns on anyway (never starve a zone).

    Args:
        desired_actions: Zone ID → ZoneAction from evaluate_zone().
        zones: Zone ID → ZoneRuntime for flow rate and state lookup.
        max_flow_rate: Upper bound on aggregate flow (L/min).

    Returns:
        Updated actions dict with some TURN_ON demoted to STAY_OFF.

    """
    # unbounded max flow rate returns desired actions
    if max_flow_rate is None:
        return desired_actions

    # Committed flow from zones that are staying on
    committed_flow = 0.0
    for zone_id, action in desired_actions.items():
        if action == ZoneAction.STAY_ON:
            flow_rate = zones[zone_id].config.nominal_flow_rate
            if flow_rate is not None:
                committed_flow += flow_rate

    # Collect TURN_ON candidates that have a flow rate
    candidates: list[tuple[str, float, float]] = []
    for zone_id, action in desired_actions.items():
        if action != ZoneAction.TURN_ON:
            continue
        flow_rate = zones[zone_id].config.nominal_flow_rate
        if flow_rate is None:
            # No flow rate configured — pass through unconstrained
            continue
        remaining_quota = (
            zones[zone_id].state.requested_duration - zones[zone_id].state.used_duration
        )
        candidates.append((zone_id, remaining_quota, flow_rate))

    if not candidates:
        return desired_actions

    # Sort by remaining quota descending (front-load high-demand zones)
    candidates.sort(key=lambda c: c[1], reverse=True)

    result = dict(desired_actions)
    for zone_id, _remaining_quota, flow_rate in candidates:
        if committed_flow + flow_rate <= max_flow_rate:
            # Fits within budget — allow TURN_ON
            committed_flow += flow_rate
        elif committed_flow == 0.0:
            # No other zones running — never starve a single zone
            committed_flow += flow_rate
        else:
            # Exceeds budget — demote to STAY_OFF
            result[zone_id] = ZoneAction.STAY_OFF

    return result
