DOMAIN = "yettel_srbija"

NALOG_BASE = "https://www.yettel.rs/nalog"
API_BASE = "https://api.yettel.rs/yettel/api"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PIN = "pin"
CONF_MSISDN = "msisdn"
CONF_TARIFF = "tariff"

# Yettel PWA očekuje pravi browser/mobilni User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
)


def cookie_path(hass, key: str) -> str:
    """Putanja fajla za perzistenciju kolačića (remember-device)."""
    safe = "".join(c for c in str(key) if c.isalnum())
    return hass.config.path(f".yettel_srbija_{safe}.cookies")
