"""Yettel Srbija integracija."""
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import YettelApi
from .const import DOMAIN, USER_AGENT, cookie_path
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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        await stored["session"].close()
    return unload_ok
