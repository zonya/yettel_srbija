"""Yettel Srbija API klijent."""
import re
import logging
from typing import Any

import aiohttp

from .const import (
    NALOG_BASE,
    API_BASE,
    OAUTH_INIT,
    OAUTH_VALIDATE_TEMP,
    API_ID,
    APP_ID,
    APP_VERSION,
    API_VERSION,
    HDR_API_ID,
    HDR_APP_ID,
    HDR_APP_VERSION,
    HDR_API_VERSION,
    HDR_TOKEN,
    HDR_PIN_TOKEN,
)

_LOGGER = logging.getLogger(__name__)


def _gb_from_text(text: str) -> float | None:
    """Izvlači GB vrednost iz teksta poput '<b>21.50 GB</b>'."""
    m = re.search(r"([\d.]+)\s*GB", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


class YettelAuthError(Exception):
    pass


class YettelPinError(Exception):
    pass


class YettelApiError(Exception):
    pass


class YettelApi:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._api_token: str | None = None
        self._pin_token: str | None = None

    # ------------------------------------------------------------------
    # Headeri za api.yettel.rs (PWA API ne koristi kolačiće za auth)
    # ------------------------------------------------------------------

    def _api_headers(self) -> dict[str, str]:
        h = {
            HDR_API_ID: API_ID,
            HDR_APP_ID: APP_ID,
            HDR_APP_VERSION: APP_VERSION,
            HDR_API_VERSION: API_VERSION,
        }
        if self._api_token:
            h[HDR_TOKEN] = self._api_token
        if self._pin_token:
            h[HDR_PIN_TOKEN] = self._pin_token
        return h

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str, pin: str) -> dict:
        """Potpuna auth sekvenca (pretpostavlja zapamćen uređaj — bez 2FA)."""
        needs_2fa = await self.begin_login(username, password)
        if needs_2fa:
            raise YettelAuthError("2FA_REQUIRED")
        token_pin = await self.finish_login(pin)
        return {"token_pin": token_pin}

    async def begin_login(self, username: str, password: str) -> bool:
        """Korak 1: CSRF + login. Vraća True ako je potrebna 2FA."""
        try:
            csrf_name, csrf_value = await self._get_csrf()
            try:
                await self._post_login(csrf_name, csrf_value, username, password)
            except YettelAuthError as err:
                if "2FA_REQUIRED" in str(err):
                    return True
                raise
            return False
        except (YettelAuthError, YettelApiError):
            raise
        except aiohttp.ClientError as err:
            raise YettelApiError(f"Mrežna greška: {err}") from err

    async def finish_login(self, pin: str) -> str:
        """Korak 2: OAuth lanac (api token) + PIN. Vraća tokenPin."""
        self._api_token = await self._exchange_oauth()
        self._pin_token = await self._validate_pin(pin)
        return self._pin_token

    async def _get_csrf(self) -> tuple[str, str]:
        async with self._session.get(
            f"{NALOG_BASE}/app/login",
            allow_redirects=True,
        ) as r:
            html = await r.text()
        name = re.search(r'name="csrf_name"\s+value="([^"]+)"', html)
        value = re.search(r'name="csrf_value"\s+value="([^"]+)"', html)
        if not name or not value:
            raise YettelApiError("CSRF tokeni nisu pronađeni")
        return name.group(1), value.group(1)

    async def _post_login(
        self, csrf_name: str, csrf_value: str, username: str, password: str
    ) -> None:
        async with self._session.post(
            f"{NALOG_BASE}/app/login-post",
            data={
                "csrf_name": csrf_name,
                "csrf_value": csrf_value,
                "resource": username,
                "password": password,
                "stayLogin": "on",
            },
            allow_redirects=True,
        ) as r:
            if r.status not in (200, 302):
                raise YettelAuthError(f"Login HTTP {r.status}")
            url = str(r.url)
            if "2fa" in url:
                raise YettelAuthError("2FA_REQUIRED")

    async def _exchange_oauth(self) -> str:
        """Pun OAuth lanac → vraća X-Yettel-Api-Token (JWT).

        1. GET /pwa/login/init → 302 na /nalog/api/auth (server upiše state u
           api PHPSESSID; OBAVEZNO — bez ovoga authorize-back vraća 403).
        2. GET auth URL (već ulogovan na nalog) → HTML sa JS redirektom na
           authorize-back?code=...&state=...
        3. GET authorize-back → 302 na PWA: .../#/login/<tempToken>
        4. POST /pwa/login/validate-temp-token (tempToken) → data.data.token
        """
        # 1) init
        async with self._session.get(
            f"{API_BASE}{OAUTH_INIT}",
            headers=self._api_headers(),
            allow_redirects=False,
        ) as r:
            auth_url = r.headers.get("Location")
            if not auth_url:
                raise YettelApiError(f"login/init bez redirekta (HTTP {r.status})")

        # 2) auth → JS redirect HTML
        async with self._session.get(auth_url, allow_redirects=False) as r:
            html = await r.text()
        m = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', html)
        if not m:
            raise YettelApiError("OAuth: authorize-back URL nije pronađen")
        back_url = m.group(1).replace("&amp;", "&")

        # 3) authorize-back → redirect na PWA sa tempToken-om
        async with self._session.get(back_url, allow_redirects=False) as r:
            loc = r.headers.get("Location", "")
        mt = re.search(r"#/login/([0-9a-fA-F]+)", loc)
        if not mt:
            raise YettelApiError("OAuth: tempToken nije pronađen (login neuspešan)")
        temp_token = mt.group(1)

        # 4) validate-temp-token → pravi api token
        async with self._session.post(
            f"{API_BASE}{OAUTH_VALIDATE_TEMP}",
            data={"tempToken": temp_token},
            headers=self._api_headers(),
        ) as r:
            if r.status != 200:
                raise YettelApiError(f"validate-temp-token HTTP {r.status}")
            data = await r.json(content_type=None)
        inner = data.get("data", {})
        token = inner.get("token")
        if not inner.get("success") or not token:
            raise YettelApiError("validate-temp-token nije vratio token")
        return token

    async def _validate_pin(self, pin: str) -> str:
        async with self._session.post(
            f"{API_BASE}/pwa/services/validate-pin",
            data={"pin": pin},
            headers=self._api_headers(),
        ) as r:
            if r.status != 200:
                raise YettelPinError(f"PIN HTTP {r.status}")
            data = await r.json(content_type=None)
            inner = data.get("data", {})
            token_pin = inner.get("tokenPin")
            if not inner.get("success", True) or not token_pin:
                raise YettelPinError("tokenPin nije vraćen (pogrešan PIN?)")
            return token_pin

    # ------------------------------------------------------------------
    # Podaci
    # ------------------------------------------------------------------

    async def get_home(self) -> dict:
        """Dohvata /index/home. Vraća {} ako je sesija/token istekla."""
        async with self._session.get(
            f"{API_BASE}/index/home", headers=self._api_headers()
        ) as r:
            # 401/403 = istekao api token; has_pin = istekao pin token → re-login
            if r.status in (401, 403):
                return {}
            if r.status != 200:
                raise YettelApiError(f"home HTTP {r.status}")
            data = await r.json(content_type=None)
        inner = data.get("data", {})
        if "has_pin" in inner:
            return {}
        return inner

    async def get_bill_history(self, msisdn: str) -> list[dict]:
        async with self._session.get(
            f"{API_BASE}/pages/resource-bills-history",
            params={"identifier": msisdn},
            headers=self._api_headers(),
        ) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
        # Vraća listu items-a; svaki item ima 'elements' sa smallMonthlyInvoice.
        # parse_latest_bill() prolazi kroz items i traži najnoviji račun.
        items: list[dict] = []
        try:
            for page in data["data"]["pages"]:
                for group in page.get("groups", []):
                    items.extend(group.get("items", []))
        except (KeyError, IndexError, TypeError):
            return []
        return items

    async def get_account_list(self, home_data: dict) -> list[dict]:
        """Izvlači listu dostupnih brojeva iz home podataka."""
        accounts = []
        try:
            pages = home_data.get("pages", [])
            for page in pages:
                for group in page.get("groups", []):
                    for item in group.get("items", []):
                        for el in item.get("elements", []):
                            if el.get("type") == "accountPicker2":
                                for lst in el.get("list", []):
                                    accounts.extend(lst)
        except Exception:
            pass
        return accounts

    def get_primary_account(self, accounts: list[dict]) -> dict | None:
        """Vraća primarni nalog (broj + tarifa) iz liste."""
        for acc in accounts:
            if acc.get("primary"):
                return acc
        return accounts[0] if accounts else None

    async def submit_2fa(self, otp_code: str, resource: str) -> None:
        """Šalje SMS OTP kod sa rememberDevice=1 (preskače 2FA ubuduće)."""
        csrf_name, csrf_value = await self._get_2fa_csrf()
        async with self._session.post(
            f"{NALOG_BASE}/app/2fa/confirm-code-post",
            data={
                "csrf_name": csrf_name,
                "csrf_value": csrf_value,
                "resource": resource,
                "resend_code": "false",
                "skip_account_existance_check": "1",
                "type": "msisdn",
                "otpCode": otp_code,
                "rememberDevice": "1",
            },
            allow_redirects=True,
        ) as r:
            if r.status not in (200, 302):
                raise YettelAuthError(f"2FA HTTP {r.status}")
            if "confirm-code" in str(r.url):
                raise YettelAuthError("INVALID_OTP")

    async def _get_2fa_csrf(self) -> tuple[str, str]:
        async with self._session.get(
            f"{NALOG_BASE}/app/2fa/confirm-code",
        ) as r:
            html = await r.text()
        name = re.search(r'name="csrf_name"\s+value="([^"]+)"', html)
        value = re.search(r'name="csrf_value"\s+value="([^"]+)"', html)
        if not name or not value:
            raise YettelApiError("2FA CSRF tokeni nisu pronađeni")
        return name.group(1), value.group(1)

    def parse_home(self, home_data: dict, msisdn: str) -> dict:
        """Parsira home_data i vraća dict sa svim vrednostima za senzore."""
        result: dict[str, Any] = {
            "msisdn": msisdn,
            "balance": None,
            "tariff": None,
            "bill_amount": None,
            "bill_status": None,
            "bill_deadline": None,
            "bill_month": None,
            "internet_gb": None,
            "internet_unlimited": False,
            "roaming_gb": None,
            "wb_gb": None,
            "minutes_unlimited": False,
            "sms_unlimited": False,
        }

        try:
            pages = home_data.get("pages", [])
            for page in pages:
                stat = page.get("stat", {})
                for prop_name, prop in stat.get("user_properties", {}).items():
                    if prop_name == "actualTariffName":
                        result["tariff"] = prop.get("value")
                    elif prop_name == "planType":
                        result["plan_type"] = prop.get("value")

                for group in page.get("groups", []):
                    for item in group.get("items", []):
                        for el in item.get("elements", []):
                            etype = el.get("type", "")

                            if etype == "accountBalanceMoney":
                                val = el.get("value", "").replace(".", "").replace(",", ".")
                                try:
                                    result["balance"] = float(val)
                                except ValueError:
                                    pass

                            elif etype == "YPaySummary":
                                bills = el.get("list", [])
                                if bills:
                                    b = bills[0]
                                    amt = b.get("contentAmount", "").replace(".", "").replace(",", ".")
                                    try:
                                        result["bill_amount"] = float(amt)
                                    except ValueError:
                                        pass
                                    status_txt = b.get("status", "")
                                    result["bill_status"] = (
                                        "placen" if "plaćen" in status_txt.lower() and "nije" not in status_txt.lower()
                                        else "nije_placen"
                                    )
                                    result["bill_deadline"] = b.get("contentDeadline", "").replace("Rok: ", "")
                                    result["bill_month"] = b.get("month")

                            elif etype == "accountBalanceDetails":
                                for tab in el.get("tabs", []):
                                    if tab.get("title") == "Internet":
                                        result["internet_unlimited"] = tab.get("unlimited", False)
                                        if not result["internet_unlimited"]:
                                            result["internet_gb"] = tab.get("value")
                                        for v in tab.get("vals", []):
                                            info = v.get("additionalInfo", "")
                                            txt = v.get("text1", "")
                                            if "roming" in txt.lower() and "balkan" not in txt.lower():
                                                gb = v.get("val", 0) / (1024 ** 3)
                                                result["roaming_gb"] = round(gb, 2)
                                            elif "balkan" in txt.lower() or "wb" in info.lower():
                                                gb = v.get("val", 0) / (1024 ** 3)
                                                result["wb_gb"] = round(gb, 2)

                            elif etype == "progressBar":
                                info = el.get("additionalInfo", "")
                                text1 = el.get("text1", "")
                                text2 = el.get("text2", "")
                                if info == "MIN":
                                    result["minutes_unlimited"] = "Neograničeno" in text2
                                elif info == "SMS":
                                    result["sms_unlimited"] = "Neograničeno" in text2
                                elif "balkan" in text1.lower():
                                    gb = _gb_from_text(text2)
                                    if gb is not None:
                                        result["wb_gb"] = gb
                                elif "roming internet" in text1.lower():
                                    gb = _gb_from_text(text2)
                                    if gb is not None:
                                        result["roaming_gb"] = gb
        except Exception as exc:
            _LOGGER.warning("Greška pri parsiranju home podataka: %s", exc)

        return result

    def parse_latest_bill(self, bill_items: list) -> dict:
        """Izvlači poslednji račun iz istorije računa."""
        result: dict[str, Any] = {
            "bill_amount": None,
            "bill_status": None,
            "bill_deadline": None,
            "bill_month": None,
        }
        for item in bill_items:
            for el in item.get("elements", []) if isinstance(item, dict) else []:
                if el.get("type") == "smallMonthlyInvoice":
                    amt = el.get("contentAmount", "").replace(".", "").replace(",", ".")
                    try:
                        result["bill_amount"] = float(amt)
                    except ValueError:
                        pass
                    status_txt = el.get("text", "")
                    result["bill_status"] = (
                        "placen" if "plaćen" in status_txt.lower() and "nije" not in status_txt.lower()
                        else "nije_placen"
                    )
                    result["bill_deadline"] = el.get("contentDeadline")
                    result["bill_month"] = el.get("title")
                    return result
        return result
