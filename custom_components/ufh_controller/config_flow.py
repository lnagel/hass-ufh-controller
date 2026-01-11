"""Config flow for Underfloor Heating Controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from slugify import slugify

from .const import (
    DEFAULT_PID,
    DEFAULT_PRESETS,
    DEFAULT_SETPOINT,
    DEFAULT_TIMING,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_CONTROLLER,
    SUBENTRY_TYPE_ZONE,
    UI_PRESET_TEMPERATURE,
    UI_SETPOINT_DEFAULT,
    UI_SETPOINT_MAX,
    UI_SETPOINT_MIN,
    UI_TIMING_CLOSING_WARNING,
    UI_TIMING_CONTROLLER_LOOP_INTERVAL,
    UI_TIMING_FLUSH_DURATION,
    UI_TIMING_MIN_RUN_TIME,
    UI_TIMING_OBSERVATION_PERIOD,
    UI_TIMING_VALVE_OPEN_TIME,
    UI_TIMING_WINDOW_BLOCK_TIME,
    TimingDefaults,
)

CONF_NAME = "name"
CONF_CONTROLLER_ID = "controller_id"
CONF_HEAT_REQUEST_ENTITY = "heat_request_entity"
CONF_DHW_ACTIVE_ENTITY = "dhw_active_entity"
CONF_CIRCULATION_ENTITY = "circulation_entity"
CONF_SUMMER_MODE_ENTITY = "summer_mode_entity"


def get_timing_schema(timing: TimingDefaults | None = None) -> vol.Schema:
    """Get the schema for timing configuration."""
    timing = timing or DEFAULT_TIMING
    return vol.Schema(
        {
            vol.Required(
                "observation_period",
                default=timing.get(
                    "observation_period", DEFAULT_TIMING["observation_period"]
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_TIMING_OBSERVATION_PERIOD["min"],
                    max=UI_TIMING_OBSERVATION_PERIOD["max"],
                    step=UI_TIMING_OBSERVATION_PERIOD["step"],
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                "min_run_time",
                default=timing.get("min_run_time", DEFAULT_TIMING["min_run_time"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_TIMING_MIN_RUN_TIME["min"],
                    max=UI_TIMING_MIN_RUN_TIME["max"],
                    step=UI_TIMING_MIN_RUN_TIME["step"],
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                "valve_open_time",
                default=timing.get(
                    "valve_open_time", DEFAULT_TIMING["valve_open_time"]
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_TIMING_VALVE_OPEN_TIME["min"],
                    max=UI_TIMING_VALVE_OPEN_TIME["max"],
                    step=UI_TIMING_VALVE_OPEN_TIME["step"],
                    unit_of_measurement="s",
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
                    min=UI_TIMING_CLOSING_WARNING["min"],
                    max=UI_TIMING_CLOSING_WARNING["max"],
                    step=UI_TIMING_CLOSING_WARNING["step"],
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                "window_block_time",
                default=timing.get(
                    "window_block_time",
                    DEFAULT_TIMING["window_block_time"],
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_TIMING_WINDOW_BLOCK_TIME["min"],
                    max=UI_TIMING_WINDOW_BLOCK_TIME["max"],
                    step=UI_TIMING_WINDOW_BLOCK_TIME["step"],
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                "controller_loop_interval",
                default=timing.get(
                    "controller_loop_interval",
                    DEFAULT_TIMING["controller_loop_interval"],
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_TIMING_CONTROLLER_LOOP_INTERVAL["min"],
                    max=UI_TIMING_CONTROLLER_LOOP_INTERVAL["max"],
                    step=UI_TIMING_CONTROLLER_LOOP_INTERVAL["step"],
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                "flush_duration",
                default=timing.get(
                    "flush_duration",
                    DEFAULT_TIMING["flush_duration"],
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_TIMING_FLUSH_DURATION["min"],
                    max=UI_TIMING_FLUSH_DURATION["max"],
                    step=UI_TIMING_FLUSH_DURATION["step"],
                    unit_of_measurement="s",
                )
            ),
        }
    )


def get_zone_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Get the schema for zone configuration."""
    defaults = defaults or {}
    setpoint = defaults.get("setpoint", DEFAULT_SETPOINT)
    pid = defaults.get("pid", DEFAULT_PID)

    return vol.Schema(
        {
            vol.Required(
                "name", default=defaults.get("name", "")
            ): selector.TextSelector(),
            vol.Required(
                "temp_sensor", default=defaults.get("temp_sensor", "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                "valve_switch", default=defaults.get("valve_switch", "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
            vol.Optional(
                "circuit_type", default=defaults.get("circuit_type", "regular")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="regular", label="Regular"),
                        selector.SelectOptionDict(value="flush", label="Flush"),
                    ]
                )
            ),
            vol.Optional(
                "window_sensors", default=defaults.get("window_sensors", [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(
                "setpoint_min",
                default=setpoint.get("min", DEFAULT_SETPOINT["min"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_SETPOINT_MIN["min"],
                    max=UI_SETPOINT_MIN["max"],
                    step=UI_SETPOINT_MIN["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "setpoint_max",
                default=setpoint.get("max", DEFAULT_SETPOINT["max"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_SETPOINT_MAX["min"],
                    max=UI_SETPOINT_MAX["max"],
                    step=UI_SETPOINT_MAX["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "setpoint_default",
                default=setpoint.get("default", DEFAULT_SETPOINT["default"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_SETPOINT_DEFAULT["min"],
                    max=UI_SETPOINT_DEFAULT["max"],
                    step=UI_SETPOINT_DEFAULT["step"],
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
                    min=0,
                    step="any",
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
    )


def get_zone_entities_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Get the schema for zone entities configuration."""
    defaults = defaults or {}

    return vol.Schema(
        {
            vol.Required(
                "name", default=defaults.get("name", "")
            ): selector.TextSelector(),
            vol.Required(
                "temp_sensor", default=defaults.get("temp_sensor", "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                "valve_switch", default=defaults.get("valve_switch", "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
            vol.Optional(
                "circuit_type", default=defaults.get("circuit_type", "regular")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="regular", label="Regular"),
                        selector.SelectOptionDict(value="flush", label="Flush"),
                    ]
                )
            ),
            vol.Optional(
                "window_sensors", default=defaults.get("window_sensors", [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
        }
    )


def get_zone_temperature_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Get the schema for zone temperature control configuration."""
    defaults = defaults or {}
    setpoint = defaults.get("setpoint", DEFAULT_SETPOINT)
    pid = defaults.get("pid", DEFAULT_PID)

    return vol.Schema(
        {
            vol.Optional(
                "setpoint_min",
                default=setpoint.get("min", DEFAULT_SETPOINT["min"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_SETPOINT_MIN["min"],
                    max=UI_SETPOINT_MIN["max"],
                    step=UI_SETPOINT_MIN["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "setpoint_max",
                default=setpoint.get("max", DEFAULT_SETPOINT["max"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_SETPOINT_MAX["min"],
                    max=UI_SETPOINT_MAX["max"],
                    step=UI_SETPOINT_MAX["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "setpoint_default",
                default=setpoint.get("default", DEFAULT_SETPOINT["default"]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_SETPOINT_DEFAULT["min"],
                    max=UI_SETPOINT_DEFAULT["max"],
                    step=UI_SETPOINT_DEFAULT["step"],
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
                    min=0,
                    step="any",
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
    )


def get_zone_presets_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Get the schema for zone presets configuration."""
    defaults = defaults or {}
    presets = defaults.get("presets", DEFAULT_PRESETS)

    return vol.Schema(
        {
            vol.Optional(
                "preset_home",
                description={
                    "suggested_value": presets.get("home", DEFAULT_PRESETS["home"])
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_PRESET_TEMPERATURE["min"],
                    max=UI_PRESET_TEMPERATURE["max"],
                    step=UI_PRESET_TEMPERATURE["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "preset_away",
                description={
                    "suggested_value": presets.get("away", DEFAULT_PRESETS["away"])
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_PRESET_TEMPERATURE["min"],
                    max=UI_PRESET_TEMPERATURE["max"],
                    step=UI_PRESET_TEMPERATURE["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "preset_eco",
                description={
                    "suggested_value": presets.get("eco", DEFAULT_PRESETS["eco"])
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_PRESET_TEMPERATURE["min"],
                    max=UI_PRESET_TEMPERATURE["max"],
                    step=UI_PRESET_TEMPERATURE["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "preset_comfort",
                description={
                    "suggested_value": presets.get(
                        "comfort", DEFAULT_PRESETS["comfort"]
                    )
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_PRESET_TEMPERATURE["min"],
                    max=UI_PRESET_TEMPERATURE["max"],
                    step=UI_PRESET_TEMPERATURE["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                "preset_boost",
                description={
                    "suggested_value": presets.get("boost", DEFAULT_PRESETS["boost"])
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UI_PRESET_TEMPERATURE["min"],
                    max=UI_PRESET_TEMPERATURE["max"],
                    step=UI_PRESET_TEMPERATURE["step"],
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


def build_presets_from_input(user_input: dict[str, Any]) -> dict[str, float]:
    """Build presets dict from user input, filtering out empty values."""
    presets: dict[str, float] = {}
    for preset_name in ("home", "away", "eco", "comfort", "boost"):
        key = f"preset_{preset_name}"
        if key in user_input and user_input[key] is not None:
            presets[preset_name] = user_input[key]
    return presets


def build_zone_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Build zone data from user input."""
    zone_id = user_input.get("zone_id") or slugify(user_input["name"])
    return {
        "id": zone_id,
        "name": user_input["name"],
        "circuit_type": user_input.get("circuit_type", "regular"),
        "temp_sensor": user_input["temp_sensor"],
        "valve_switch": user_input["valve_switch"],
        "window_sensors": user_input.get("window_sensors", []),
        "setpoint": {
            "min": user_input.get("setpoint_min", DEFAULT_SETPOINT["min"]),
            "max": user_input.get("setpoint_max", DEFAULT_SETPOINT["max"]),
            "step": user_input.get("setpoint_step", DEFAULT_SETPOINT["step"]),
            "default": user_input.get("setpoint_default", DEFAULT_SETPOINT["default"]),
        },
        "pid": {
            "kp": user_input.get("kp", DEFAULT_PID["kp"]),
            "ki": user_input.get("ki", DEFAULT_PID["ki"]),
            "kd": user_input.get("kd", DEFAULT_PID["kd"]),
            "integral_min": DEFAULT_PID["integral_min"],
            "integral_max": DEFAULT_PID["integral_max"],
        },
        "presets": dict(DEFAULT_PRESETS),
    }


class UFHControllerFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Underfloor Heating Controller."""

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

            LOGGER.debug(
                "Creating Underfloor Heating Controller entry: %s", controller_id
            )

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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {SUBENTRY_TYPE_ZONE: ZoneSubentryFlowHandler}


class UFHControllerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Underfloor Heating Controller."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> config_entries.ConfigFlowResult:
        """Show menu with configuration options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["control_entities", "timing"],
        )

    async def async_step_control_entities(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure control entities (heat request, summer mode, etc.)."""
        if user_input is not None:
            # Update the config entry data with new control entities
            new_data = {
                **self.config_entry.data,
                CONF_HEAT_REQUEST_ENTITY: user_input.get(CONF_HEAT_REQUEST_ENTITY),
                CONF_DHW_ACTIVE_ENTITY: user_input.get(CONF_DHW_ACTIVE_ENTITY),
                CONF_CIRCULATION_ENTITY: user_input.get(CONF_CIRCULATION_ENTITY),
                CONF_SUMMER_MODE_ENTITY: user_input.get(CONF_SUMMER_MODE_ENTITY),
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )
            return self.async_create_entry(title="", data={})

        # Get current values from config entry data
        current_data = self.config_entry.data

        return self.async_show_form(
            step_id="control_entities",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HEAT_REQUEST_ENTITY,
                        description={
                            "suggested_value": current_data.get(
                                CONF_HEAT_REQUEST_ENTITY
                            )
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                    vol.Optional(
                        CONF_DHW_ACTIVE_ENTITY,
                        description={
                            "suggested_value": current_data.get(CONF_DHW_ACTIVE_ENTITY)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                    vol.Optional(
                        CONF_CIRCULATION_ENTITY,
                        description={
                            "suggested_value": current_data.get(CONF_CIRCULATION_ENTITY)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                    vol.Optional(
                        CONF_SUMMER_MODE_ENTITY,
                        description={
                            "suggested_value": current_data.get(CONF_SUMMER_MODE_ENTITY)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="select")
                    ),
                }
            ),
        )

    async def async_step_timing(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure timing parameters."""
        # Get timing from controller subentry if it exists
        timing: TimingDefaults = DEFAULT_TIMING.copy()
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
                stored = subentry.data.get("timing")
                if stored is not None:
                    timing = stored  # type: ignore[assignment]
                break

        if user_input is not None:
            new_timing = {
                "observation_period": int(user_input["observation_period"]),
                "min_run_time": int(user_input["min_run_time"]),
                "valve_open_time": int(user_input["valve_open_time"]),
                "closing_warning_duration": int(user_input["closing_warning_duration"]),
                "window_block_time": int(user_input["window_block_time"]),
                "controller_loop_interval": int(user_input["controller_loop_interval"]),
                "flush_duration": int(user_input["flush_duration"]),
            }

            # Update the controller subentry with new timing
            for subentry in self.config_entry.subentries.values():
                if subentry.subentry_type == SUBENTRY_TYPE_CONTROLLER:
                    self.hass.config_entries.async_update_subentry(
                        self.config_entry,
                        subentry,
                        data={"timing": new_timing},
                    )
                    break

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="timing",
            data_schema=get_timing_schema(timing),
        )


class ZoneSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding and modifying zones."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle adding a new zone."""
        errors: dict[str, str] = {}

        if user_input is not None:
            zone_id = user_input.get("zone_id") or slugify(user_input["name"])

            # Check for duplicate zone_id
            config_entry = self._get_entry()
            for subentry in config_entry.subentries.values():
                if subentry.data.get("id") == zone_id:
                    errors["base"] = "zone_id_exists"
                    break

            if not errors:
                zone_data = build_zone_data(user_input)
                LOGGER.debug("Creating zone subentry: %s", zone_id)
                return self.async_create_entry(
                    title=user_input["name"],
                    data=zone_data,
                    unique_id=zone_id,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=get_zone_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SubentryFlowResult:
        """Show menu with configuration options for existing zone."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options={
                "zone_entities": "Zone Entities",
                "temperature_control": "Temperature Control",
                "presets": "Presets",
            },
        )

    async def async_step_zone_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure zone entities (sensors, switches, circuit type)."""
        subentry = self._get_reconfigure_subentry()
        current_data = dict(subentry.data)

        if user_input is not None:
            # Update only the entities-related fields
            new_data = {
                **current_data,
                "name": user_input["name"],
                "temp_sensor": user_input["temp_sensor"],
                "valve_switch": user_input["valve_switch"],
                "circuit_type": user_input.get("circuit_type", "regular"),
                "window_sensors": user_input.get("window_sensors", []),
            }
            LOGGER.debug("Updating zone entities: %s", new_data["id"])
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input["name"],
                data=new_data,
            )

        return self.async_show_form(
            step_id="zone_entities",
            data_schema=get_zone_entities_schema(defaults=current_data),
        )

    async def async_step_temperature_control(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure temperature control (setpoint bounds, PID)."""
        subentry = self._get_reconfigure_subentry()
        current_data = dict(subentry.data)

        if user_input is not None:
            # Update only the temperature-related fields
            new_data = {
                **current_data,
                "setpoint": {
                    "min": user_input.get("setpoint_min", DEFAULT_SETPOINT["min"]),
                    "max": user_input.get("setpoint_max", DEFAULT_SETPOINT["max"]),
                    "step": current_data.get("setpoint", {}).get(
                        "step", DEFAULT_SETPOINT["step"]
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
            }
            LOGGER.debug("Updating zone temperature control: %s", new_data["id"])
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=new_data,
            )

        return self.async_show_form(
            step_id="temperature_control",
            data_schema=get_zone_temperature_schema(defaults=current_data),
        )

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure zone presets."""
        subentry = self._get_reconfigure_subentry()
        current_data = dict(subentry.data)

        if user_input is not None:
            # Build presets from input, filtering out empty values
            presets = build_presets_from_input(user_input)
            new_data = {
                **current_data,
                "presets": presets,
            }
            LOGGER.debug("Updating zone presets: %s", new_data["id"])
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=new_data,
            )

        return self.async_show_form(
            step_id="presets",
            data_schema=get_zone_presets_schema(defaults=current_data),
        )
