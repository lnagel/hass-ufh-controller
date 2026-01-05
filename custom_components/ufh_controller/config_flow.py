"""Config flow for UFH Controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from slugify import slugify

from .const import DOMAIN, LOGGER

CONF_NAME = "name"
CONF_CONTROLLER_ID = "controller_id"
CONF_HEAT_REQUEST_ENTITY = "heat_request_entity"


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
                    CONF_HEAT_REQUEST_ENTITY: user_input[CONF_HEAT_REQUEST_ENTITY],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_HEAT_REQUEST_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                }
            ),
            errors=errors,
        )
