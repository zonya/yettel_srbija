"""Config flow za Yettel Srbija."""
import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries

from .api import YettelApi, YettelAuthError, YettelPinError, YettelApiError
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_MSISDN,
    CONF_TARIFF,
    USER_AGENT,
    cookie_path,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_PIN): str,
    }
)

OTP_SCHEMA = vol.Schema({vol.Required("otp_code"): str})


class YettelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._api: YettelApi | None = None
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                headers={"User-Agent": USER_AGENT},
            )
            self._api = YettelApi(self._session)
            self._data = dict(user_input)

            try:
                needs_2fa = await self._api.begin_login(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except YettelAuthError:
                errors["base"] = "invalid_auth"
            except YettelApiError as err:
                _LOGGER.error("Yettel cannot_connect: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Yettel begin_login neočekivana greška")
                errors["base"] = "unknown"
            else:
                if needs_2fa:
                    return await self.async_step_2fa()
                return await self._finalize()

            await self._cleanup_session()

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_2fa(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                # resource = broj telefona ili email iz prvog koraka
                await self._api.submit_2fa(
                    user_input["otp_code"], self._data[CONF_USERNAME]
                )
            except YettelAuthError:
                errors["base"] = "invalid_otp"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Yettel 2FA neočekivana greška")
                errors["base"] = "unknown"
            else:
                return await self._finalize()

        return self.async_show_form(
            step_id="2fa", data_schema=OTP_SCHEMA, errors=errors
        )

    async def _finalize(self):
        """Završava login: PIN, čita msisdn, snima kolačiće, kreira entry."""
        try:
            await self._api.finish_login(self._data[CONF_PIN])
            home = await self._api.get_home()
            accounts = await self._api.get_account_list(home)
            primary = self._api.get_primary_account(accounts)
        except YettelPinError as err:
            _LOGGER.error("Yettel PIN greška: %s", err)
            await self._cleanup_session()
            return self.async_show_form(
                step_id="user",
                data_schema=USER_SCHEMA,
                errors={"base": "invalid_pin"},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Yettel _finalize neočekivana greška")
            await self._cleanup_session()
            return self.async_show_form(
                step_id="user",
                data_schema=USER_SCHEMA,
                errors={"base": "unknown"},
            )

        if not primary:
            await self._cleanup_session()
            return self.async_abort(reason="no_accounts")

        msisdn = primary.get("value", "")
        tariff = primary.get("text1", "Yettel")

        await self.async_set_unique_id(msisdn)
        self._abort_if_unique_id_configured()

        # Sačuvaj kolačiće (remember-device) keširane po msisdn
        cpath = cookie_path(self.hass, msisdn)
        jar = self._session.cookie_jar

        def _save():
            try:
                jar.save(cpath)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Ne mogu da sačuvam kolačiće: %s", exc)

        await self.hass.async_add_executor_job(_save)
        await self._cleanup_session()

        self._data[CONF_MSISDN] = msisdn
        self._data[CONF_TARIFF] = tariff

        return self.async_create_entry(
            title=f"{tariff} ({msisdn})",
            data=self._data,
        )

    async def _cleanup_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
