"""Twelve Data adapter tests. No network: httpx.MockTransport plays the API.

Response bodies are trimmed copies of real Twelve Data responses (2026-10-06).
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from data_sources.market_data.base import (
    MarketDataProvider,
    ProviderError,
    RateLimitError,
    UnknownSymbolError,
)
from data_sources.market_data.twelve_data import BASE_URL, TwelveDataProvider

API_KEY = "test-key-123"

TIME_SERIES_OK = {
    "meta": {"symbol": "AAPL", "interval": "1day", "currency": "USD"},
    "values": [
        {"datetime": "2026-09-28", "close": "338.39999", "volume": "32820800"},
        {"datetime": "2026-09-29", "close": "329.39999", "volume": "38478000"},
    ],
    "status": "ok",
}
QUOTE_OK = {
    "symbol": "AAPL",
    "close": "332.89001",
    "volume": "34350900",
    "timestamp": 1791207000,
    "last_quote_at": 1791230340,
}
NOT_FOUND = {
    "code": 404,
    "message": "**symbol** or **figi** parameter is missing or invalid.",
    "status": "error",
}
NO_DATA = {
    "code": 400,
    "message": "No data is available on the specified dates.",
    "status": "error",
}
RATE_LIMIT = {
    "code": 429,
    "message": "You have run out of API credits for the current minute.",
    "status": "error",
}

Handler = Callable[[httpx.Request], httpx.Response]


def provider(handler: Handler) -> TwelveDataProvider:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return TwelveDataProvider(API_KEY, client=client)


def reply(status: int, body: Any) -> Handler:
    return lambda request: httpx.Response(status, json=body)


class Recorder:
    """A handler that remembers the requests it received."""

    def __init__(self, status: int, body: Any) -> None:
        self.requests: list[httpx.Request] = []
        self._status, self._body = status, body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status, json=self._body)


# --- construction ---------------------------------------------------------------


def test_satisfies_the_provider_contract() -> None:
    assert isinstance(provider(reply(200, QUOTE_OK)), MarketDataProvider)


@pytest.mark.parametrize("key", ["", "   "])
def test_rejects_empty_api_key(key: str) -> None:
    with pytest.raises(ValueError):
        TwelveDataProvider(key)


# --- security: where the key goes -----------------------------------------------


def test_api_key_is_sent_in_header_not_url() -> None:
    rec = Recorder(200, TIME_SERIES_OK)
    provider(rec).daily_closes("AAPL", date(2026, 9, 28), date(2026, 9, 29))

    request = rec.requests[0]
    assert request.headers["Authorization"] == f"apikey {API_KEY}"
    assert API_KEY not in str(request.url)


def test_errors_never_contain_the_api_key() -> None:
    with pytest.raises(ProviderError) as exc_info:
        server_error = {"code": 500, "message": "boom", "status": "error"}
        provider(reply(500, server_error)).latest_snapshot("AAPL")

    assert API_KEY not in str(exc_info.value)


# --- daily_closes ---------------------------------------------------------------


def test_daily_closes_parses_exact_decimals() -> None:
    closes = provider(reply(200, TIME_SERIES_OK)).daily_closes(
        "aapl", date(2026, 9, 28), date(2026, 9, 29)
    )

    assert [(c.symbol, c.day, c.close) for c in closes] == [
        ("AAPL", date(2026, 9, 28), Decimal("338.39999")),
        ("AAPL", date(2026, 9, 29), Decimal("329.39999")),
    ]


def test_daily_closes_requests_end_plus_one_day() -> None:
    # Our range is inclusive; Twelve Data's end_date is exclusive.
    rec = Recorder(200, TIME_SERIES_OK)
    provider(rec).daily_closes("AAPL", date(2026, 9, 28), date(2026, 10, 2))

    params = rec.requests[0].url.params
    assert rec.requests[0].url.path == "/time_series"
    assert params["interval"] == "1day"
    assert params["start_date"] == "2026-09-28"
    assert params["end_date"] == "2026-10-03"


def test_daily_closes_sorted_even_if_api_returns_newest_first() -> None:
    newest_first = {**TIME_SERIES_OK, "values": list(reversed(TIME_SERIES_OK["values"]))}
    closes = provider(reply(200, newest_first)).daily_closes(
        "AAPL", date(2026, 9, 28), date(2026, 9, 29)
    )

    assert [c.day for c in closes] == [date(2026, 9, 28), date(2026, 9, 29)]


def test_daily_closes_no_trading_days_is_empty_list() -> None:
    weekend = (date(2026, 10, 3), date(2026, 10, 4))

    assert provider(reply(400, NO_DATA)).daily_closes("AAPL", *weekend) == []


def test_daily_closes_rejects_start_after_end_without_calling_api() -> None:
    rec = Recorder(200, TIME_SERIES_OK)

    with pytest.raises(ValueError):
        provider(rec).daily_closes("AAPL", date(2026, 10, 2), date(2026, 10, 1))
    assert rec.requests == []


def test_daily_closes_malformed_row_is_provider_error() -> None:
    bad = {**TIME_SERIES_OK, "values": [{"datetime": "2026-09-28"}]}  # no close

    with pytest.raises(ProviderError):
        provider(reply(200, bad)).daily_closes("AAPL", date(2026, 9, 28), date(2026, 9, 29))


def test_daily_closes_zero_price_is_provider_error() -> None:
    bad = {**TIME_SERIES_OK, "values": [{"datetime": "2026-09-28", "close": "0"}]}

    with pytest.raises(ProviderError):
        provider(reply(200, bad)).daily_closes("AAPL", date(2026, 9, 28), date(2026, 9, 29))


# --- latest_snapshot ------------------------------------------------------------


def test_latest_snapshot_parses_quote() -> None:
    snap = provider(reply(200, QUOTE_OK)).latest_snapshot("AAPL")

    assert snap.symbol == "AAPL"
    assert snap.price == Decimal("332.89001")
    assert snap.volume == 34350900
    assert snap.observed_at == datetime.fromtimestamp(1791230340, tz=UTC)  # last_quote_at


def test_latest_snapshot_falls_back_to_timestamp() -> None:
    quote = {k: v for k, v in QUOTE_OK.items() if k != "last_quote_at"}

    snap = provider(reply(200, quote)).latest_snapshot("AAPL")

    assert snap.observed_at == datetime.fromtimestamp(1791207000, tz=UTC)


def test_latest_snapshot_fx_has_no_volume() -> None:
    fx = {"symbol": "EUR/USD", "close": "1.13716", "timestamp": 1791207000}

    assert provider(reply(200, fx)).latest_snapshot("EUR/USD").volume is None


# --- errors ---------------------------------------------------------------------


@pytest.mark.parametrize("call", ["daily_closes", "latest_snapshot"])
def test_unknown_symbol(call: str) -> None:
    p = provider(reply(404, NOT_FOUND))

    with pytest.raises(UnknownSymbolError):
        if call == "daily_closes":
            p.daily_closes("ZZZZ", date(2026, 9, 28), date(2026, 9, 29))
        else:
            p.latest_snapshot("ZZZZ")


def test_rate_limit() -> None:
    with pytest.raises(RateLimitError):
        provider(reply(429, RATE_LIMIT)).latest_snapshot("AAPL")


def test_rate_limit_is_a_provider_error() -> None:
    assert issubclass(RateLimitError, ProviderError)


def test_error_reported_with_http_200() -> None:
    # Twelve Data sometimes reports errors in the body with HTTP 200.
    with pytest.raises(UnknownSymbolError):
        provider(reply(200, NOT_FOUND)).latest_snapshot("ZZZZ")


def test_network_failure_is_provider_error() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError):
        provider(fail).latest_snapshot("AAPL")


def test_non_json_response_is_provider_error() -> None:
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    with pytest.raises(ProviderError):
        provider(html).latest_snapshot("AAPL")
