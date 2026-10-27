"""Asynchronous client for the INWX DomRobot JSON-RPC API."""

import asyncio
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import pyotp

API_URL = "https://api.domrobot.com/jsonrpc/"

CODE_AUTH_ERROR = 2200
DOMAIN_LIST_PAGE_LIMIT = 100
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
TOTP_INTERVAL = 30

# INWX returns timestamps without offset in German local time.
INWX_TIMEZONE = ZoneInfo("Europe/Berlin")

# A TOTP code may only be used once. The config flow and the following setup
# log in within seconds, so remember the last used time step per user.
_last_totp_step: dict[str, int] = {}


class InwxError(Exception):
    """Base error of the INWX client."""


class InwxConnectionError(InwxError):
    """Error to indicate the API could not be reached."""


class InwxAuthError(InwxError):
    """Error to indicate the credentials were rejected."""


class InwxTwoFactorRequiredError(InwxAuthError):
    """Error to indicate the account needs a 2FA shared secret."""


class InwxTwoFactorError(InwxAuthError):
    """Error to indicate the 2FA code was rejected."""


class InwxInvalidSharedSecretError(InwxAuthError):
    """Error to indicate the 2FA shared secret is not valid Base32."""


class InwxApiError(InwxError):
    """Error to indicate the API answered with an error code."""

    def __init__(self, code: int | None, message: str) -> None:
        """Initialize the error."""
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class InwxAccount:
    """Account returned by the login."""

    customer_id: int
    customer_no: int | None


@dataclass(frozen=True, slots=True)
class InwxBalance:
    """Account balance."""

    available: float
    locked: float
    credit_limit: float


@dataclass(frozen=True, slots=True)
class InwxDomain:
    """Domain of the account."""

    ro_id: int
    name: str
    name_ace: str
    status: str | None
    renewal_mode: str | None
    period: str | None
    renewal_date: datetime | None
    expiration_date: datetime | None


@dataclass(frozen=True, slots=True)
class InwxPrice:
    """Renewal price of a domain."""

    net: float
    gross: float
    currency: str


def normalize_shared_secret(shared_secret: str) -> str:
    """Return the shared secret without spaces and in upper case."""
    return "".join(shared_secret.split()).upper()


def parse_datetime(value: Any) -> datetime | None:
    """Parse a timestamp of the API."""
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y%m%dT%H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=INWX_TIMEZONE)
    return parsed


class InwxClient:
    """Client for the INWX DomRobot JSON-RPC API.

    The session must not share its cookie jar with other clients, because the
    API session is kept in a cookie.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        shared_secret: str | None = None,
        url: str = API_URL,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._username = username
        self._password = password
        self._shared_secret = normalize_shared_secret(shared_secret) if shared_secret else None
        self._url = url
        self._cookies: dict[str, str] = {}

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call an API method and return its result data."""
        payload = {"method": method, "params": params or {}}
        try:
            async with self._session.post(
                self._url,
                json=payload,
                cookies=self._cookies,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
                for name, morsel in response.cookies.items():
                    self._cookies[name] = morsel.value
        except (aiohttp.ClientError, TimeoutError) as err:
            raise InwxConnectionError(f"Request {method} failed: {err}") from err
        except ValueError as err:
            raise InwxApiError(None, f"Invalid response for {method}") from err

        if not isinstance(body, dict) or not isinstance(body.get("code"), int):
            raise InwxApiError(None, f"Invalid response for {method}")
        code: int = body["code"]
        if code >= 2000:
            message = str(body.get("msg", ""))
            if code == CODE_AUTH_ERROR:
                raise InwxAuthError(message)
            raise InwxApiError(code, message)
        res_data = body.get("resData")
        return res_data if isinstance(res_data, dict) else {}

    async def _async_totp_code(self, shared_secret: str) -> str:
        """Return a TOTP code that has not been used yet."""
        step = int(time.time()) // TOTP_INTERVAL
        if _last_totp_step.get(self._username, -1) >= step:
            await asyncio.sleep(TOTP_INTERVAL - time.time() % TOTP_INTERVAL + 1)
            step = int(time.time()) // TOTP_INTERVAL
        try:
            code = pyotp.TOTP(shared_secret, interval=TOTP_INTERVAL).at(
                datetime.fromtimestamp(step * TOTP_INTERVAL, UTC)
            )
        except (binascii.Error, ValueError) as err:
            raise InwxInvalidSharedSecretError("Shared secret is not valid Base32") from err
        _last_totp_step[self._username] = step
        return code

    async def login(self) -> InwxAccount:
        """Log in and unlock the session with 2FA if required."""
        self._cookies.clear()
        res_data = await self._call(
            "account.login", {"user": self._username, "pass": self._password}
        )
        if str(res_data.get("tfa", "0")) != "0":
            if not self._shared_secret:
                raise InwxTwoFactorRequiredError("Account requires a 2FA shared secret")
            tan = await self._async_totp_code(self._shared_secret)
            try:
                await self._call("account.unlock", {"tan": tan})
            except InwxApiError as err:
                raise InwxTwoFactorError(err.message) from err
            except InwxAuthError as err:
                raise InwxTwoFactorError(str(err)) from err
        try:
            customer_id = int(res_data["customerId"])
        except (KeyError, TypeError, ValueError) as err:
            raise InwxApiError(None, "Login response without customer ID") from err
        customer_no = res_data.get("customerNo")
        return InwxAccount(
            customer_id=customer_id,
            customer_no=int(customer_no) if customer_no is not None else None,
        )

    async def logout(self) -> None:
        """Log out and drop the session."""
        try:
            await self._call("account.logout")
        finally:
            self._cookies.clear()

    async def get_balance(self) -> InwxBalance:
        """Return the account balance."""
        res_data = await self._call("accounting.accountBalance")
        try:
            return InwxBalance(
                available=float(res_data["available"]),
                locked=float(res_data.get("locked", 0)),
                credit_limit=float(res_data.get("creditLimit", 0)),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise InwxApiError(None, "Invalid account balance") from err

    async def get_domains(self) -> list[InwxDomain]:
        """Return all domains of the account."""
        domains: list[InwxDomain] = []
        page = 1
        while True:
            res_data = await self._call(
                "domain.list", {"page": page, "pagelimit": DOMAIN_LIST_PAGE_LIMIT}
            )
            entries = res_data.get("domain") or []
            if not isinstance(entries, list):
                raise InwxApiError(None, "Invalid domain list")
            for entry in entries:
                try:
                    domains.append(
                        InwxDomain(
                            ro_id=int(entry["roId"]),
                            name=str(entry["domain"]),
                            name_ace=str(entry.get("domain-ace") or entry["domain"]),
                            status=entry.get("status"),
                            renewal_mode=entry.get("renewalMode"),
                            period=entry.get("period"),
                            renewal_date=parse_datetime(entry.get("reDate")),
                            expiration_date=parse_datetime(entry.get("exDate")),
                        )
                    )
                except (KeyError, TypeError, ValueError) as err:
                    raise InwxApiError(None, "Invalid domain entry") from err
            count = int(res_data.get("count", len(domains)))
            if not entries or len(domains) >= count:
                return domains
            page += 1

    async def get_renewal_price(self, domain: InwxDomain) -> InwxPrice:
        """Return the renewal price of a domain."""
        params: dict[str, Any] = {"domain": [domain.name_ace]}
        if domain.period:
            params["period"] = domain.period
        res_data = await self._call("domain.getalldomainprices", params)
        entry = res_data.get("domain")
        if isinstance(entry, list):
            entry = entry[0] if entry else None
        elif isinstance(entry, dict) and "renewalPrice" not in entry:
            entry = entry.get(domain.name_ace) or entry.get(domain.name)
        if not isinstance(entry, dict):
            raise InwxApiError(None, f"No price for {domain.name}")
        try:
            return InwxPrice(
                net=float(entry["renewalPrice"]),
                gross=float(entry["renewalPriceWithVat"]),
                currency=str(entry["currency"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise InwxApiError(None, f"Invalid price for {domain.name}") from err
