"""DataUpdateCoordinator za Yettel Srbija."""
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import YettelApi, YettelAuthError, YettelPinError, YettelApiError
from .const import CONF_USERNAME, CONF_PASSWORD, CONF_PIN, CONF_MSISDN, DOMAIN

_LOGGER = logging.getLogger(__name__)


class YettelCoordinator(DataUpdateCoordinator):
    """Upravlja dohvatanjem i osvežavanjem Yettel podataka."""

    def __init__(self, hass: HomeAssistant, api: YettelApi, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data.get(CONF_MSISDN, '')}",
            update_interval=timedelta(hours=4),
        )
        self._api = api
        self._entry = entry
        self._msisdn = entry.data.get(CONF_MSISDN, "")

    async def _async_update_data(self) -> dict:
        try:
            home = await self._api.get_home()

            # Sesija istekla (vraćeno {} jer je has_pin) → ponovni login
            if not home:
                _LOGGER.debug("Yettel sesija istekla, ponovni login")
                await self._api.login(
                    self._entry.data[CONF_USERNAME],
                    self._entry.data[CONF_PASSWORD],
                    self._entry.data[CONF_PIN],
                )
                home = await self._api.get_home()

            if not home:
                raise UpdateFailed("Prazni podaci posle ponovnog login-a")

            parsed = self._api.parse_home(home, self._msisdn)

            # Dopuna iz istorije računa ako home nema iznos
            if parsed.get("bill_amount") is None and self._msisdn:
                history = await self._api.get_bill_history(self._msisdn)
                bill = self._api.parse_latest_bill(history)
                for key, val in bill.items():
                    if val is not None:
                        parsed[key] = val

            return parsed

        except YettelAuthError as err:
            if "2FA" in str(err):
                raise ConfigEntryAuthFailed(
                    "Potrebna ponovna 2FA verifikacija"
                ) from err
            raise ConfigEntryAuthFailed(str(err)) from err
        except YettelPinError as err:
            raise ConfigEntryAuthFailed(f"PIN greška: {err}") from err
        except YettelApiError as err:
            raise UpdateFailed(str(err)) from err
