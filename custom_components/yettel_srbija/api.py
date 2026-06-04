"""Yettel Srbija API klijent."""
import re
import logging
from typing import Any

import aiohttp

from .const import NALOG_BASE, API_BASE

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
        csrf_name, csrf_value = await self._get_csrf()
        try:
            await self._post_login(csrf_name, csrf_value, username, password)
        except YettelAuthError as err:
            if "2FA_REQUIRED" in str(err):
                return True
            raise
        return False

    async def finish_login(self, pin: str) -> str:
        """Korak 2: OAuth + PIN. Vraća tokenPin."""
        await self._exchange_oauth()
        return await self._validate_pin(pin)

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

    async def _exchange_oauth(self) -> None:
        params = {
            "client_id": "pwa-new",
            "scope": "user_msisdn ftth_info user_info",
            "response_type": "code",
            "state": "ha_yettel_state",
            "redirect_uri": f"{API_BASE.replace('/api', '')}/api/pwa/login/authorize-back",
            "lang": "sr",
        }
        async with self._session.get(
            f"{NALOG_BASE}/api/auth",
            params=params,
            allow_redirects=True,
        ) as r:
            if r.status not in (200, 302):
                raise YettelApiError(f"OAuth HTTP {r.status}")

    async def _validate_pin(self, pin: str) -> str:
        async with self._session.post(
            f"{API_BASE}/pwa/services/validate-pin",
            data={"pin": pin},
        ) as r:
            if r.status != 200:
                raise YettelPinError(f"PIN HTTP {r.status}")
            data = await r.json(content_type=None)
            token_pin = data.get("data", {}).get("tokenPin")
            if not token_pin:
                raise YettelPinError("tokenPin nije vraćen")
            return token_pin

    # ------------------------------------------------------------------
    # Podaci
    # ------------------------------------------------------------------

    async def get_home(self) -> dict:
        """Dohvata /index/home. Vraća {} ako token istekao (has_pin)."""
        async with self._session.get(f"{API_BASE}/index/home") as r:
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
        ) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
        try:
            items = (
                data["data"]["pages"][0]["groups"][0]["items"][0]["elements"][0]
            )
            return items if isinstance(items, list) else []
        except (KeyError, IndexError, TypeError):
            return []

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
