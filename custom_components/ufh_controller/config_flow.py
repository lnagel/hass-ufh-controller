"""Config flow for UFH Controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from slugify import slugify

from .const import (
    DEFAULT_PID,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    LOGGER,
)

CONF_NAME = "name"
CONF_CONTROLLER_ID = "controller_id"
CONF_HEAT_REQUEST_ENTITY = "heat_request_entity"
CONF_DHW_ACTIVE_ENTITY = "dhw_active_entity"
CONF_CIRCULATION_ENTITY = "circulation_entity"
CONF_SUMMER_MODE_ENTITY = "summer_mode_entity"


class UFHControllerFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for UFH Controller."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Generate controller_id from name if not provided
            controller_id = user_input.get(CONF_CONTROLLER_ID) or slugify(
                user_input[CONF_NAME]
            )

            # Check for duplicate controller_id
            await self.async_set_unique_id(controller_id)
            self._abort_if_unique_id_configured()

            LOGGER.debug("Creating UFH Controller entry: %s", controller_id)

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_CONTROLLER_ID: controller_id,
                    CONF_HEAT_REQUEST_ENTITY: user_input.get(CONF_HEAT_REQUEST_ENTITY),
                    CONF_DHW_ACTIVE_ENTITY: user_input.get(CONF_DHW_ACTIVE_ENTITY),
                    CONF_CIRCULATION_ENTITY: user_input.get(CONF_CIRCULATION_ENTITY),
                    CONF_SUMMER_MODE_ENTITY: user_input.get(CONF_SUMMER_MODE_ENTITY),
                },
                options={
                    "timing": DEFAULT_TIMING.copy(),
                    "zones": [],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_HEAT_REQUEST_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                    vol.Optional(CONF_DHW_ACTIVE_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                    vol.Optional(CONF_CIRCULATION_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                    vol.Optional(CONF_SUMMER_MODE_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="select")
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> UFHControllerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return UFHControllerOptionsFlowHandler()


class UFHControllerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for UFH Controller."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._zone_to_edit: str | None = None

    async def async_step_init(
        self,
        _user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_zone", "manage_zones", "timing"],
        )

    async def async_step_add_zone(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Add a new zone."""
        errors: dict[str, str] = {}

        if user_input is not None:
            zone_id = user_input.get("zone_id") or slugify(user_input["name"])

            # Check for duplicate zone_id
            zones = list(self.config_entry.options.get("zones", []))
            if any(z["id"] == zone_id for z in zones):
                errors["zone_id"] = "zone_id_exists"
            else:
                new_zone = {
                    "id": zone_id,
                    "name": user_input["name"],
                    "circuit_type": user_input.get("circuit_type", "regular"),
                    "temp_sensor": user_input["temp_sensor"],
                    "valve_switch": user_input["valve_switch"],
                    "window_sensors": user_input.get("window_sensors", []),
                    "setpoint": {
                        "min": user_input.get("setpoint_min", DEFAULT_SETPOINT["min"]),
                        "max": user_input.get("setpoint_max", DEFAULT_SETPOINT["max"]),
                        "step": user_input.get(
                            "setpoint_step", DEFAULT_SETPOINT["step"]
                        ),
                        "default": user_input.get(
                            "setpoint_default", DEFAULT_SETPOINT["default"]
                        ),
                    },
                    "pid": {
                        "kp": user_input.get("kp", DEFAULT_PID["kp"]),
                        "ki": user_input.get("ki", DEFAULT_PID["ki"]),
                        "kd": user_input.get("kd", DEFAULT_PID["kd"]),
                        "integral_min": DEFAULT_PID["integral_min"],
                        "integral_max": DEFAULT_PID["integral_max"],
                    },
                    "presets": {},
                }
                zones.append(new_zone)

                return self.async_create_entry(
                    title="",
                    data={
                        **self.config_entry.options,
                        "zones": zones,
                    },
                )

        return self.async_show_form(
            step_id="add_zone",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(),
                    vol.Required("temp_sensor"): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required("valve_switch"): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                    vol.Optional(
                        "circuit_type", default="regular"
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value="regular", label="Regular"
                                ),
                                selector.SelectOptionDict(value="flush", label="Flush"),
                            ]
                        )
                    ),
                    vol.Optional("window_sensors"): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="binary_sensor", multiple=True
                        )
                    ),
                    vol.Optional(
                        "setpoint_min", default=DEFAULT_SETPOINT["min"]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=30,
                            step=0.1,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "setpoint_max", default=DEFAULT_SETPOINT["max"]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=35,
                            step=0.1,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "setpoint_default", default=DEFAULT_SETPOINT["default"]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=35,
                            step=0.1,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "kp", default=DEFAULT_PID["kp"]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "ki", default=DEFAULT_PID["ki"]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "kd", default=DEFAULT_PID["kd"]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_manage_zones(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage existing zones."""
        zones = self.config_entry.options.get("zones", [])

        if not zones:
            return self.async_abort(reason="no_zones")

        if user_input is not None:
            selected_zone = user_input.get("zone")
            action = user_input.get("action")

            if action == "delete":
                zones = [z for z in zones if z["id"] != selected_zone]
                return self.async_create_entry(
                    title="",
                    data={
                        **self.config_entry.options,
                        "zones": zones,
                    },
                )
            if action == "edit":
                self._zone_to_edit = selected_zone
                return await self.async_step_edit_zone()

        zone_options = [
            selector.SelectOptionDict(value=z["id"], label=z["name"]) for z in zones
        ]

        return self.async_show_form(
            step_id="manage_zones",
            data_schema=vol.Schema(
                {
                    vol.Required("zone"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=zone_options)
                    ),
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value="edit", label="Edit"),
                                selector.SelectOptionDict(
                                    value="delete", label="Delete"
                                ),
                            ]
                        )
                    ),
                }
            ),
        )

    async def async_step_edit_zone(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit an existing zone."""
        zones = list(self.config_entry.options.get("zones", []))
        zone = next((z for z in zones if z["id"] == self._zone_to_edit), None)

        if zone is None:
            return self.async_abort(reason="zone_not_found")

        if user_input is not None:
            # Update zone with new values
            zone["name"] = user_input["name"]
            zone["temp_sensor"] = user_input["temp_sensor"]
            zone["valve_switch"] = user_input["valve_switch"]
            zone["circuit_type"] = user_input.get("circuit_type", "regular")
            zone["window_sensors"] = user_input.get("window_sensors", [])
            zone["setpoint"] = {
                "min": user_input.get("setpoint_min", DEFAULT_SETPOINT["min"]),
                "max": user_input.get("setpoint_max", DEFAULT_SETPOINT["max"]),
                "step": zone.get("setpoint", {}).get("step", DEFAULT_SETPOINT["step"]),
                "default": user_input.get(
                    "setpoint_default", DEFAULT_SETPOINT["default"]
                ),
            }
            zone["pid"] = {
                "kp": user_input.get("kp", DEFAULT_PID["kp"]),
                "ki": user_input.get("ki", DEFAULT_PID["ki"]),
                "kd": user_input.get("kd", DEFAULT_PID["kd"]),
                "integral_min": DEFAULT_PID["integral_min"],
                "integral_max": DEFAULT_PID["integral_max"],
            }

            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    "zones": zones,
                },
            )

        # Prefill with existing values
        setpoint = zone.get("setpoint", DEFAULT_SETPOINT)
        pid = zone.get("pid", DEFAULT_PID)

        return self.async_show_form(
            step_id="edit_zone",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=zone["name"]): selector.TextSelector(),
                    vol.Required(
                        "temp_sensor", default=zone["temp_sensor"]
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required(
                        "valve_switch", default=zone["valve_switch"]
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                    vol.Optional(
                        "circuit_type", default=zone.get("circuit_type", "regular")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value="regular", label="Regular"
                                ),
                                selector.SelectOptionDict(value="flush", label="Flush"),
                            ]
                        )
                    ),
                    vol.Optional(
                        "window_sensors", default=zone.get("window_sensors", [])
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="binary_sensor", multiple=True
                        )
                    ),
                    vol.Optional(
                        "setpoint_min",
                        default=setpoint.get("min", DEFAULT_SETPOINT["min"]),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=30,
                            step=0.1,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "setpoint_max",
                        default=setpoint.get("max", DEFAULT_SETPOINT["max"]),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=35,
                            step=0.1,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "setpoint_default",
                        default=setpoint.get("default", DEFAULT_SETPOINT["default"]),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=35,
                            step=0.1,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "kp", default=pid.get("kp", DEFAULT_PID["kp"])
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "ki", default=pid.get("ki", DEFAULT_PID["ki"])
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "kd", default=pid.get("kd", DEFAULT_PID["kd"])
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    async def async_step_timing(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure timing parameters."""
        timing = self.config_entry.options.get("timing", DEFAULT_TIMING)

        if user_input is not None:
            new_timing = {
                "observation_period": int(user_input["observation_period"]),
                "duty_cycle_window": int(user_input["duty_cycle_window"]),
                "min_run_time": int(user_input["min_run_time"]),
                "valve_open_time": int(user_input["valve_open_time"]),
                "closing_warning_duration": int(user_input["closing_warning_duration"]),
                "window_block_threshold": user_input["window_block_threshold"],
            }
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    "timing": new_timing,
                },
            )

        return self.async_show_form(
            step_id="timing",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "observation_period",
                        default=timing.get(
                            "observation_period", DEFAULT_TIMING["observation_period"]
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1800, max=14400, step=600, unit_of_measurement="s"
                        )
                    ),
                    vol.Required(
                        "duty_cycle_window",
                        default=timing.get(
                            "duty_cycle_window", DEFAULT_TIMING["duty_cycle_window"]
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=600, max=7200, step=300, unit_of_measurement="s"
                        )
                    ),
                    vol.Required(
                        "min_run_time",
                        default=timing.get(
                            "min_run_time", DEFAULT_TIMING["min_run_time"]
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60, max=1800, step=60, unit_of_measurement="s"
                        )
                    ),
                    vol.Required(
                        "valve_open_time",
                        default=timing.get(
                            "valve_open_time", DEFAULT_TIMING["valve_open_time"]
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60, max=600, step=30, unit_of_measurement="s"
                        )
                    ),
                    vol.Required(
                        "closing_warning_duration",
                        default=timing.get(
                            "closing_warning_duration",
                            DEFAULT_TIMING["closing_warning_duration"],
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60, max=600, step=30, unit_of_measurement="s"
                        )
                    ),
                    vol.Required(
                        "window_block_threshold",
                        default=timing.get(
                            "window_block_threshold",
                            DEFAULT_TIMING["window_block_threshold"],
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1,
                            step=0.01,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
