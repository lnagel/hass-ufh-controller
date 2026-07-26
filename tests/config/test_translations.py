"""
Tests that config flow fields and selectors resolve to translated strings.

A field whose key is missing from strings.json renders with a blank label in
the UI, which the schema tests cannot catch because the schema itself is valid.
"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.ufh_controller.config_flow import CONF_DHW_PRIORITY
from custom_components.ufh_controller.const import DEFAULT_TIMING, DHWPriority

PREFIX = "component.ufh_controller"

CONTROL_ENTITY_FIELDS = [
    "pump_request_entity",
    "heat_request_entity",
    "dhw_active_entity",
    CONF_DHW_PRIORITY,
    "summer_mode_entity",
]


@pytest.mark.parametrize("field", CONTROL_ENTITY_FIELDS)
async def test_initial_setup_fields_have_labels(
    hass: HomeAssistant, field: str
) -> None:
    """Every field in the initial setup step renders with a label."""
    tr = await async_get_translations(
        hass, "en", "config", integrations=["ufh_controller"]
    )
    assert tr.get(f"{PREFIX}.config.step.user.data.{field}")


@pytest.mark.parametrize("field", CONTROL_ENTITY_FIELDS)
async def test_control_entities_fields_have_labels(
    hass: HomeAssistant, field: str
) -> None:
    """Every field in the Control Entities options step renders with a label."""
    tr = await async_get_translations(
        hass, "en", "options", integrations=["ufh_controller"]
    )
    assert tr.get(f"{PREFIX}.options.step.control_entities.data.{field}")


@pytest.mark.parametrize("field", list(DEFAULT_TIMING))
async def test_timing_fields_have_labels(hass: HomeAssistant, field: str) -> None:
    """Every timing parameter renders with a label in both timing forms."""
    tr = await async_get_translations(
        hass, "en", "options", integrations=["ufh_controller"]
    )
    assert tr.get(f"{PREFIX}.options.step.timing.data.{field}")

    subentry = await async_get_translations(
        hass, "en", "config_subentries", integrations=["ufh_controller"]
    )
    assert subentry.get(
        f"{PREFIX}.config_subentries.controller.step.reconfigure.data.{field}"
    )


@pytest.mark.parametrize("priority", list(DHWPriority))
async def test_dhw_priority_options_have_labels(
    hass: HomeAssistant, priority: DHWPriority
) -> None:
    """Each DHW priority dropdown option resolves via its translation_key."""
    tr = await async_get_translations(
        hass, "en", "selector", integrations=["ufh_controller"]
    )
    assert tr.get(f"{PREFIX}.selector.{CONF_DHW_PRIORITY}.options.{priority.value}")
