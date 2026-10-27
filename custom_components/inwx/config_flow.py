"""Config flow for the INWX integration."""

from collections.abc import Mapping
from typing import Any, override

import aiohttp
from aioinwx import (
    InwxAccount,
    InwxApiError,
    InwxAuthError,
    InwxClient,
    InwxConnectionError,
    InwxError,
    InwxInvalidSharedSecretError,
    InwxTwoFactorError,
    InwxTwoFactorRequiredError,
    normalize_shared_secret,
)
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import probatio

from .const import (
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_VAT,
    CONF_SHARED_SECRET,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_INCLUDE_VAT,
    DOMAIN,
    LOGGER,
    MAX_FORECAST_DAYS,
)
from .coordinator import InwxConfigEntry

USERNAME_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
)
PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
SHARED_SECRET_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="off")
)

STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): USERNAME_SELECTOR,
        probatio.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
        probatio.Optional(CONF_SHARED_SECRET): SHARED_SECRET_SELECTOR,
    }
)

STEP_REAUTH_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
        probatio.Optional(CONF_SHARED_SECRET): SHARED_SECRET_SELECTOR,
    }
)

OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_FORECAST_DAYS): probatio.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=MAX_FORECAST_DAYS,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="d",
                )
            ),
            probatio.Coerce(int),
        ),
        probatio.Required(CONF_INCLUDE_VAT): BooleanSelector(),
    }
)

DEFAULT_OPTIONS = {
    CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
    CONF_INCLUDE_VAT: DEFAULT_INCLUDE_VAT,
}


def _credentials(user_input: Mapping[str, Any], username: str) -> dict[str, Any]:
    """Return the config entry data for the given input."""
    data: dict[str, Any] = {
        CONF_USERNAME: username,
        CONF_PASSWORD: user_input[CONF_PASSWORD],
    }
    if shared_secret := normalize_shared_secret(user_input.get(CONF_SHARED_SECRET) or ""):
        data[CONF_SHARED_SECRET] = shared_secret
    return data


class InwxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for INWX."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: InwxConfigEntry) -> InwxOptionsFlow:
        """Get the options flow for this handler."""
        return InwxOptionsFlow()

    async def _async_validate(
        self, data: Mapping[str, Any]
    ) -> tuple[InwxAccount | None, dict[str, str]]:
        """Log in with the given credentials and return the account or errors."""
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=aiohttp.DummyCookieJar()
        )
        client = InwxClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data.get(CONF_SHARED_SECRET),
            session=session,
        )
        errors: dict[str, str] = {}
        account: InwxAccount | None = None
        try:
            account = await client.login()
        except InwxTwoFactorRequiredError:
            errors["base"] = "tfa_required"
        except InwxInvalidSharedSecretError:
            errors[CONF_SHARED_SECRET] = "invalid_shared_secret"
        except InwxTwoFactorError:
            errors["base"] = "invalid_tfa"
        except InwxAuthError:
            errors["base"] = "invalid_auth"
        except InwxConnectionError:
            errors["base"] = "cannot_connect"
        except InwxApiError:
            LOGGER.exception("Unexpected API response")
            errors["base"] = "unknown"
        except Exception:
            LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            try:
                await client.logout()
            except InwxError:
                LOGGER.debug("Logout after validation failed", exc_info=True)
        finally:
            session.detach()
        return account, errors

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _credentials(user_input, user_input[CONF_USERNAME])
            account, errors = await self._async_validate(data)
            if account is not None:
                await self.async_set_unique_id(str(account.customer_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=data[CONF_USERNAME], data=data, options=DEFAULT_OPTIONS
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials of the account."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        username = reauth_entry.data[CONF_USERNAME]
        if user_input is not None:
            data = _credentials(user_input, username)
            account, errors = await self._async_validate(data)
            if account is not None:
                await self.async_set_unique_id(str(account.customer_id))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(reauth_entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={CONF_USERNAME: username},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the credentials of the account."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            data = _credentials(user_input, user_input[CONF_USERNAME])
            account, errors = await self._async_validate(data)
            if account is not None:
                await self.async_set_unique_id(str(account.customer_id))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry, title=data[CONF_USERNAME], data=data
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {CONF_USERNAME: reconfigure_entry.data[CONF_USERNAME]},
            ),
            errors=errors,
        )


class InwxOptionsFlow(OptionsFlowWithReload):
    """Handle INWX options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the forecast options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, {**DEFAULT_OPTIONS, **self.config_entry.options}
            ),
        )
