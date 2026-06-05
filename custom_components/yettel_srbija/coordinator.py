"""DataUpdateCoordinator za Yettel Srbija (više naloga po loginu)."""
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import YettelApi, YettelAuthError, YettelPinError, YettelApiError
from .const import CONF_USERNAME, CONF_PASSWORD, CONF_PIN, CONF_MSISDN, CONF_TARIFF, DOMAIN

_LOGGER = logging.getLogger(__name__)


class YettelCoordinator(DataUpdateCoordinator):
    """Dohvata podatke za SVE naloge pod jednim Yettel loginom."""

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

            accounts = await self._api.get_account_list(home)
            primary = self._api.get_primary_account(accounts)
            primary_val = (primary or {}).get("value") or self._msisdn

            # Ako accountPicker nije vraćen (jedan nalog), napravi sintetički
            if not accounts:
                accounts = [
                    {
                        "value": self._msisdn,
                        "text1": self._entry.data.get(CONF_TARIFF, "Yettel"),
                    }
                ]

            by: dict = {}
            meta: list = []
            for acc in accounts:
                val = acc.get("value")
                if not val:
                    continue
                ah = home if val == primary_val else await self._api.get_home(slave=val)
                if not ah:
                    continue
                parsed = self._api.parse_home(ah, val)
                parsed["label"] = acc.get("text1") or val
                parsed["address"] = acc.get("text2") or ""

                # Dopuna računa iz istorije ako home nema iznos
                if parsed.get("bill_amount") is None:
                    history = await self._api.get_bill_history(val)
                    bill = self._api.parse_latest_bill(history)
                    for key, value in bill.items():
                        if value is not None:
                            parsed[key] = value

                by[val] = parsed
                meta.append(
                    {"value": val, "label": parsed["label"], "kind": parsed["kind"]}
                )

            if not by:
                raise UpdateFailed("Nijedan nalog nije vratio podatke")

            return {"accounts": meta, "by": by, "primary": primary_val}

        except YettelAuthError as err:
            if "2FA" in str(err):
                raise ConfigEntryAuthFailed("Potrebna ponovna 2FA verifikacija") from err
            raise ConfigEntryAuthFailed(str(err)) from err
        except YettelPinError as err:
            raise ConfigEntryAuthFailed(f"PIN greška: {err}") from err
        except YettelApiError as err:
            raise UpdateFailed(str(err)) from err
