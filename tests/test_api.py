"""Tests for the INWX API client."""

from datetime import datetime
from http.cookies import SimpleCookie
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
from freezegun.api import FrozenDateTimeFactory
import pyotp
import pytest

from custom_components.inwx.api import (
    INWX_TIMEZONE,
    InwxApiError,
    InwxAuthError,
    InwxClient,
    InwxConnectionError,
    InwxDomain,
    InwxInvalidSharedSecretError,
    InwxPrice,
    InwxTwoFactorError,
    InwxTwoFactorRequiredError,
    parse_datetime,
)

SHARED_SECRET = "JBSWY3DPEHPK3PXP"
LOGIN_OK = {
    "code": 1000,
    "msg": "OK",
    "resData": {"customerId": 12345, "customerNo": 1, "tfa": "0"},
}
LOGIN_TFA = {
    "code": 1000,
    "msg": "OK",
    "resData": {"customerId": 12345, "customerNo": 1, "tfa": "GOOGLE-AUTH"},
}
OK = {"code": 1000, "msg": "OK"}


class FakeResponse:
    """Fake aiohttp response."""

    def __init__(self, body: Any, cookies: dict[str, str] | None = None) -> None:
        """Initialize the response."""
        self._body = body
        self.cookies: SimpleCookie = SimpleCookie()
        for name, value in (cookies or {}).items():
            self.cookies[name] = value

    async def __aenter__(self) -> FakeResponse:
        """Enter the context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the context."""

    def raise_for_status(self) -> None:
        """Do not raise."""

    async def json(self, content_type: str | None = None) -> Any:
        """Return the body."""
        return self._body


class FakeSession:
    """Fake aiohttp session that returns prepared responses."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        """Initialize the session."""
        self._responses = list(responses)
        self.requests: list[tuple[dict[str, Any], dict[str, str]]] = []

    def post(
        self, url: str, *, json: dict[str, Any], cookies: dict[str, str], timeout: Any
    ) -> FakeResponse:
        """Return the next response."""
        self.requests.append((json, dict(cookies)))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(session: FakeSession, shared_secret: str | None = None) -> InwxClient:
    """Return a client for the fake session."""
    return InwxClient(session, "user", "pass", shared_secret)  # type: ignore[arg-type]


async def test_login_keeps_session_cookie() -> None:
    """Test the login and the use of the session cookie."""
    session = FakeSession(
        FakeResponse(LOGIN_OK, cookies={"domrobot": "abc"}),
        FakeResponse({"code": 1000, "resData": {"available": 5, "locked": 1, "creditLimit": 0}}),
    )
    client = make_client(session)

    account = await client.login()
    balance = await client.get_balance()

    assert account.customer_id == 12345
    assert balance.available == 5.0
    assert session.requests[0][0] == {
        "method": "account.login",
        "params": {"user": "user", "pass": "pass"},
    }
    assert session.requests[1][1] == {"domrobot": "abc"}


async def test_login_with_two_factor(freezer: FrozenDateTimeFactory) -> None:
    """Test the login with 2FA."""
    freezer.move_to("2026-10-26 12:00:05")
    session = FakeSession(FakeResponse(LOGIN_TFA), FakeResponse(OK))
    client = make_client(session, "jbsw y3dp ehpk 3pxp")

    await client.login()

    assert session.requests[1][0] == {
        "method": "account.unlock",
        "params": {
            "tan": pyotp.TOTP(SHARED_SECRET).at(datetime.fromisoformat("2026-10-26T12:00:00+00:00"))
        },
    }


async def test_totp_code_is_not_reused(freezer: FrozenDateTimeFactory) -> None:
    """Test that a second login in the same time step waits for a new code."""
    freezer.move_to("2026-10-26 12:00:05")
    session = FakeSession(
        FakeResponse(LOGIN_TFA), FakeResponse(OK), FakeResponse(LOGIN_TFA), FakeResponse(OK)
    )
    client = make_client(session, SHARED_SECRET)

    async def fake_sleep(seconds: float) -> None:
        freezer.tick(seconds)

    with patch(
        "custom_components.inwx.api.asyncio.sleep", AsyncMock(side_effect=fake_sleep)
    ) as sleep:
        await client.login()
        await client.login()

    sleep.assert_awaited_once()
    first_tan = session.requests[1][0]["params"]["tan"]
    second_tan = session.requests[3][0]["params"]["tan"]
    assert first_tan != second_tan
    assert second_tan == pyotp.TOTP(SHARED_SECRET).at(
        datetime.fromisoformat("2026-10-26T12:00:30+00:00")
    )


async def test_two_factor_without_secret() -> None:
    """Test the login of a 2FA account without shared secret."""
    client = make_client(FakeSession(FakeResponse(LOGIN_TFA)))

    with pytest.raises(InwxTwoFactorRequiredError):
        await client.login()


async def test_two_factor_rejected() -> None:
    """Test a rejected 2FA code."""
    client = make_client(
        FakeSession(FakeResponse(LOGIN_TFA), FakeResponse({"code": 2200, "msg": "Auth"})),
        SHARED_SECRET,
    )

    with pytest.raises(InwxTwoFactorError):
        await client.login()


async def test_invalid_shared_secret() -> None:
    """Test a shared secret that is not Base32."""
    client = make_client(FakeSession(FakeResponse(LOGIN_TFA)), "not-base32!")

    with pytest.raises(InwxInvalidSharedSecretError):
        await client.login()


async def test_invalid_credentials() -> None:
    """Test rejected credentials."""
    client = make_client(FakeSession(FakeResponse({"code": 2200, "msg": "Authentication error"})))

    with pytest.raises(InwxAuthError):
        await client.login()


async def test_api_error() -> None:
    """Test an error code of the API."""
    client = make_client(FakeSession(FakeResponse({"code": 2400, "msg": "Command failed"})))

    with pytest.raises(InwxApiError, match="2400: Command failed"):
        await client.get_balance()


async def test_invalid_response() -> None:
    """Test a response without result code."""
    client = make_client(FakeSession(FakeResponse(["unexpected"])))

    with pytest.raises(InwxApiError):
        await client.get_balance()


async def test_connection_error() -> None:
    """Test a failed request."""
    client = make_client(FakeSession(aiohttp.ClientConnectionError("down")))

    with pytest.raises(InwxConnectionError):
        await client.login()


async def test_get_domains_with_pages() -> None:
    """Test reading the domain list over several pages."""
    first = {
        "roId": 1,
        "domain": "example.de",
        "domain-ace": "example.de",
        "status": "OK",
        "renewalMode": "AUTORENEW",
        "period": "1Y",
        "reDate": "2026-11-20T00:00:00Z",
        "exDate": "2026-11-25 10:00:00",
    }
    second = {"roId": 2, "domain": "müller.de", "domain-ace": "xn--mller-kva.de"}
    session = FakeSession(
        FakeResponse({"code": 1000, "resData": {"count": 2, "domain": [first]}}),
        FakeResponse({"code": 1000, "resData": {"count": 2, "domain": [second]}}),
    )
    client = make_client(session)

    domains = await client.get_domains()

    assert [request[0]["params"]["page"] for request in session.requests] == [1, 2]
    assert domains[0].renewal_date == datetime.fromisoformat("2026-11-20T00:00:00+00:00")
    assert domains[0].expiration_date == datetime(2026, 11, 25, 10, tzinfo=INWX_TIMEZONE)
    assert domains[1].name_ace == "xn--mller-kva.de"
    assert domains[1].renewal_date is None


async def test_get_domains_empty() -> None:
    """Test an account without domains."""
    client = make_client(FakeSession(FakeResponse({"code": 1000, "resData": {"count": 0}})))

    assert await client.get_domains() == []


DOMAIN = InwxDomain(
    ro_id=1,
    name="example.de",
    name_ace="example.de",
    status="OK",
    renewal_mode="AUTORENEW",
    period="1Y",
    renewal_date=None,
    expiration_date=None,
)
PRICE_ENTRY = {"renewalPrice": 4.0, "renewalPriceWithVat": 4.76, "currency": "EUR"}


@pytest.mark.parametrize(
    "res_data",
    [
        {"domain": PRICE_ENTRY},
        {"domain": [PRICE_ENTRY]},
        {"domain": {"example.de": PRICE_ENTRY}},
    ],
)
async def test_get_renewal_price(res_data: dict[str, Any]) -> None:
    """Test the supported layouts of the price response."""
    session = FakeSession(FakeResponse({"code": 1000, "resData": res_data}))
    client = make_client(session)

    assert await client.get_renewal_price(DOMAIN) == InwxPrice(net=4.0, gross=4.76, currency="EUR")
    assert session.requests[0][0] == {
        "method": "domain.getalldomainprices",
        "params": {"domain": ["example.de"], "period": "1Y"},
    }


@pytest.mark.parametrize(
    "res_data",
    [{}, {"domain": []}, {"domain": {"other.de": PRICE_ENTRY}}, {"domain": {"renewalPrice": 1}}],
)
async def test_get_renewal_price_invalid(res_data: dict[str, Any]) -> None:
    """Test price responses without usable price."""
    client = make_client(FakeSession(FakeResponse({"code": 1000, "resData": res_data})))

    with pytest.raises(InwxApiError):
        await client.get_renewal_price(DOMAIN)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("invalid", None),
        ("20261120T10:00:00", datetime(2026, 11, 20, 10, tzinfo=INWX_TIMEZONE)),
    ],
)
def test_parse_datetime(value: str | None, expected: datetime | None) -> None:
    """Test parsing of timestamps."""
    assert parse_datetime(value) == expected
