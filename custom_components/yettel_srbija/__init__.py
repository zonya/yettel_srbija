"""Yettel Srbija integracija."""
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .api import YettelApi
from .const import DOMAIN, USER_AGENT, CONF_MSISDN, CONF_NICKNAME, cookie_path
from .coordinator import YettelCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    key = entry.unique_id or entry.entry_id
    cpath = cookie_path(hass, key)
    jar = aiohttp.CookieJar()

    # Učitaj "remember device" kolačić ako postoji (preskače 2FA)
    def _load():
        import os
        if os.path.exists(cpath):
            try:
                jar.load(cpath)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Ne mogu da učitam kolačiće: %s", exc)

    await hass.async_add_executor_job(_load)

    session = aiohttp.ClientSession(
        cookie_jar=jar,
        headers={"User-Agent": USER_AGENT},
    )

    api = YettelApi(session)
    coordinator = YettelCoordinator(hass, api, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    # Sačuvaj kolačiće posle uspešnog login-a
    def _save():
        try:
            jar.save(cpath)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Ne mogu da sačuvam kolačiće: %s", exc)

    await hass.async_add_executor_job(_save)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "session": session,
    }

    # Reload kad se promene opcije (npr. nadimak)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _register_services(hass: HomeAssistant) -> None:
    """Dijagnostički servis: vraća sirov home + listu naloga (za otkrivanje
    fiksnih usluga — optika/TV — bez novog logina/SMS-a)."""
    if hass.services.has_service(DOMAIN, "dump"):
        return

    async def _dump(call: ServiceCall) -> dict:
        out: dict = {}
        for entry_id, store in hass.data.get(DOMAIN, {}).items():
            coord = store["coordinator"]
            api: YettelApi = coord._api
            entry = hass.config_entries.async_get_entry(entry_id)
            label = (entry.data.get(CONF_NICKNAME) or entry.data.get(CONF_MSISDN) or entry_id)
            try:
                home = await api.get_home()
                if not home:  # token istekao → re-login preko kolačića (bez SMS)
                    from .const import CONF_USERNAME, CONF_PASSWORD, CONF_PIN
                    await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD], entry.data[CONF_PIN])
                    home = await api.get_home()
                accounts = await api.get_account_list(home)
                extra = await api.probe_fixed(call.data.get("paths"))
                out[label] = {"accounts": accounts, "home": home, "probe": extra}
            except Exception as exc:  # noqa: BLE001
                out[label] = {"error": f"{type(exc).__name__}: {exc}"}
        return out

    hass.services.async_register(
        DOMAIN, "dump", _dump, supports_response=SupportsResponse.ONLY
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        await stored["session"].close()
    return unload_ok
