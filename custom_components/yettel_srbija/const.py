DOMAIN = "yettel_srbija"

NALOG_BASE = "https://www.yettel.rs/nalog"
API_BASE = "https://api.yettel.rs/yettel/api"

# OAuth (pwa-new) — login/init endpoint sam generiše state + redirect_uri,
# pa ih mi ne šaljemo ručno (raniji bug: ručni state → authorize-back 403).
OAUTH_INIT = "/pwa/login/init"
OAUTH_VALIDATE_TEMP = "/pwa/login/validate-temp-token"

# api.yettel.rs PWA API se NE autentifikuje kolačićima nego X-Yettel-* headerima.
# API_ID je hardkodovana konstanta iz PWA bundla (ista za sve korisnike).
API_ID = "da3ac9670cf297b895e526f18d572385"
APP_ID = "2"
APP_VERSION = "2.13"
API_VERSION = "2.13"

HDR_API_ID = "X-Yettel-Api-Id"
HDR_APP_ID = "X-Yettel-App-Id"
HDR_APP_VERSION = "X-Yettel-App-Version"
HDR_API_VERSION = "X-Yettel-Api-Version"
HDR_TOKEN = "X-Yettel-Api-Token"
HDR_PIN_TOKEN = "X-Yettel-Api-Pin-Token"

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
